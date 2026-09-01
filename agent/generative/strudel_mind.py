"""Slow plane, algorave lane: state + intent -> validated Strudel code (S2).

The sibling of `mind.py`, with the private JSON pattern-spec swapped for the
language the livecoding scene already standardised on: Strudel (TidalCycles in
the browser). Same safety philosophy, same shape — one completion call per
phrase boundary, no tool loop, no streaming — and the same reject-and-hold
contract: nothing the LLM writes reaches audio before a validator has run it,
one retry carries the validator's error back, and a second failure raises so
the caller keeps looping the code it already has. Audio never stops for a bad
idea.

Two things differ from `mind.py`, both on purpose:

- **Validation is out of process.** Strudel is JavaScript; the only honest way
  to know a pattern evaluates and emits events is to evaluate it, so the
  verdict comes from `node scripts/algorave-spike/validate.mjs` (docs/
  algorave-livecoding-plan.md §8.1) rather than from a Python schema. A missing
  Node or a missing `node_modules` is diagnosed BEFORE the subprocess, with the
  fix in the message — not as a traceback out of `subprocess`.
- **Mutation is the normal move.** In an algorave the code on screen is the
  performance, so when state carries `current_code` the mind edits that code
  instead of writing a fresh pattern; the `reason` then has to say what changed.

Model resolution is `GENERATIVE_MODEL` > `AGENT_MODEL` > provider default (the
BRIEF_MODEL precedent, #123) so the algorave lane can run on a different model
from the live DJ without splitting the provider wiring.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .state import to_prompt

# ---------------------------------------------------------------------------
# Where the validator lives. agent/generative/strudel_mind.py -> repo root.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "scripts" / "algorave-spike"
VALIDATOR = SPIKE_DIR / "validate.mjs"

# How much of the pattern the validator queries. Four cycles == four bars: long
# enough for `<a b>`-style per-bar alternation to actually be exercised, short
# enough that a rejection comes back in well under a second.
VALIDATE_CYCLES = 4
VALIDATE_TIMEOUT_SEC = 30.0

DEFAULT_KEY = "A:minor"

# ---------------------------------------------------------------------------
# The palette registry — ONE committed file (plan §10) that this module,
# validate.mjs and the spike pages all read, so sounds and banks are enabled
# by DATA, never by code. v1's "`bank()` is free-form" rule died with it: the
# registered sample map is machine-prefixed (RolandTR909_bd), so a bank the
# registry does not know — or a (sound, bank) pair its matrix lacks — resolves
# to no sample and plays SILENCE live.
#
# Three sound categories, told apart only by the `.bank()` rule: `drums`
# (bank-prefixed samples, they NEED the right bank), `synths` (oscillators, no
# samples) and `instruments` (sample-backed but bankless — piano.json keys the
# sound name directly, so a .bank() on one plays silence exactly like it does
# on a synth voice). The `roles` table rides in the same file (voice + register
# per melodic role): prompt-side data this module renders — the validator
# cannot attribute an event to a role, so it only requires the field's presence.
# ---------------------------------------------------------------------------
PALETTE_FILE = SPIKE_DIR / "palette.json"


def _load_palette_registry() -> dict:
    """Parse and shape-check the committed registry — loud on failure.

    Loud on purpose (the GENRE_THEMES lesson): a registry that silently
    degraded to a hardcoded fallback would drift from what the validator
    enforces, and the drift would surface as live 502s, not here.
    """
    try:
        registry = json.loads(PALETTE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"palette registry not found at {PALETTE_FILE} — it is a committed "
            "file (the validator, this prompt and the spike pages all read it); "
            "restore it from git."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"palette registry {PALETTE_FILE} is not valid JSON: {exc}") from exc
    for field in ("sources", "drums", "synths", "instruments", "roles", "banks", "genres"):
        if field not in registry:
            raise RuntimeError(f"palette registry {PALETTE_FILE} is missing {field!r}")
    return registry


PALETTE_REGISTRY = _load_palette_registry()
DRUM_SOUNDS = tuple(PALETTE_REGISTRY["drums"])
SYNTH_SOUNDS = tuple(PALETTE_REGISTRY["synths"])
INSTRUMENT_SOUNDS = tuple(PALETTE_REGISTRY["instruments"])
# The flat registry-wide vocabulary — what a genre-less validator run accepts.
PALETTE = DRUM_SOUNDS + SYNTH_SOUNDS + INSTRUMENT_SOUNDS


def _normalize_genre(genre: str | None) -> str:
    """The one spelling rule for genre keys, shared by brief/palette/validator."""
    return (genre or "").strip().lower()


def genre_palette(genre: str | None) -> dict:
    """`genre` -> {"drums", "synths", "instruments": tuples, "banks": {...}, "roles": {...}}.

    Mirrors validate.mjs's `paletteFor()`: a genre the registry knows narrows
    the vocabulary to its entry; an unknown one gets the registry-wide sets —
    not fatal, the `genre_brief` precedent. `instruments` and `roles` are read
    per-FIELD (a genre entry that predates the category inherits the
    registry-wide table rather than silently losing it), which is
    `paletteFor()`'s rule too.
    """
    entry = PALETTE_REGISTRY["genres"].get(_normalize_genre(genre))
    drums = entry["drums"] if entry else PALETTE_REGISTRY["drums"]
    synths = entry["synths"] if entry else PALETTE_REGISTRY["synths"]
    instruments = (
        entry["instruments"]
        if entry and "instruments" in entry
        else PALETTE_REGISTRY["instruments"]
    )
    roles = entry["roles"] if entry and "roles" in entry else PALETTE_REGISTRY["roles"]
    bank_names = entry["banks"] if entry else list(PALETTE_REGISTRY["banks"])
    return {
        "drums": tuple(drums),
        "synths": tuple(synths),
        "instruments": tuple(instruments),
        "banks": {name: tuple(PALETTE_REGISTRY["banks"].get(name, ())) for name in bank_names},
        "roles": {
            name: {"voices": tuple(spec["voices"]), "octaves": tuple(spec["octaves"])}
            for name, spec in roles.items()
        },
    }


class StrudelMindError(RuntimeError):
    """The slow plane failed to produce valid Strudel. Caller must hold."""


@dataclass
class StrudelCode:
    """One validated pattern: the code, its stated why, the validator's stats.

    `stats` is the verdict's own dict (events, cycles_checked, sounds,
    kick_four_on_floor, out_of_key) — carried through untouched so callers and
    benches read the validator's numbers rather than re-deriving them.
    """

    code: str
    reason: str | None = None
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The committed `scripts/algorave-spike/patterns/deephouse.js`, condensed to the
# REPL dialect: same roles, same voicings, same idiom, with the ES-module
# imports, the arrangement masks and the per-bar automation dropped. Everything
# here is proven — the module version of it is queried by the spike's vitest
# suite under the very scope (@strudel/core + mini + tonal) the validator uses.
FEW_SHOT_DEEPHOUSE = """// reason: seed groove — four-on-floor with the offbeat open hat, rolling A-minor bass
stack(
  s("bd*4").bank("RolandTR909").gain(0.92),
  s("[~ oh]*4").bank("RolandTR909").gain(0.55).pan(0.52),
  s("hh*16").bank("RolandTR909").gain("[0.44 0.38 0.40 0.39]*4").swingBy(1/8, 8).pan(0.46),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.62).room(0.25),
  n("[0 ~] [~ 0] [0 ~] [~ 7] [0 ~] [~ 0] [0 0] [~ 0]").add(n("<0 5>"))
    .scale("A1:minor").s("sawtooth").lpf("<400 400 620 800>").lpq(6)
    .attack(0.005).decay(0.12).sustain(0.35).release(0.08).gain(0.72),
  note("<[a3,c4,e4,g4] [f3,a3,c4,e4]>").struct("~ ~ ~ x ~ ~ ~ x").s("triangle")
    .attack(0.008).decay(0.16).sustain(0.12).release(0.3).lpf(3600).lpq(3)
    .delay(0.4).delaytime(0.1875).delayfeedback(0.32).room(0.55).gain(0.52)
).mul(gain(0.55))"""


SYSTEM_PROMPT = f"""You are the mind of a live algorave set. You write Strudel code
(TidalCycles in the browser), and that code is BOTH the music and the visual — it is
projected on screen while it plays, so it has to read like something a human wrote.

OUTPUT CONTRACT — obey it exactly:
- Reply with ONLY code. No prose, no explanation, no markdown fences.
- Optionally ONE leading comment line: `// reason: <one sentence>` — the musical WHY
  of this change. Nothing else may be commented.
- The code is a SINGLE expression evaluating to a pattern — normally `stack(...)`
  with one layer per role.
- Mini-notation strings are double-quoted: s("bd*4"), never single quotes.
- No `import`, no `require`, no `fetch`, no `eval`, no `process`. Code carrying any
  of those tokens is rejected before it is even evaluated.
- No `setcps`, `cps` or tempo calls of any kind: the harness owns tempo, and one
  cycle is one bar of 4/4.
- Express key musically with `.scale("{DEFAULT_KEY}")` (add an octave digit to the
  root — `.scale("A1:minor")` — to place the register) instead of hand-picking notes.

Sampled instruments come in two shapes and are written differently. A CHROMATIC
one (its map is keyed by note name — piano, balafon) is played with
`note("c3 eb3").s("piano")`. Everything else is a flat set of one-shots and is
walked with .n(i) — `s("stab").n("<0 3 5>")`. Writing note() over a one-shot set
is not an error and makes no noise: it picks one sample and transposes it, which
for a drum kit means one hit at three pitches instead of the kit. Reach for
note()/.scale on a one-shot only when transposing it is the point.

Idiom you can rely on: stack, s, n, note, gain; mini-notation ("bd*4", "[~ oh]*4",
"~ cp ~ cp", "<0 5>", "[a3,c4,e4]"); .struct, .add, .scale, .gain, .pan, .speed,
.late, .lpf/.lpq/.hpf, .unison/.detune/.spread, .vib,
.attack/.decay/.sustain/.release, .room/.roomsize,
.delay/.delaytime/.delayfeedback, .orbit, .swingBy, .every, .sometimesBy, .off,
.mask, .range, and `.mul(gain(x))` for a master trim (a plain .gain(x) on the stack
would overwrite every layer's own gain instead of scaling it).

HOW TO EVOLVE:
- If the state carries current code, that code is what the room is hearing RIGHT NOW.
  MUTATE it: keep its identity, change what the intent asks for, and name the change
  in the reason ("opened the bass filter", "dropped the stabs for a bar"). Do not
  rewrite the set from scratch — a livecoder edits in front of the audience.
- If there is no current code, write the opening pattern of the set.
- Change ONE thing well rather than five things vaguely. The reason must state a
  concrete musical decision, not a vibe.
- Do not repeat the recent reasons: if the state shows a plateau, move something.
"""


def palette_block(genre: str | None = "deep") -> str:
    """The per-genre PALETTE section of the prompt, straight from the registry.

    Lists each allowed bank WITH the sounds its sample set actually has: a
    (sound, bank) pair the matrix lacks resolves to no sample and plays
    silence live — so the prompt teaches the pairing and the validator gates
    it (the same registry on both ends, by construction). Instruments get
    their own line for the same reason: they are sampled, so the model would
    reasonably reach for `.bank()`, and that pair is silence too.
    """
    pal = genre_palette(genre)
    lines = [
        "PALETTE — the only sound names that exist:",
        f"  drums (via s()):   {', '.join(pal['drums'])}",
        f"  synth voices (via .s() on a note()/n() pattern): {', '.join(pal['synths'])}",
    ]
    if pal["instruments"]:
        lines.append(
            "  instruments (sampled, via .s() on note()/n(), never with .bank()): "
            + ", ".join(pal["instruments"])
        )
    lines += [
        "`.bank(...)` picks the drum machine. The banks for this set, each with the",
        "sounds it actually has — a pair outside this table plays SILENCE, so never",
        "pair a sound with a bank that lacks it:",
    ]
    lines += [f"  {name}: {', '.join(roles)}" for name, roles in pal["banks"].items()]
    lines.append(
        "Never put .bank() on a synth voice or an instrument. Any sound or bank not "
        "listed above is rejected — do not invent names."
    )
    return "\n".join(lines)


def roles_block(genre: str | None = "deep") -> str:
    """The ROLES section of the prompt — who plays where, from the registry.

    Voice + register per melodic role (plan §10): the voice is the layer's
    `.s()`, the register is the octave digit on its scale root or note names.
    Prompt-side data ONLY — the validator cannot attribute an event to a role,
    so nothing here is gated at runtime; the fence is CI consistency (every
    voice must resolve in the same scope's synths ∪ instruments, because a
    role teaching a voice the validator rejects would be a scripted 502).
    Empty roles ("" here) drop the section, the instruments-line precedent.
    """
    roles = genre_palette(genre)["roles"]
    if not roles:
        return ""
    lines = [
        "ROLES — who plays where. The voice is the .s() on that layer (first listed =",
        "the role's home sound); the register is the octave digit on its scale root or",
        "note names. Keep each role in its register — two roles in one octave fight",
        "for the same space:",
    ]
    for name, spec in roles.items():
        voices = " or ".join(f'.s("{voice}")' for voice in spec["voices"])
        lo, hi = spec["octaves"]
        register = f"octave {lo}" if lo == hi else f"octaves {lo}-{hi}"
        lines.append(f"  {name}: {voices} — {register}")
    return "\n".join(lines)


GENRE_BRIEFS: dict[str, str] = {
    "deep": """GENRE: deep house.
- ~122 BPM feel, one cycle = one bar of 4/4. Kick on every beat, s("bd*4"), 909 family.
- The offbeat open hat IS the genre: s("[~ oh]*4"). Under it, quiet closed 16ths with
  per-step gain variation and a touch of swing (.swingBy(1/8, 8)); clap on 2 and 4,
  low in the mix and a little roomy.
- Bass: syncopated 16th-grid line written as scale degrees through .scale("A1:minor"),
  .s("sawtooth"), lowpassed at 400-800 Hz with a little .lpq — rolling, never busy.
- Chords: minor-7th / maj7 stabs on offbeats, .s("triangle") with a pluck envelope,
  .delay + .room doing the character work.
- Pads: sustained chords as note("<[a2,e3,a3] [f2,c3,f3]>") on .s("supersaw") (or
  sawtooth) with .unison(3-5).detune(0.15-0.3).spread(0.7), slow .attack(1-2)/.release(2+),
  .lpf(700-1200), low .gain and .room high — a bed under the groove, not a part.
- Leads: one octave up on .s("pulse"), .s("square") or .s("supersaw"), monophonic
  through .scale(), .vib(4-6) for character and .delay for space — sparse, never a wall.
- Piano house: short offbeat piano stabs, .s("piano"), pluck envelope and a touch of
  .room — classic house; never a bank on it, and never a running line.
- Color, sparingly: a quiet 16th shaker (sh — TR727/TR808) makes the groove breathe;
  at a peak the ride (rd — 909/LinnDrum) can replace the offbeat oh; toms (ht/mt/lt)
  are a one-bar fill into a phrase change, never a running pattern; cb/tb/perc are
  single accents, low in the mix.
- Organic percussion (conga, bongo, cabasa, clave, agogo, shaker_small) answers the
  TR727, it does not double it: one or two hits a bar, placed off the steps the machine
  kit already owns, and well under it — n() there picks the sample variation, not a
  scale degree: n("<0 3>").s("clave").gain(0.3).
- Tonal color (fmpiano, balafon) is texture, never the lead: note("...").s("fmpiano")
  answering the stabs on the off-phrase, or a two-note balafon motif behind them —
  quieter than the chords, with .room doing the depth.
- Groove is king: change ONE element per phrase and keep the rest locked. Build by
  opening the bass .lpf and lifting hat gain; strip back by removing a layer, not by
  rewriting the groove.""",
}


# §9.2: the one line that turns a solo into a duet. It goes in the USER message,
# never in the system prompt — the system prompt is what `bench_strudel_mind.py`
# measures a model against, and a B2B set must stay comparable to a solo one.
# It is also per-call state ("am I alternating right now"), which is exactly what
# the user message is for.
B2B_USER_LINE = (
    "You are in a back-to-back set. recent_reasons carries your partner's moves "
    "— acknowledge the LAST one and answer it; never undo it."
)


def genre_brief(genre: str | None) -> str:
    """The idiom paragraph for `genre`, or "" — an unknown genre is not fatal."""
    return GENRE_BRIEFS.get((genre or "").strip().lower(), "")


def build_system_prompt(genre: str | None = "deep", key: str = DEFAULT_KEY) -> str:
    """Contract + palette + roles + genre idiom + key + few-shot, in that order.

    The palette comes from the registry, per genre — the sounds, each bank's
    actual sound set, and the role table (voice + register) are DATA
    (`palette.json`), so widening the lane's vocabulary never edits this
    module. The few-shot is appended for every genre: it teaches the REPL
    *dialect* (what a valid single expression looks like), which is not genre
    knowledge.
    """
    parts = [SYSTEM_PROMPT, palette_block(genre)]
    roles = roles_block(genre)
    if roles:
        parts.append(roles)
    brief = genre_brief(genre)
    if brief:
        parts.append(brief)
    parts.append(
        f'KEY: {key}. Every pitched layer goes through .scale("{key}") so the set stays '
        "in key by construction."
    )
    parts.append(
        "Example — Apollo's own committed deep house pattern, condensed to this dialect "
        "(match its register, then evolve it):\n" + FEW_SHOT_DEEPHOUSE
    )
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# LLM transport (mirrors mind.py's _default_llm, with the S2 model precedence)
# ---------------------------------------------------------------------------

def _resolve_model(fallback: str) -> str:
    """GENERATIVE_MODEL > AGENT_MODEL > the provider's default (#123 precedent)."""
    return os.getenv("GENERATIVE_MODEL") or os.getenv("AGENT_MODEL") or fallback


def _max_tokens() -> int:
    """Completion budget, env-tunable.

    Assume the model is a reasoner: it spends tokens thinking before the first
    character of code appears, and a budget that felt generous for chat (512)
    already truncated `brief_parser` into nothing. 4096 leaves room for a long
    stack after the thinking.
    """
    try:
        return int(os.getenv("GENERATIVE_MAX_TOKENS", "4096"))
    except ValueError:
        return 4096


def _default_llm(system: str, user: str) -> str:
    """Single completion against whichever provider the env has wired.

    Detection order is mind.py's / agent/run.py's: ANTHROPIC_API_KEY ->
    AZURE_OPENAI_API_KEY -> Ollama (the generic OpenAI-compatible path, which
    is what the tunnel's LM Studio / litellm gateway actually is).
    """
    provider = os.getenv("AGENT_PROVIDER", "")
    if not provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("AZURE_OPENAI_API_KEY"):
            provider = "azure"
        else:
            provider = "ollama"

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=_resolve_model("claude-opus-4-6"),
            max_tokens=_max_tokens(),  # the API requires it; same budget as below
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    extra: dict = {}
    if provider == "azure":
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        model = _resolve_model(os.getenv("AZURE_OPENAI_DEPLOYMENT", ""))
    else:  # ollama / any OpenAI-compatible local gateway
        from openai import OpenAI
        client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
        model = _resolve_model("gemma4:4b")
        extra["max_tokens"] = _max_tokens()

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **extra,
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Reply parsing
# ---------------------------------------------------------------------------

# A fenced block, with or without a language tag, tolerating a fence the model
# opened and never closed (a truncated reply still carries usable code).
_FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)(?:```|\Z)", re.DOTALL)
_REASON_RE = re.compile(r"^[ \t]*//[ \t]*reason[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)


def _extract_code(text: str) -> str:
    """Pull the code out of an LLM reply.

    The contract says "code only", and models add fences anyway — the same
    tolerance `mind.py._extract_json` applies to JSON, applied to code: take the
    fenced block if there is one, else the whole reply, trimmed.
    """
    match = _FENCE_RE.search(text or "")
    code = (match.group(1) if match else (text or "")).strip()
    if not code:
        raise StrudelMindError(f"no code in LLM reply: {(text or '')[:200]!r}")
    return code


def _leading_reason(code: str) -> str | None:
    """The `// reason:` line, if the model wrote one."""
    match = _REASON_RE.search(code)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# Validation (out of process — see module docstring)
# ---------------------------------------------------------------------------

def require_validator() -> None:
    """Fail with the FIX, before any subprocess is attempted.

    `node_modules` is gitignored and the spike is not part of the root install,
    so "it works on the box that ran npm install" is the normal state of the
    world. Each message names the missing thing and the command that supplies
    it — a traceback out of `subprocess` names neither.
    """
    if shutil.which("node") is None:
        raise StrudelMindError(
            "node was not found on PATH — the Strudel validator runs in Node. "
            f"Install Node.js, then run `npm install` in {SPIKE_DIR}."
        )
    if not VALIDATOR.exists():
        raise StrudelMindError(
            f"Strudel validator not found at {VALIDATOR} — check out the algorave "
            f"spike and run `npm install` in {SPIKE_DIR}."
        )
    if not (SPIKE_DIR / "node_modules").is_dir():
        raise StrudelMindError(
            f"{SPIKE_DIR / 'node_modules'} is missing — run `npm install` in "
            f"{SPIKE_DIR} before the mind can validate Strudel code."
        )


def _verdict_from_stdout(stdout: str) -> dict:
    """Parse the validator's ONE verdict line.

    Node is happy to print deprecation warnings before real output, so the
    verdict is the LAST line that parses as a JSON object with a `valid` key,
    not simply the last line.
    """
    for line in reversed([ln for ln in (stdout or "").splitlines() if ln.strip()]):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "valid" in obj:
            return obj
    raise StrudelMindError(
        f"validator produced no verdict JSON (stdout: {(stdout or '')[:200]!r})"
    )


def validate_code(
    code: str,
    *,
    cycles: int = VALIDATE_CYCLES,
    key: str = DEFAULT_KEY,
    genre: str | None = None,
    timeout: float = VALIDATE_TIMEOUT_SEC,
) -> dict:
    """Run `node validate.mjs` on `code` and return its verdict dict.

    `genre` narrows the validator to that genre's registry entry (sounds AND
    banks) — the same fence the prompt teaches; omitted or unknown, the
    validator enforces the registry-wide vocabulary.

    Raises `StrudelMindError` only for harness breakage (no Node, a crashed
    validator, unparseable output) — never for a rejected pattern, which comes
    back as `{"valid": false, ...}` so the caller can retry with the error.

    A validator that hangs is treated as a rejection, not breakage: a pattern
    whose query does not terminate is bad code, and one retry is cheaper than
    a wedged mind.
    """
    require_validator()
    cmd = ["node", "validate.mjs", "--cycles", str(cycles), "--key", key]
    normalized_genre = _normalize_genre(genre)
    if normalized_genre:
        cmd += ["--genre", normalized_genre]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(SPIKE_DIR),
            input=code,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "error": (
                f"validator timed out after {timeout:g}s — the pattern probably "
                "does not terminate; simplify it"
            ),
            "reason": None,
            "stats": {},
        }
    except FileNotFoundError as exc:  # node vanished between check and exec
        raise StrudelMindError(
            f"could not run node in {SPIKE_DIR}: {exc}. Install Node.js and run "
            f"`npm install` there."
        ) from exc

    if proc.returncode != 0:
        # §8.1: exit 0 whenever a verdict was computed, valid or not. Nonzero
        # means the validator itself broke, which is not the model's fault and
        # must not be retried as if it were.
        raise StrudelMindError(
            f"validator exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:300]}"
        )
    return _verdict_from_stdout(proc.stdout)


# ---------------------------------------------------------------------------
# The mind
# ---------------------------------------------------------------------------

class StrudelMind:
    """state + intent -> validated Strudel code. `llm` is injectable for tests.

    genre: key into GENRE_BRIEFS — appends the idiom paragraph to the system
    prompt so every phrase stays in the lane (the M-6 move, ported).
    """

    def __init__(
        self,
        llm=None,
        genre: str | None = "deep",
        key: str = DEFAULT_KEY,
        cycles: int = VALIDATE_CYCLES,
        validate_timeout: float = VALIDATE_TIMEOUT_SEC,
    ):
        self._llm = llm or _default_llm
        self._genre = genre
        self._key = key
        self._cycles = cycles
        self._validate_timeout = validate_timeout
        self._system = build_system_prompt(genre, key)

    # -- prompt ------------------------------------------------------------

    def _user_message(self, state: dict, intent: str) -> str:
        current = str(state.get("current_code") or "").strip()
        # The code is shown once, as code — repeating it inside the state JSON
        # would double the tokens and quote-escape the very thing we want the
        # model to edit. `b2b` is dropped for the same reason from the other
        # end: it is said once, as the sentence below, and a `"b2b": true` in
        # the state blob would be the same fact in a second dialect — leaving it
        # out is what makes the duet prompt the solo prompt plus ONE line (§9.2).
        rest = {k: v for k, v in (state or {}).items() if k not in ("current_code", "b2b")}
        parts = [f"Current musical state:\n{to_prompt(rest)}"]
        if current:
            parts.append("Code playing RIGHT NOW:\n" + current)
            parts.append(
                "MUTATE the code above to serve the intent — keep what works, change "
                "what the intent asks for, and say what you changed in the reason."
            )
        else:
            parts.append(
                "Nothing is playing yet. Write the opening pattern for this set."
            )
        parts.append(f"Standing intent: {intent.strip() or 'none'}")
        if (state or {}).get("b2b"):
            parts.append(B2B_USER_LINE)
        return "\n\n".join(parts)

    # -- the call ----------------------------------------------------------

    def next_code(self, state: dict, intent: str) -> StrudelCode:
        """One phrase decision: ask, validate, retry once, then hold.

        Reject-and-hold (FS3): the retry carries the validator's own error, so
        the model fixes the actual complaint instead of guessing. Two failures
        raise `StrudelMindError` carrying BOTH errors — the caller keeps playing
        the code it already has, and the operator can see whether the model
        failed the same way twice (a capability problem) or two different ways
        (a prompt problem).
        """
        user = self._user_message(state, intent)
        first_error: str | None = None

        for _ in (1, 2):
            prompt = user if first_error is None else (
                f"{user}\n\nYour previous code was REJECTED by the validator: "
                f"{first_error}\nReply again with ONLY corrected Strudel code "
                "(optionally one leading // reason: line)."
            )
            raw = self._llm(self._system, prompt)
            try:
                code = _extract_code(raw)
            except StrudelMindError as exc:
                error = str(exc)
            else:
                verdict = validate_code(
                    code,
                    cycles=self._cycles,
                    key=self._key,
                    genre=self._genre,
                    timeout=self._validate_timeout,
                )
                if verdict.get("valid"):
                    return StrudelCode(
                        code=code,
                        reason=verdict.get("reason") or _leading_reason(code),
                        stats=verdict.get("stats") or {},
                    )
                error = str(verdict.get("error") or "rejected without an error message")

            if first_error is None:
                first_error = error
            else:
                raise StrudelMindError(
                    "slow plane failed twice — holding current code "
                    f"(1st: {first_error}; 2nd: {error})"
                )

        raise StrudelMindError("slow plane produced no verdict")  # unreachable
