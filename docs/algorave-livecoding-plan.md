# Algorave lane — adopt livecoding, don't rebuild it

> Status: **iteration 0 in progress (2026-08-28)**. Decision + spec for the first
> slice: 30 seconds of deep house recorded through a livecoding engine, with the
> code as a first-class visible artifact. Supersedes the "custom spec→MIDI→Surge"
> path as the *algorave* direction; the generative engine (docs/reasoned-generative-engine.md)
> and its surgepy/offline renderers stay for what they already do (offline render,
> quality bench, CI) — this lane does not fork them, it replaces their role as the
> live performance surface.

## 1. Why adopt instead of build

The 2026-07 generative engine proved the *reasoning* thesis (LLM mutates patterns
at phrase cadence, reject-and-hold keeps audio alive). But its pattern language is
a private JSON schema: the LLM had to be taught it (few-shot, guardrails), no
human can read it on screen, and every musical feature (swing, progressions,
fills) was reimplemented from scratch. The livecoding scene already solved this
layer and has a decade of idiom on top:

- **TidalCycles** (Haskell) — the reference pattern language (Alex McLean).
- **Strudel** — TidalCycles patterns in JavaScript/Web Audio, same mini-notation.
- **Sonic Pi / FoxDot / SuperCollider** — same family, different hosts.

Three properties make the standard language strictly better for Apollo:

1. **LLMs already speak it.** Tidal/Strudel mini-notation is all over training
   data. The mind stops needing a bespoke schema lesson; validation gets easier,
   quality gets better, for free.
2. **The code IS the visual.** Algorave's defining move ("show us your screens")
   means the performance artifact and the stream visual are the same thing. Our
   custom JSON was never going to be projectable; `s("bd*4").bank("RolandTR909")`
   is.
3. **Idiomatic depth ships with the framework** — euclidean rhythms, pattern
   transformations (`every`, `sometimesBy`, `off`), per-event FX. We were on a
   multi-month path to reimplement a fraction of this.

## 2. Stack decision: Strudel first, Tidal-on-tunel as fallback

**Strudel** is the iteration-0 engine:

- It runs in the browser. Apollo's live audio path **already is a browser**
  captured by OBS (`/live` page → Web Audio → OBS → YouTube). Strudel drops into
  the existing product with zero new audio plumbing — no loopMIDI, no
  SuperCollider boot, no OS audio routing.
- Same pattern language as TidalCycles (it is the same project family), so
  nothing learned here is thrown away if we later want SuperDirt's synthesis
  depth: **TidalCycles + SuperDirt on `tunel`** (Linux, 32 cores, already our
  LLM host) is the documented phase-2 escape hatch if Strudel's Web Audio
  synthesis ceiling disappoints the ear test.
- Sonic Pi is discarded (GUI-first, weakest headless/embedding story).

## 3. Iteration 0 — "30 seconds of deep house" (this cycle)

**Deliverable:** `output/algorave/deephouse-30s.wav` — ≥30 s, 48 kHz stereo,
rendered by a Strudel pattern whose source lives in the repo, plus the spike
page that plays it with the code on screen.

**Everything lives in `scripts/algorave-spike/`** (self-contained npm package;
does NOT touch `web/frontend` deps or the root CI):

```
scripts/algorave-spike/
  package.json          # pinned @strudel/* deps + vitest + playwright (devDeps)
  README.md             # how to run, record, test; version pins documented
  patterns/deephouse.js # the pattern as a pure, importable module (see §4)
  index.html            # spike page: embeds the Strudel REPL/editor, code visible,
                        #   Play + Record controls
  serve.mjs             # tiny static server on :4031 (4010/4020 are prod, 4011/4021 dev)
  record.mjs            # Playwright: load page → play → capture 32 s → WAV via ffmpeg
  test/pattern.test.mjs # deterministic pattern tests (no audio, CI-safe)
  test/wav.test.mjs     # recording smoke (machine-local, skipped without the WAV)
```

**Audio capture route (A, default):** the page taps the master output with a
`MediaStreamAudioDestinationNode` + `MediaRecorder` (webm/opus), `record.mjs`
drives it with Playwright (chromium is already installed on this box), saves the
blob, converts with ffmpeg (host has 8.1). Headless-safe: MediaRecorder captures
the graph even with a null output device.
**Route B (probe, timeboxed ≤30 min):** if current `@strudel/*` exposes a real
offline/`OfflineAudioContext` render, prefer it (deterministic, no Playwright in
the loop). Do not fight it if undocumented — route A is known-good.

**Non-goals for iteration 0:** product/`/live` integration, LLM-written
patterns, chat steering, self-hosted sample banks (CDN samples acceptable in the
spike; self-hosting is listed for the integration slice).

## 4. Musical spec (deep house, the part the code must express)

- **122 BPM** (`setcps(122/60/4)`), key **A minor (8A)** — catalog vocabulary.
- One cycle = one bar. ~16 bars ≈ 31.5 s.
- Roles:
  - Kick: four-on-floor, 909-family bank.
  - Hats: offbeat open hat (the deep house signature), quiet closed 16ths with
    velocity/gain variation; a touch of swing.
  - Clap/snare: beats 2 & 4, low in the mix.
  - Bass: rolling syncopated A-minor line (offbeat pushes, octave movement),
    filtered saw (`lpf` ~400–800 Hz), all pitch classes ⊂ A natural minor.
  - Chords: Am7 / Fmaj7 stabs on offbeats, e-piano/pluck character, delay +
    room reverb, entering at bar 4.
- Arrangement (audible progression, not a static loop): bars 0–4 kick+hats+bass;
  4–8 add clap+stabs; 8–12 open the bass filter / raise hat energy; 12–16 full
  groove with a small variation (`every`/fill) into the end.
- The pattern module must export the pattern AND a plain-object description
  (bpm, key, roles, section map) so tests and future tooling don't parse code.

## 5. Test plan

Mandatory (repo rule: no function/endpoint without tests):

1. **Deterministic pattern tests** (`test/pattern.test.mjs`, vitest, no audio,
   no network — CI-candidate): pattern imports pure; `queryArc(0, 1)` and
   `(0, 16)` produce events; kick fires at 0/.25/.5/.75 of every cycle; clap at
   2 & 4; every bass/chord pitch class ∈ A natural minor; section map honored
   (stabs absent before bar 4, present after); event counts stable across two
   queries (determinism).
2. **Recording smoke** (`test/wav.test.mjs`, machine-local like
   `render_surge_live.py`): WAV exists, duration ≥ 30 s, 48 kHz stereo,
   0.02 < RMS, peak < 0.99 (no clipping), non-silent in each 5 s window.
3. **Quality bench (advisory)**: run the WAV through the existing
   `scripts/quality_bench.py` deep references — the project's own
   definition-of-done gate for generated audio. Advisory this cycle, gate later.
4. CI wiring for (1) is a follow-up decision, not part of the spike (keep the
   root CI untouched).

## 6. Next slices (not this cycle — sized for the daily cycle)

- **S2 — the mind writes Strudel:** intent → Strudel code via tunel LM Studio
  (`GENERATIVE_MODEL` env, the BRIEF_MODEL precedent); validation = parse +
  `queryArc` in a Node subprocess (reject-and-hold, as ever); `bench_mind`
  measuring validity rate + latency per model over the tunnel (bench_extend_set
  pattern) BEFORE anything goes live. Measured 2026-08-28 on the JSON-spec mind:
  warm e4b 8.6 s / qwen3.5-9b 12.5 s, ~50 % invalid — the standard notation
  should improve validity; the bench proves or refutes that.
- **S3 — stream surface:** Strudel editor panel on the live page (code changing
  on screen = the visual; OBS already captures it), chat → intent → code edits,
  self-hosted samples, crossfade between pattern sets and WAV decks.
- **Fallback lane:** TidalCycles + SuperDirt headless on tunel if Strudel's
  synthesis ceiling hurts the ear test (SSH access works; jarvis has the cores).

## 7. Risks / honest unknowns

- `@strudel/*` API drift vs training data — the implementer MUST verify current
  package names/APIs against strudel.cc docs + npm before writing code, and pin
  versions.
- Default sample banks load from Strudel's CDN at eval time → network needed at
  record time (fine for the spike; self-host before the stream depends on it).
- MediaRecorder gives opus-compressed capture, not sample-exact output —
  acceptable for the ear test; route B or a `tidal-on-tunel` render is the
  lossless path if we ever need one.
- Web Audio synthesis ceiling (bass/keys character) — the ear test on this WAV
  decides whether phase-2 (SuperDirt) accelerates.

---

## 8. S2 spec — the mind writes Strudel (iteration 1, 2026-08-29)

**Thesis:** the slow plane emits Strudel REPL-dialect code — the language LLMs
already know — instead of the private JSON spec. Same safety philosophy as
`mind.py`: nothing the LLM writes can touch audio until it has been validated;
reject-and-hold; one retry carrying the validator's error.

### 8.1 Validator (Node, lives in the spike)

`scripts/algorave-spike/validate.mjs` — plain `node validate.mjs [--cycles N]
[--key "A:minor"]`, code on **stdin**, ONE JSON line on **stdout**.

- Evaluates REPL dialect (@strudel/transpiler + core/mini/tonal evalScope — no
  webaudio, no network, no audio). Known hazard: importing the `@strudel/core`
  package root breaks in plain Node (the `@kabelsalat/web` IIFE issue in the
  spike README); the vitest alias fix does not apply outside vitest — importing
  the package's dist file directly by path is the expected workaround. Verify.
- **Code contract for the LLM:** a single expression evaluating to a Pattern
  (typically `stack(...)`), double-quoted mini strings, optional first line
  `// reason: <one sentence>`. No imports, no `setcps` (the harness owns
  tempo). The validator REJECTS code containing `import`/`require`/`fetch`/
  `eval`/`process` tokens — hygiene against a confused model, not a security
  boundary against attackers.
- **Verdict JSON:** `{"valid": bool, "error": str|null, "reason": str|null,
  "stats": {"events": int, "cycles_checked": int, "sounds": [str],
  "kick_four_on_floor": bool, "out_of_key": [str]}}`. Exit 0 whenever a
  verdict was computed — valid OR invalid; nonzero only on harness breakage.
- **Validity:** evaluates without throwing; `queryArc(0, cycles)` yields ≥ 1
  event; every event's `s` ∈ the registry vocabulary (`palette.json`, per
  genre with `--genre`, registry-wide otherwise) and every `.bank()` must
  exist in the registry AND carry that sound — a pair the matrix lacks
  resolves to no sample and plays silence live. A bank on a synth voice, or
  on an `instruments` entry (sample-backed but NOT bank-prefixed — see §10),
  is rejected for the same reason, each with its own coaching message.
  (Supersedes v1's {bd, sd, hh, oh, cp, rim,
  triangle, sawtooth, square, sine} + free-form `bank()` — the §10 registry
  shipped 2026-08-29.) `out_of_key` (vs `--key`) is reported, NOT gating in
  v1 — Tidal idiom leans on `.scale()`.
- vitest tests: valid stack, syntax error, zero events, palette violation,
  token screen, reason extraction, `--cycles`.

### 8.2 Mind (Python)

`agent/generative/strudel_mind.py`, mirroring `mind.py`'s shape:
`StrudelMind(llm=None, genre="deep")` with
`next_code(state: dict, intent: str) -> StrudelCode`
(dataclass: `code`, `reason`, `stats`).

- Model: `GENERATIVE_MODEL` env > `AGENT_MODEL` (the BRIEF_MODEL precedent,
  #123). Provider detection as in `mind.py`; the ollama path sets an explicit
  completion budget (default 4096, env `GENERATIVE_MAX_TOKENS`) — the
  token-budget lesson.
- Prompt: Strudel-REPL system prompt with the deep idiom (tempo is the
  harness's, key via `.scale("A:minor")`, the palette above, few-shot = a
  condensed committed deephouse pattern); state carries `current_code` (empty →
  generate; non-empty → **mutate it** per the intent — the algorave move),
  `bars_elapsed`, `recent_reasons`.
- Validation: subprocess `node validate.mjs`, cwd = `scripts/algorave-spike`
  resolved from the repo root; a missing `node_modules` produces an error that
  says `npm install`, not a traceback. Reject → one retry with the validator
  error appended → `StrudelMindError` (caller holds the current code).
- pytest: mock-llm/mock-subprocess unit tests (happy, retry-recovers,
  double-fail, env precedence, validator-missing message, token-screen
  propagation) + ONE real-validator integration test, skipped cleanly when
  node or the spike `node_modules` is absent (backend CI has neither).

### 8.3 bench_mind (the gate BEFORE anything goes live)

`scripts/bench_strudel_mind.py` — the `bench_extend_set.py` lessons verbatim:

- PREFLIGHT the endpoint (models actually served) and refuse to run otherwise;
  `--base-url` explicit (default the tunnel `http://100.68.5.104:1234/v1`);
  `--models` list; `--trials N` (≥ 10 for a real read); one warm-up call per
  model excluded from stats (LM Studio JIT); raw per-trial JSONL under
  `output/quality/strudel-mind-bench/`.
- Trial mix: generate-from-empty and mutate-the-committed-pattern, alternating,
  over a fixed intent rotation ("darker", "build to a peak", "strip it back",
  "more swing").
- Report per model: valid-rate, breakdown {invalid_js, no_events, palette,
  token_screen, timeout}, latency p50/p95, a sample of reasons. The symptom is
  a RATE — read the breakdown, never just the pass line.

### 8.4 Non-goals (iteration 1)

Playing mind-written code on the spike page or /live; chat intake;
self-hosted samples; any change to `patterns/deephouse.js`.

---

## 9. Playground, human-in-the-loop, and B2B (design, 2026-08-29)

The load-bearing fact: **hot-swapping code without stopping audio is native to
Strudel** — `evaluate()` replaces the playing pattern at a cycle boundary;
that IS livecoding. So "who holds the pen" is pure UI/state on top of a
mechanism the framework already gives us, and the mind's mutation path
(`state.current_code` in §8.2) already accepts code written by ANYONE — it
never needs to know whether the last edit came from itself or from Pablo.

Three stages, each daily-cycle sized, each subsuming the previous:

1. **Playground** — the spike page grows an *editable* editor (the Strudel
   REPL component, or CodeMirror driving `@strudel/web`): edit → re-evaluate
   on the next cycle, plus a **"mind" button** that POSTs `{current_code,
   intent}` to a tiny local endpoint running `StrudelMind` and offers the
   mutation back as a diff (apply = evaluate). Local, detached from the
   stream: a jam/practice surface, and the audition bench for §10's packs.
2. **Human-in-the-loop (the pen)** — one control token: `pen ∈ {mind, human}`.
   Human takes the pen → the phrase scheduler stops asking the mind and the
   mind becomes an observer (state keeps accumulating, `recent_reasons` gains
   `"human: <what they changed>"` entries — diffed automatically, no typing).
   Hand back → the next scheduled call is simply
   `next_code(state.current_code = the human's code)` — the architecture from
   §8.2, unchanged. On stream, the pen holder is displayed: that moment of
   "the human grabs the code" is *content*.
3. **B2B** — a scheduler flips the pen every N bars (8/16): Apollo and Pablo
   alternating edits on the same running code, each answering the other's
   last move. Needs one prompt paragraph ("you are in a back-to-back;
   acknowledge your partner's last change and answer it, don't undo it") and
   a bar-counter — nothing structural. The audience (S3 chat intake) later
   becomes a third voice whispering intents to whoever holds the pen.

Sequencing: playground first (it is S3's editor panel built local-first),
then the pen, then the B2B scheduler on top.

### 9.1 The pen — contract (iteration 2, 2026-08-29)

State lives in the playground page; the server contract from iteration 1 is
already sufficient (it accepts `bars_elapsed` and `recent_reasons`).

- **Pen token**: `pen ∈ {mind, human}`, starts at `human` (loading a page must
  never fire LLM calls by itself). One toggle: *take the pen / hand to the
  mind*. The holder is displayed LARGE (stream-ready — OBS will crop this).
- **Phrase scheduler** (the mind's hand): runs ONLY while `pen === mind` AND
  playing. Every `phraseBars` bars (control in the UI, default 8) it POSTs
  `{code: current buffer, intent, bars_elapsed, recent_reasons}` to `/mind`
  and — this is what holding the pen MEANS — **auto-applies** the validated
  mutation into the editor and evaluates it, flashing the diff and the reason
  on screen. One request in flight max (a boundary reached while one is
  pending is skipped, not queued). A 4xx/5xx/network failure logs, keeps the
  current code looping (page-level reject-and-hold) and tries again at the
  next boundary.
- **Bars**: derived from the audio clock the page already owns —
  `bars_elapsed = floor(elapsed_since_play × cps)`. Precision beyond ±1 bar
  is NOT required (application happens on evaluate, which hot-swaps at the
  next cycle anyway); drift is irrelevant at this granularity.
- **Human edits become state**: while `pen === human`, every evaluate of a
  buffer that differs from the last evaluated one appends
  `"human: <summary>"` to `recent_reasons` — summarized automatically from a
  line diff (±N lines + a truncated first changed line), never typed. The
  ring keeps the last 5 (the mind's MAX_RECENT_REASONS convention).
- **Handoff is free**: taking the pen just stops the scheduler; handing back
  makes the next scheduled call `next_code(current_code = whatever is in the
  editor)` — §8.2 unchanged, no new server work.
- **Testability**: the scheduler/diff/ring logic ships as a pure module
  (`patterns/pen.js`) with vitest coverage (fire decisions, in-flight
  skipping, bar derivation, human-edit summaries, ring trimming); the page
  wires it. DOM wiring is browser-verified, as the playground's was.
- **Non-goals (iteration 2)**: the B2B alternation scheduler (stage 3), /live
  integration, chat intake, any server change.

### 9.2 B2B — contract (iteration 3, 2026-08-29)

B2B automates the toggle; everything else is §9.1 unchanged. The mind's turn
IS §9.1's mind-holds-the-pen; the human's turn IS human-holds-the-pen.

- **Mode**: `mode ∈ {free, b2b}`, starts at `free`; never persisted (a page
  wakes up free/HUMAN, same principle as the pen). One toggle + a
  `b2bBars` control (default 16, min 4, persisted like `phrase`).
- **The flip**: while `mode === b2b` AND playing, the pen flips every
  `b2bBars` bars. Pure decision in `pen.js`
  (`b2bDecide({barsNow, lastFlipBar, b2bBars, mode, playing}) → {flip, to}`),
  same consume-the-boundary semantics as `decide()` — a flip and a phrase
  fire on the same bar must not double-act: the flip wins, the mind's first
  fire is its next boundary (the §9.1 handoff rule already guarantees this).
- **Countdown on screen**: "✍/✦ pen flips in N bars" near the pen indicator —
  stream content, updated per bar.
- **The mind knows it is a duet**: the page sends `b2b: true` while in B2B;
  the server forwards it into `state["b2b"]`; `strudel_mind.py` appends ONE
  line to the USER message (system prompt untouched — the bench stays
  comparable): "You are in a back-to-back set. recent_reasons carries your
  partner's moves — acknowledge the LAST one and answer it; never undo it."
- **Human turn ending**: the mind reads the buffer AS-IS at its first
  boundary — unevaluated human edits are carried into the mutation (nothing
  is lost) but only *evaluated* edits produce a `human:` reason. Contract
  note for the performer: evaluate before your turn ends if the room should
  hear your move first.
- **Silence is a move**: a human turn with no edits simply hands the mind a
  ring with no new `human:` entry — no special casing.
- **Tests**: `b2bDecide` (flip cadence, consume semantics, flip-vs-fire same
  bar, mode/playing gates) in the spike's vitest; the `b2b` passthrough in
  `tests/test_algorave_playground.py`; the user-message line (present with
  `state["b2b"]`, absent without) in `tests/test_strudel_mind.py`.
- **Non-goals (iteration 3)**: /live integration, chat intake, per-turn
  time-based (non-bar) clocks, more than two performers.

## 10. Pattern packs — collections of banks / roles / sections

**Shipped 2026-08-29 (the registry core):** `scripts/algorave-spike/
palette.json` — sample `sources`, the drum-role and synth vocabularies, a
bank→sounds matrix (extracted from the registered tidal-drum-machines map:
TR909/TR808/TR707/TR727/LinnDrum/EmuSP12), and per-genre entries (`deep`:
15 roles, no misc/fx). Read by all three sides: `validate.mjs` gates sounds
AND (sound, bank) pairs per `--genre`; `strudel_mind.py` builds the palette
prompt (with the matrix — silence pairs are taught, not just rejected) and
passes `--genre`; both pages register `sources` at boot with the b-cdn URL
as fallback.

**Shipped 2026-08-30 (`instruments`, the third category):** sample-backed
sounds with NO bank. A drum is a bank-prefixed sample (`RolandTR909_bd`), a
synth is an oscillator, and an **instrument** is a sample map that keys the
sound name directly — `piano.json` — so `.bank()` on one resolves to nothing
and plays silence exactly the way it does on a synth voice. There is no
pitched-vs-percussive distinction: an instrument is simply a bankless sound.
Registry shape: a top-level `"instruments": [...]` (required, like the other
vocabularies) plus an optional per-genre `instruments` list; `paletteFor()`
and `genre_palette()` read it per-FIELD, so a genre entry written before the
category inherits the registry-wide list instead of silently having none.
First entry: `piano` (source `https://strudel.b-cdn.net/piano.json`, base
`https://strudel.b-cdn.net/piano/` — the map's own `_base` points at GitHub
raw, and `samples(json, base)` resolves `base || map._base`, so the explicit
base is what keeps the samples on the CDN). The pages needed no change: they
register every entry of `sources` generically.

**Shipped 2026-08-30 (`roles` — voice + register):** the melodic role table.
`"roles": {bass|stabs|pads|leads: {"voices": [...], "octaves": [lo, hi]}}`,
top-level REQUIRED / per-genre optional with per-field inheritance (the
`instruments` rule; both loaders shape-check the field so the two sides stay
one registry). `voices` is ordered — first is the role's home sound — and the
deep values are lifted from the committed idiom: bass sawtooth 1–2, stabs
triangle/piano 3–4, pads supersaw/sawtooth 2–3, leads pulse/square/supersaw
4–5. Prompt-side data ONLY: `roles_block()` renders it between the palette
and the genre brief (the voice is the layer's `.s()`, the register the octave
digit on its scale root or note names); the validator gates none of it — an
event cannot be attributed to a role. What IS fenced, in CI on both suites,
is resolution: every voice must live in the same scope's synths ∪
instruments, because a role teaching a voice the sound gate rejects would be
a scripted 502. An explicitly empty per-genre table drops the section from
the prompt (the instruments-line precedent).

Still §10 backlog: gain lanes, section templates, seed-per-pack, the Camelot
bridge, pitch-mapped collections. The original sketch:

Before the registry the vocabulary was hardcoded in two places (the §8.1
palette in the validator, `strudel_mind.PALETTE` + the genre brief in
Python). To scale to collections, ONE registry both sides read — the
`genres.py`/`patches.py` precedent, now for the Strudel lane:

- **Pack = data, not code**: per genre — allowed drum **banks** (which
  machines fit: 909/707 for deep, 808 for lofi…), **roles** with synth voice
  + register (bass `A1`, stabs octave 3–4…), gain lanes, **section
  templates** (16-bar arcs as per-bar mask strings — the committed
  `deephouse.js` idiom: `'<0 0 0 0 1 1 …>'`), and a seed pattern per pack.
- **Camelot bridge**: `tracks.json` speaks Camelot; Strudel speaks
  `"root:type"` (`.scale("A1:minor")`, root octave defaults to 3). A helper
  next to `scales.py` — `camelot_to_strudel("8A", octave=1) -> "A1:minor"` —
  makes every pack key-agnostic and lets a session inherit the key of the
  WAV set it interleaves with.
- **Pitch-mapped sample collections** (later): Strudel sample maps support a
  base pitch per file (`"g3": "path.wav"`), so melodic collections — including
  slices of Apollo's own catalog stems — can be played through `note()`
  correctly tuned. That is the door to "the mix quotes its own catalog".

### Curation rationale — the VCSL instruments (2026-08-30)

The second `sources` entry is https://strudel.b-cdn.net/vcsl.json (128
instruments). Dumping 128 names into a 4B's prompt would sink it, so the
registry adopts **eight**, chosen to answer what the TR727 cannot: six organic
percussion voices — `conga` (34 samples), `bongo` (28), `shaker_small` (16),
`cabasa` (6), `clave` (6), `agogo` (5), all index-only, played through `n()` —
and two tonal colors, `fmpiano` (22 samples, note-keyed C/E/G# across C0–C7)
and `balafon` (6, note-keyed C#3–F5), played through `note()`. Each one was
range-probed on the mirror before adoption. Two path facts are load-bearing:
the map's own `_base` is a **GitHub raw** URL (as tidal-drum-machines' is), so
the registry overrides it with the b-cdn mirror, and that mirror's path is
**case-sensitive** — `/VCSL/` serves, `/vcsl/` 404s, while the map itself is
lowercase `vcsl.json`. VCSL keys are bare names, unlike the machine-prefixed
`RolandTR909_bd`, so nothing collides and nothing carries a bank.

Rejected: everything pitched-but-orchestral (sax, recorders, timpani,
pipeorgan — wrong genre), the VCSL drum names that duplicate the machines at
lower groove value (`clap`, `hihat`, `cowbell`, `snare_*`, `bassdrum*`),
`triangles` (one plural away from the `triangle` synth voice — a name trap for
a small model), and the second variants of what we took (`balafon_soft`,
`shaker_large`, `tambourine2`) which buy a nuance the prompt cannot spend.
**Dirt-Samples was skipped entirely**: the CDN's `Dirt-Samples.json` is not the
classic SuperDirt library, it is a 2 KB nine-folder subset (casio, crow,
insect, wind, jazz, metal, east, space, numbers) whose `_base` is GitHub raw
with no b-cdn mirror. There is no house stab and no vocal chop in it; `jazz`
is an acoustic kit that would shadow the machine roles and `east` is Japanese,
not Latin, percussion. Nothing there earns a slot in a deep-house prompt.

### Reading list (URLs verified alive 2026-08-29)

- **The REPL itself** — https://strudel.cc — its *sounds* panel lists every
  registered bank/sound live: the fastest browser of what exists. Workshop
  ("getting started") linked from the front page.
- **Sounds & synths basics** — https://strudel.cc/learn/sounds/ (s(),
  note+s) and its sibling *Synths* page.
- **Sample maps** — https://strudel.cc/learn/samples/ — `samples()` with
  JSON maps, the `github:user/repo` shortcut, `@strudel/sampler` for serving
  your own folder locally, and per-sample base pitch. This page is the
  foundation of §10's collections.
- **Scales / tonal helpers** — https://strudel.cc/learn/tonal/ —
  `scale("root:type")`, `transpose`, `scaleTranspose`, `voicing()` (chord
  voicings with modes) and `rootNotes()`. `voicing()` is the upgrade path
  for the stabs.
- **Mini-notation** — https://strudel.cc/learn/mini-notation/ — the string
  language itself.
- **Full function reference** — https://strudel.cc/functions/intro/ — time
  modifiers, signals, random/conditional modifiers, LFOs, tonal, stepwise.
- **Drum machine banks** — https://github.com/ritchse/tidal-drum-machines
  (the collection: machines × drum types); the registered map is
  https://strudel.b-cdn.net/tidal-drum-machines.json. Browse the repo's
  `machines/` tree to pick banks per genre pack.
- **Upstream source** — https://codeberg.org/uzu/strudel (moved off GitHub;
  GitHub raw URLs 404 — spike finding).

### Curation rationale — the Dirt-Samples library (2026-08-31)

`samples('.../Dirt-Samples/master/strudel.json')` is the classic TidalCycles
library: **218 sound folders, 2038 samples**. It is registered as a fourth
source and a curated slice is added to `instruments`.

**No new category, and that is the point.** By the registry's own taxonomy
(`_doc`) a category is defined by the BANK RULE, and Dirt sounds are
sample-backed and not bank-prefixed — exactly what `instruments` already means.
The validator's instrument branch already refuses `.bank()` on them with the
right message. So this is a data change, not a code change, which is what §10
promised the registry would make possible.

**The handoff's dead end is not this.** `Dirt-Samples.json` on the b-cdn is a
2 KB nine-folder subset with no mirror. This is the library's own
`strudel.json`, from its own repo, whose `_base` already points at the raw
files. Different artefact, same name — worth knowing before dismissing it twice.

**What the fourteen add, by what we lacked:**

| | |
|---|---|
| `jvbass` | a sampled bass. The catalogue had none — every low end was an oscillator |
| `stab`, `house`, `hoover` | house stabs and the rave stab, an idiom with no voice here before |
| `arpy`, `juno`, `moog` | pitched plucks and synth keys with sample character |
| `pad` | a sampled pad beside the supersaw one |
| `space`, `wind` | texture for the ambient lane, which had none |
| `tabla` | hand percussion — a colour the six machines cannot make |
| `amencutup` | breaks, for a change of feel rather than a change of sound |
| `clubkick`, `realclaps` | a kick and a clap that are not machine-shaped |

Ten of them go into `genres.deep`; `hoover`, `amencutup`, `space` and `wind`
stay registry-wide, since rave stabs and jungle breaks are not deep house.
`jvbass` joins the `bass` role and `stab` the `stabs` role — the two that add an
idiom rather than another timbre.

**The hazard the tests now guard:** Dirt shares many names with the drum
machines (`bd`, `sd`, `hh`, `cp`, `perc`…). A curated name that collided would
be addressable two ways and mean two things — `s("bd")` bare would PLAY (Dirt's)
while the validator rejected it as a bankless drum. None of the fourteen
collide, and a test keeps it that way.

**Selection is `.n(i)`, not `.note()`.** These hold many variants —
`s("stab").n("<0 3 5>")` walks them. The prompt now says so; pitch-shifting is
for when you actually want it.

### Second pass — twenty-one more, by role (2026-09-01)

The first fourteen proved the route; these fill the roles the catalogue still
had nobody for. **330 more samples**, bringing the curated slice to 35 of the
library's 218 folders.

| role | added | why it was missing |
|---|---|---|
| kits & machines | `gretsch` (24), `bassdm` (24), `drumtraks` (13), `linnhats` (6), `hardkick` (6) | every drum was one of six machines; an acoustic kit was not available at all |
| hand percussion | `tabla2` (46), `hand` (17) | one tabla set was the whole of it |
| bass | `jungbass` (20), `bass3` (11) | `jvbass` alone |
| melodic | `sitar` (8), `sid` (12), `fm` (17), `bleep` (13), `sequential` (8) | no plucked strings, no chip voices, no FM |
| breaks | `breaks125` (2), `jungle` (13) | `amencutup` alone |
| texture | `birds3` (19), `bottle` (13), `metal` (10) | the ambient lane had wind and space |
| industrial | `industrial` (32), `dist` (16) | nothing for the cyberpunk end |

Ten go into `genres.deep` — the kits, the hand percussion, the basses and the
melodic voices that suit house. `sid`, `bleep`, `industrial`, `dist`, `jungle`,
`breaks125`, `birds3`, `bottle` and `metal` stay registry-wide: the genre fence
is there to be used, and a chip bleep in a deep house set should be a decision
somebody made rather than something the mind could reach for by default.

**Chosen by role and by what the catalogue lacked, not by ear.** These are
well-known folders of the Tidal library and the counts are the map's own, but
nobody has listened to them in this context yet — the palette browser auditions
on click, and the ear test is the performer's. Expect this list to be edited.

**The collision rule did the work again**: `bd`, `sd`, `hh`, `cp`, `perc` and
the rest of the bank-prefixed drum names are all present in Dirt and all
excluded, enforced by a test rather than by care.
