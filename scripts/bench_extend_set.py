"""Bench: does a local LLM actually call ``extend_set`` under LIVE conditions?

``smoke_local_llm.py`` asks a toy question — one tool, three short ids served
on a plate — and every candidate model passes it. That gate cannot explain the
live failure it was meant to catch: gemma-4-e4b contributed **zero**
``extend_set`` calls across 17 real ``playlist_running_low`` pokes on stream,
answering with prose or an empty string while passing the smoke at 3.6 s.

The gap between the two is the whole point of this bench. Under live conditions
the model must, in one turn:

  1. read a ~110-line system prompt with ten tools competing for attention,
  2. realise it does not know any track id,
  3. call ``pick_next_track`` with a sane BPM window,
  4. copy a long UUID-suffixed id **verbatim** out of a markdown table,
  5. and call ``extend_set`` with it — inside the ~5 s grace window.

Everything below is the REAL live artefact, imported rather than
re-implemented, so a pass here means something:

  * ``_LIVE_DJ_SYSTEM`` — the full live prompt.
  * ``_LIVE_TOOLS`` + ``_build_openai_schemas`` — all ten tools, schema-built
    exactly as the live loop builds them.
  * ``_format_turn`` — the PLAYLIST_RUNNING_LOW turn text, verbatim.
  * ``pick_next_track`` / ``extend_set`` — the real tools against the real
    catalog, with the real eligibility screen, the real genre fence, and the
    real coaching error strings.
  * ``parse_textual_tool_call`` — the ``[llm-shim]`` the live loop applies when
    a small model writes its call as prose.

Only the audio engine is faked (a recorder that accepts appends), because the
bench must not open an audio device or touch a stream.

Because the live symptom is a RATE (0 of 17), a single trial proves nothing —
run enough trials to tell "never" from "sometimes".

Usage (from the main checkout — needs tracks/tracks.json):
    uv run python scripts/bench_extend_set.py --trials 10
    uv run python scripts/bench_extend_set.py --trials 10 \
        --models google/gemma-4-e4b prism-ml/bonsai-27b --genre aural

Exit code 0 if every model reached the pass bar, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.live_dj import (  # noqa: E402
    _LIVE_DJ_SYSTEM,
    _LIVE_TOOLS,
    _format_turn,
    _playlist_summary,
)
from agent.run import (  # noqa: E402
    _build_openai_schemas,
    _run_tool,
    parse_textual_tool_call,
)

PLAYLIST_RUNNING_LOW = "playlist_running_low"

# The live loop's own ceiling (agent/live_dj.py passes max_turns=5).
MAX_TURNS = 5

# The grace window before the deterministic fallback takes over. A trial that
# appends after this still counts as APPENDED — the engine would already have
# auto-picked, but the model's intent was right — so latency is reported
# separately rather than folded into the verdict.
GRACE_SEC = 5.0

# Pass bar: the live path needs the model to append reliably, not occasionally.
PASS_RATE = 0.7


# ---------------------------------------------------------------------------
# Outcome classification (pure — unit-tested in tests/test_bench_extend_set.py)
# ---------------------------------------------------------------------------

APPENDED = "appended"
REJECTED = "rejected"
PICKED_ONLY = "picked_only"
OTHER_TOOL = "other_tool"
SILENT = "silent"

_OUTCOME_ORDER = [APPENDED, REJECTED, PICKED_ONLY, OTHER_TOOL, SILENT]


def classify_outcome(tools_called: list[str], appended: bool) -> str:
    """Bucket one trial.

    ``appended`` is ground truth from the fake engine, not from the model's
    prose: a model that says "appended!" without calling the tool is exactly
    the live failure mode, so the engine's recorder is the only witness that
    counts.

    Order matters — a trial that called ``extend_set`` and had it rejected is
    a DIFFERENT failure (usually a hallucinated id) from one that never got
    past ``pick_next_track``, and both are different from prose-only silence.
    """
    if appended:
        return APPENDED
    if "extend_set" in tools_called:
        return REJECTED
    if "pick_next_track" in tools_called:
        return PICKED_ONLY
    if tools_called:
        return OTHER_TOOL
    return SILENT


def summarize(outcomes: list[str]) -> dict[str, int]:
    """Count outcomes, always returning every bucket (zeros included)."""
    return {name: outcomes.count(name) for name in _OUTCOME_ORDER}


def append_rate(outcomes: list[str]) -> float:
    """Fraction of trials that actually put a track on the queue."""
    if not outcomes:
        return 0.0
    return outcomes.count(APPENDED) / len(outcomes)


# ---------------------------------------------------------------------------
# Fake engine — the only faked collaborator
# ---------------------------------------------------------------------------

class RecordingEngine:
    """Stands in for the live engine: records appends, answers state reads.

    ``extend_set`` reaches the engine only AFTER the real catalog lookup,
    eligibility screen and genre fence have passed, so an append recorded
    here means the model produced a genuinely valid id.
    """

    def __init__(self, playlist: list[dict]) -> None:
        self.playlist = list(playlist)
        self.appended: list[dict] = []

    def append_track(self, track: dict) -> str:
        self.appended.append(track)
        self.playlist.append(track)
        return (
            f"Appended '{track.get('display_name', '?')}' at position "
            f"{len(self.playlist)}."
        )

    def get_state(self) -> dict:
        cur = self.playlist[0] if self.playlist else {}
        return {
            "state": "playing",
            "position_sec": 180,
            "current_track": cur,
            "next_track": None,
            "seconds_to_crossfade": 30,
            "playlist_remaining": 1,
        }


# ---------------------------------------------------------------------------
# Scenario construction from the real catalog
# ---------------------------------------------------------------------------

def load_catalog(catalog_path: Path) -> list[dict]:
    with open(catalog_path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("tracks", [])


def pick_scenario_tracks(catalog: list[dict], genre: str, n: int = 3) -> list[dict]:
    """Take the first ``n`` playable tracks of ``genre`` as the dying queue.

    Requires a BPM: the turn text quotes the current track's BPM, and the
    model's ``pick_next_track`` window is built from it.
    """
    genre = genre.strip().lower()
    out = []
    for t in catalog:
        folder = (t.get("genre_folder") or t.get("genre") or "").strip().lower()
        if folder != genre:
            continue
        if not isinstance(t.get("bpm"), (int, float)):
            continue
        if not isinstance(t.get("duration_sec"), (int, float)):
            continue
        if float(t["duration_sec"]) < 120:
            continue
        out.append(t)
        if len(out) >= n:
            break
    return out


def build_turn_text(current: dict, playlist: list[dict]) -> str:
    """The exact user-role turn the live loop builds for the poke."""
    event = {
        "type": PLAYLIST_RUNNING_LOW,
        "track": current,
        "seconds_remaining": 29.9,
    }
    state = {
        "state": "playing",
        "position_sec": 180,
        "current_track": current,
        "next_track": None,
        "seconds_to_crossfade": 29.9,
        "playlist_remaining": 1,
    }
    return _format_turn([event], [], state)


# ---------------------------------------------------------------------------
# Trial execution
# ---------------------------------------------------------------------------

def check_endpoint(client, models: list[str]) -> tuple[bool, str]:
    """Preflight: is the endpoint alive and does it serve these models?

    Learned the hard way (2026-08-14): the bench inherited a STALE
    ``OLLAMA_BASE_URL`` from a worktree ``.env`` written before LM Studio
    moved to the Tailscale node, pointed at the dead LAN host, and spent
    21 minutes collecting 20 identical timeouts — which the report then
    presented as a clean "0% append rate, silent=10" for both models. A
    dead host and a mute model produce the SAME bucket, so the run must
    be refused up front rather than explained afterwards.

    Returns ``(ok, detail)``; ``detail`` is "" on success.
    """
    try:
        served = {m.id for m in client.models.list().data}
    except Exception as exc:  # noqa: BLE001 — this IS the error path
        return False, f"endpoint unreachable: {type(exc).__name__}: {exc}"
    missing = [m for m in models if m not in served]
    if missing:
        return False, (
            f"not served: {', '.join(missing)}. Available: "
            + ", ".join(sorted(served))
        )
    return True, ""


@dataclass
class Trial:
    outcome: str
    seconds: float
    tools_called: list[str] = field(default_factory=list)
    shim_used: bool = False
    detail: str = ""


def run_trial(
    client,
    model: str,
    genre: str,
    playlist: list[dict],
    turn_text: str,
    schemas: list[dict],
    tool_index: dict,
    temperature: float,
) -> Trial:
    """One full poke→append attempt, looping tools like the live loop does."""
    engine = RecordingEngine(playlist)
    ctx = {"genre": genre, "_engine": engine}

    messages: list[dict] = [
        {"role": "system", "content": _LIVE_DJ_SYSTEM},
        {"role": "user", "content": "Live session started.\n" + _playlist_summary(playlist)},
        {"role": "assistant", "content": "On deck. Let's go."},
        {"role": "user", "content": turn_text},
    ]

    tools_called: list[str] = []
    shim_used = False
    detail = ""
    t0 = time.perf_counter()

    for turn in range(MAX_TURNS):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=schemas,
                temperature=temperature,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001 — a bench reports, never crashes
            return Trial(
                outcome=SILENT,
                seconds=time.perf_counter() - t0,
                tools_called=tools_called,
                shim_used=shim_used,
                detail=f"ERROR {type(exc).__name__}: {exc}",
            )

        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        text = (msg.content or "").strip()

        if not calls:
            # Same recovery the live loop applies before giving up on a turn.
            shim = parse_textual_tool_call(text, tool_index)
            if shim is None:
                detail = detail or (text[:70] if text else "(empty response)")
                break
            name, inputs = shim
            shim_used = True
            tools_called.append(name)
            result = _run_tool(name, inputs, ctx, tool_index)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"[tool result] {name}: {result}"})
            continue

        messages.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments or "{}",
                        },
                    }
                    for c in calls
                ],
            }
        )
        for call in calls:
            name = call.function.name
            tools_called.append(name)
            try:
                inputs = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                result = f"Tool error: unparseable arguments ({exc})"
            else:
                result = _run_tool(name, inputs, ctx, tool_index)
            if name == "extend_set":
                detail = result[:70]
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

        if engine.appended:
            break

    seconds = time.perf_counter() - t0
    outcome = classify_outcome(tools_called, bool(engine.appended))
    if outcome == APPENDED:
        detail = engine.appended[-1].get("display_name", "?")
    return Trial(
        outcome=outcome,
        seconds=seconds,
        tools_called=tools_called,
        shim_used=shim_used,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(model: str, trials: list[Trial]) -> str:
    counts = summarize([t.outcome for t in trials])
    rate = append_rate([t.outcome for t in trials])
    appended = [t for t in trials if t.outcome == APPENDED]
    in_grace = sum(1 for t in appended if t.seconds <= GRACE_SEC)
    med = _median([t.seconds for t in trials])
    shimmed = sum(1 for t in trials if t.shim_used)

    lines = [
        f"== {model} " + "=" * max(0, 56 - len(model)),
        f"  append rate   {rate:.0%}  ({counts[APPENDED]}/{len(trials)})"
        f"   {'PASS' if rate >= PASS_RATE else 'FAIL'}"
        f"  [bar {PASS_RATE:.0%}]",
        f"  within {GRACE_SEC:.0f}s grace  {in_grace}/{len(appended) or 0} of the appends"
        f"   (median turn {med:.1f}s)",
        "  breakdown     "
        + "  ".join(f"{k}={v}" for k, v in counts.items() if v),
    ]
    if shimmed:
        lines.append(f"  textual calls recovered by [llm-shim]: {shimmed}")
    for i, t in enumerate(trials, 1):
        chain = "→".join(t.tools_called) if t.tools_called else "(no tool call)"
        lines.append(f"    {i:2}. {t.outcome:<11} {t.seconds:5.1f}s  {chain}")
        if t.detail:
            lines.append(f"        {t.detail}")
    return "\n".join(lines)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1"),
        help="OpenAI-compatible endpoint (defaults to $OLLAMA_BASE_URL).",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=["google/gemma-4-e4b", "prism-ml/bonsai-27b"],
        help="Model ids to bench.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "lm-studio",
        help=(
            "API key for the endpoint. Local servers ignore it; a LiteLLM "
            "proxy 401s on anything that is not its virtual key. Defaults to "
            "LITELLM_API_KEY, then OPENAI_API_KEY, then 'lm-studio'."
        ),
    )
    parser.add_argument("--trials", type=int, default=10, help="Trials per model.")
    parser.add_argument("--genre", default="aural", help="Session genre to fence to.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.4,
        help="Sampling temperature (live default territory, not greedy).",
    )
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parent.parent / "tracks" / "tracks.json"),
    )
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        print(f"Catalog not found at {catalog_path} — run from the main checkout.")
        return 1

    catalog = load_catalog(catalog_path)
    playlist = pick_scenario_tracks(catalog, args.genre)
    if not playlist:
        print(f"No eligible '{args.genre}' tracks in the catalog.")
        return 1

    current = playlist[-1]
    turn_text = build_turn_text(current, playlist)

    from openai import OpenAI  # noqa: PLC0415 — keeps import cost off --help

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=180.0)

    probe = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=10.0)
    ok, why = check_endpoint(probe, args.models)
    if not ok:
        print(f"endpoint : {args.base_url}")
        print(f"PREFLIGHT FAILED — {why}")
        print(
            "Nothing was benched. A dead endpoint and a mute model both look "
            "like 'silent', so the run is refused rather than reported."
        )
        return 1

    schemas = _build_openai_schemas(_LIVE_TOOLS)
    tool_index = {fn.__name__: fn for fn in _LIVE_TOOLS}

    print(f"endpoint : {args.base_url}")
    print(f"genre    : {args.genre}  (fence active — out-of-genre appends rejected)")
    print(f"current  : {current.get('display_name','?')} "
          f"@ {current.get('bpm','?')} BPM / {current.get('camelot_key','?')}")
    print(f"tools    : {len(schemas)} real live tools")
    print(f"trials   : {args.trials} per model, temperature {args.temperature}\n")

    all_pass = True
    for model in args.models:
        trials = [
            run_trial(
                client, model, args.genre, playlist, turn_text,
                schemas, tool_index, args.temperature,
            )
            for _ in range(args.trials)
        ]
        print(format_report(model, trials))
        print()
        if append_rate([t.outcome for t in trials]) < PASS_RATE:
            all_pass = False

    if all_pass:
        print(f"VERDICT: every model appended in >= {PASS_RATE:.0%} of trials.")
        return 0
    print(f"VERDICT: at least one model fell below the {PASS_RATE:.0%} append bar.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
