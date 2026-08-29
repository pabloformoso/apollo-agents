"""Bench: can a model actually WRITE valid Strudel — and how fast?

The S2 thesis (docs/algorave-livecoding-plan.md §6) is that a standard pattern
language beats our private JSON schema because LLMs already speak it. That is a
claim about a RATE, and the JSON mind's measured rate is the thing it has to
beat: ~50% invalid, warm 8.6 s (gemma-4-e4b) / 12.5 s (qwen3.5-9b) over the
tunnel on 2026-08-28. This bench produces the comparable number before any
mind-written code is allowed near the stream.

What it measures is the REAL path: it drives `StrudelMind` itself, so the
system prompt, the fence tolerance, the `node validate.mjs` verdict and the
one-retry reject-and-hold policy are all exactly what would run live. Only the
transport is explicit rather than env-detected — `--base-url` and `--models`
are arguments, because the 2026-08-14 lesson was that a stale env var silently
redirected a whole bench run to a dead host.

Lessons carried over from `bench_extend_set.py` verbatim:

  * PREFLIGHT and refuse. A dead endpoint and a mute model land in the same
    bucket; so do a missing `node_modules` and a model that cannot write
    Strudel. Both are checked up front, and the run is refused rather than
    reported.
  * One warm-up call per model, excluded from the stats — LM Studio's JIT load
    cost bonsai-27b 27.8 s cold vs 5.7 s warm, which is the difference between
    a FAIL and a PASS on latency.
  * The symptom is a RATE: >= 10 trials, and the breakdown is the finding, not
    the pass line. `invalid_js`, `no_events`, `palette` and `token_screen` are
    four different bugs with four different fixes (dialect, structure, prompt
    palette, prompt hygiene).
  * Raw per-trial JSONL under output/quality/strudel-mind-bench/, written as
    each trial completes so a killed run keeps what it measured.

Known bias, stated rather than hidden: the mutate trials seed the mind with the
same condensed deep-house pattern that its own system prompt carries as a
few-shot. That IS the live situation (the code on screen descends from the
seed), but it makes mutation easier than a cold edit of unfamiliar code.

Usage:
    uv run python scripts/bench_strudel_mind.py --models qwen/qwen3.6-27b
    uv run python scripts/bench_strudel_mind.py --trials 20 \\
        --models google/gemma-4-e4b qwen/qwen3.6-27b --out output/quality/run2

Exit code 0 if every model cleared the valid-rate bar, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.generative import strudel_mind  # noqa: E402
from agent.generative.strudel_mind import (  # noqa: E402
    FEW_SHOT_DEEPHOUSE,
    StrudelMind,
    StrudelMindError,
)

# The pattern a mutate trial starts from: the condensed REPL-dialect twin of
# scripts/algorave-spike/patterns/deephouse.js. The module itself cannot be the
# seed — it opens with `import` lines, which the validator's token screen
# rejects and a model would happily copy.
SEED_CODE = FEW_SHOT_DEEPHOUSE

# §8.3's fixed rotation. Four intents that pull in four different directions:
# down, up, out, and sideways.
INTENTS = ("darker", "build to a peak", "strip it back", "more swing")

WARMUP_INTENT = "keep it rolling"

GENERATE = "generate"
MUTATE = "mutate"

# Verdict buckets. `ok` is the only success; the rest are the §8.3 breakdown
# plus `mind_error` for everything that is not the model's musical failure.
OK = "ok"
INVALID_JS = "invalid_js"
NO_EVENTS = "no_events"
PALETTE = "palette"
TOKEN_SCREEN = "token_screen"
TIMEOUT = "timeout"
MIND_ERROR = "mind_error"

_VERDICT_ORDER = [OK, INVALID_JS, NO_EVENTS, PALETTE, TOKEN_SCREEN, TIMEOUT, MIND_ERROR]

# Same bar as bench_extend_set: a live surface needs a model that works
# reliably, not occasionally. Adjustable with --pass-rate.
PASS_RATE = 0.7

DEFAULT_BASE_URL = "http://100.68.5.104:1234/v1"
DEFAULT_OUT = "output/quality/strudel-mind-bench"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_bench_strudel_mind.py)
# ---------------------------------------------------------------------------

def plan_trials(n: int) -> list[tuple[str, str]]:
    """`n` (mode, intent) pairs: modes alternate, intents rotate every pair.

    Rotating the intent every TWO trials rather than every one keeps the design
    balanced — each intent is seen once in each mode — instead of permanently
    pairing "darker" with generate and "more swing" with mutate, which would
    make the two modes incomparable.
    """
    out: list[tuple[str, str]] = []
    for i in range(max(0, n)):
        mode = GENERATE if i % 2 == 0 else MUTATE
        out.append((mode, INTENTS[(i // 2) % len(INTENTS)]))
    return out


def classify_error(text: str) -> str:
    """Bucket a failure message into the §8.3 breakdown.

    The message from a double failure carries BOTH validator errors, so the
    bucket is the first signature found in the combined text — read the raw
    JSONL when the two attempts failed differently.

    The wording of the validator's errors belongs to `validate.mjs`, so each
    bucket matches several phrasings rather than one exact string: a bench that
    silently reclassifies every rejection as `invalid_js` because a message was
    reworded is worse than no breakdown at all.
    """
    low = (text or "").lower()
    if "timed out" in low or "timeout" in low:
        return TIMEOUT
    if any(k in low for k in (
        "forbidden token", "banned token", "disallowed token", "token screen",
        "not allowed", "blocked token",
    )):
        return TOKEN_SCREEN
    if any(k in low for k in (
        "no events", "zero events", "0 events", "produced no event", "empty pattern",
    )):
        return NO_EVENTS
    if any(k in low for k in (
        "palette", "unknown sound", "not a known sound", "unknown s(", "sound name",
    )):
        return PALETTE
    # Unrecognised wording: fall back on the tokens themselves before giving up.
    if any(k in low for k in (" import", "import ", "require(", "process.", "fetch(", "eval(")):
        return TOKEN_SCREEN
    if "failed twice" in low or "reject" in low or "syntax" in low:
        return INVALID_JS
    return MIND_ERROR


def looks_like_timeout(exc: BaseException) -> bool:
    """Did the transport give up, rather than the model fail?"""
    blob = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in blob or "timed out" in blob


def summarize(verdicts: list[str]) -> dict[str, int]:
    """Count every bucket, zeros included — a bucket that never fires is a fact."""
    return {name: verdicts.count(name) for name in _VERDICT_ORDER}


def valid_rate(verdicts: list[str]) -> float:
    if not verdicts:
        return 0.0
    return verdicts.count(OK) / len(verdicts)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile. 0.0 for an empty sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * (pct / 100.0)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def slug(model: str) -> str:
    """A model id that is safe as a filename ('qwen/qwen3.6-27b' has a slash)."""
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in model).strip("-")


# ---------------------------------------------------------------------------
# Trials
# ---------------------------------------------------------------------------

@dataclass
class Trial:
    model: str
    mode: str
    intent: str
    latency_s: float
    verdict: str
    error: str = ""
    reason: str = ""
    code: str = ""
    stats: dict = field(default_factory=dict)


def make_llm(client, model: str, max_tokens: int):
    """The transport StrudelMind will call — deliberately the same shape as
    `strudel_mind._default_llm`'s OpenAI-compatible branch (model, messages,
    max_tokens; no temperature override), so what is benched is what runs."""

    def llm(system: str, user: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    return llm


def run_trial(mind, model: str, mode: str, intent: str, seed_code: str = SEED_CODE) -> Trial:
    """One phrase decision, timed and bucketed. A bench reports, never crashes."""
    state = {
        "current_code": seed_code if mode == MUTATE else "",
        "bars_elapsed": 16 if mode == MUTATE else 0,
        "standing_intent": intent,
        "recent_reasons": [],
    }
    started = time.perf_counter()
    try:
        out = mind.next_code(state, intent)
    except StrudelMindError as exc:
        return Trial(
            model=model, mode=mode, intent=intent,
            latency_s=time.perf_counter() - started,
            verdict=classify_error(str(exc)), error=str(exc)[:600],
        )
    except Exception as exc:  # noqa: BLE001 — transport errors are data here
        return Trial(
            model=model, mode=mode, intent=intent,
            latency_s=time.perf_counter() - started,
            verdict=TIMEOUT if looks_like_timeout(exc) else MIND_ERROR,
            error=f"{type(exc).__name__}: {exc}"[:600],
        )
    return Trial(
        model=model, mode=mode, intent=intent,
        latency_s=time.perf_counter() - started,
        verdict=OK, reason=out.reason or "", code=out.code,
        stats=out.stats or {},
    )


def trial_path(out_dir, model: str, stamp: str) -> Path:
    return Path(out_dir) / f"{stamp}-{slug(model)}.jsonl"


def append_trial(path: Path, trial: Trial) -> None:
    """One JSON line per trial, flushed as it happens (a killed run keeps its data)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(trial), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def check_endpoint(client, models: list[str]) -> tuple[bool, str]:
    """Is the endpoint alive, and does it serve exactly these model ids?

    `client.models.list()` is the GET {base_url}/models on the SAME base the
    trials will use — checking a different base would prove nothing. Returns
    (ok, detail); detail is "" on success.
    """
    try:
        served = {m.id for m in client.models.list().data}
    except Exception as exc:  # noqa: BLE001 — this IS the error path
        return False, f"endpoint unreachable: {type(exc).__name__}: {exc}"
    missing = [m for m in models if m not in served]
    if missing:
        return False, (
            f"not served: {', '.join(missing)}. Available: " + ", ".join(sorted(served))
        )
    return True, ""


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(model: str, trials: list[Trial], pass_rate: float = PASS_RATE) -> str:
    verdicts = [t.verdict for t in trials]
    counts = summarize(verdicts)
    rate = valid_rate(verdicts)
    all_lat = [t.latency_s for t in trials]
    ok_lat = [t.latency_s for t in trials if t.verdict == OK]

    lines = [
        f"== {model} " + "=" * max(0, 56 - len(model)),
        f"  valid rate    {rate:.0%}  ({counts[OK]}/{len(trials)})"
        f"   {'PASS' if rate >= pass_rate else 'FAIL'}  [bar {pass_rate:.0%}]",
        "  breakdown     "
        + ("  ".join(f"{k}={v}" for k, v in counts.items() if v) or "(no trials)"),
        f"  latency all   p50 {percentile(all_lat, 50):.1f}s"
        f"  p95 {percentile(all_lat, 95):.1f}s   (n={len(all_lat)})",
        f"  latency valid p50 {percentile(ok_lat, 50):.1f}s"
        f"  p95 {percentile(ok_lat, 95):.1f}s   (n={len(ok_lat)})",
    ]

    reasons = [t.reason for t in trials if t.verdict == OK and t.reason][:3]
    if reasons:
        lines.append("  sample reasons")
        lines.extend(f"    - {r[:100]}" for r in reasons)

    for i, t in enumerate(trials, 1):
        lines.append(
            f"    {i:2}. {t.verdict:<12} {t.latency_s:6.1f}s  {t.mode:<8} {t.intent}"
        )
        if t.error:
            lines.append(f"        {t.error.splitlines()[0][:110]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=(
            "OpenAI-compatible endpoint. Explicit on purpose: a stale env var "
            "once redirected a whole run to a dead host (2026-08-14)."
        ),
    )
    parser.add_argument("--models", nargs="*", default=["qwen/qwen3.6-27b"],
                        help="Model ids to bench (space or comma separated).")
    parser.add_argument(
        "--api-key",
        default=os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "lm-studio",
        help="Local servers ignore it; a LiteLLM proxy 401s on anything but its key.",
    )
    parser.add_argument("--trials", type=int, default=10,
                        help="Trials per model, excluding the warm-up (>= 10 for a real read).")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="Per-call transport timeout in seconds.")
    parser.add_argument("--max-tokens", type=int,
                        default=int(os.getenv("GENERATIVE_MAX_TOKENS", "4096")),
                        help="Completion budget — reasoners think before they code.")
    parser.add_argument("--genre", default="deep", help="Idiom brief for the mind.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Directory for the raw JSONL.")
    parser.add_argument("--pass-rate", type=float, default=PASS_RATE,
                        help="Valid-rate bar below which the run exits nonzero.")
    return parser


def _split_models(models: list[str]) -> list[str]:
    """Accept both `--models a b` and `--models a,b`."""
    out: list[str] = []
    for item in models:
        out.extend(part.strip() for part in item.split(",") if part.strip())
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models = _split_models(args.models)
    if not models:
        print("No models given — nothing to bench.")
        return 1

    # Preflight 1: the validator. Without it EVERY trial would bucket as
    # mind_error, which reads like a model failure and is not one.
    try:
        strudel_mind.require_validator()
    except StrudelMindError as exc:
        print(f"PREFLIGHT FAILED — {exc}")
        print("Nothing was benched: with no validator every trial fails identically.")
        return 1

    from openai import OpenAI  # noqa: PLC0415 — keeps import cost off --help

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=args.timeout)
    probe = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=10.0)

    # Preflight 2: the endpoint.
    ok, why = check_endpoint(probe, models)
    if not ok:
        print(f"endpoint : {args.base_url}")
        print(f"PREFLIGHT FAILED — {why}")
        print("Nothing was benched. A dead endpoint and a mute model look the same "
              "in the results, so the run is refused rather than explained afterwards.")
        return 1

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.out)

    print(f"endpoint : {args.base_url}")
    print(f"validator: {strudel_mind.VALIDATOR}")
    print(f"genre    : {args.genre}   key {strudel_mind.DEFAULT_KEY}")
    print(f"trials   : {args.trials} per model (+1 warm-up, excluded), "
          f"timeout {args.timeout:g}s, max_tokens {args.max_tokens}")
    print(f"raw      : {out_dir}\n")

    all_pass = True
    for model in models:
        mind = StrudelMind(llm=make_llm(client, model, args.max_tokens), genre=args.genre)

        warm = run_trial(mind, model, GENERATE, WARMUP_INTENT)
        print(f"-- {model}: warm-up {warm.verdict} in {warm.latency_s:.1f}s (excluded)")

        path = trial_path(out_dir, model, stamp)
        trials: list[Trial] = []
        for mode, intent in plan_trials(args.trials):
            trial = run_trial(mind, model, mode, intent)
            append_trial(path, trial)
            trials.append(trial)

        print(format_report(model, trials, args.pass_rate))
        print()
        if valid_rate([t.verdict for t in trials]) < args.pass_rate:
            all_pass = False

    if all_pass:
        print(f"VERDICT: every model wrote valid Strudel in >= {args.pass_rate:.0%} of trials.")
        return 0
    print(f"VERDICT: at least one model fell below the {args.pass_rate:.0%} valid bar — "
          "read the breakdown, not just this line.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
