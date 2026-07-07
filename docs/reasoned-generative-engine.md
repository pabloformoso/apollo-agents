# Reasoned Generative Engine — Spec, Assumptions, Dependencies & Backlog

> Status: **spike built & validated (2026-07-07)**. The §11 thin vertical exists:
> `agent/generative/` + `scripts/spike_generative.py` + `tests/test_generative_*.py`
> (105 tests). Measured on the target Windows box: clock jitter p99 ≈ 0.1 ms
> (A3 ✅, wildly under budget); LLM (Azure) fits an 8-bar phrase but missed a
> 4-bar boundary once — reject-and-hold looped the phrase as designed (A1 ✅ at
> 8 bars, marginal at 4). The mind produced a musically coherent, reasoned
> mutation on the first try (A2/A4 ✅ pending ear test). Next: ear test, then
> EPIC C polish (true reason-ahead) and EPIC D/E.
>
> **v0.2 (same day):** added the **CC control lane** — synth (Surge) parameter
> control over the same MIDI transport. Two tiers: (1) `controls` role in the
> pattern-spec (LLM-authored CC ramps, e.g. open the filter over 8 bars), and
> (2) an **instant control layer** (`controls.py`): typed intents like "darker"
> trigger deterministic CC ramps on the next tick — reaction drops from ~2
> phrases (~30 s) to ~2 s, no LLM in the path. CC contract: CC 1 = energy
> (modwheel, native in Surge), CC 74 = brightness (MIDI-learn in Surge).
> Intents and `quit` are now handled mid-phrase. OSC control = documented
> follow-up (Surge XT has an OSC server; float precision, named params).
>
> Lineage: descends from the author's *Archaeopteryx* (Ruby generative MIDI engine,
> EuRuKo 2009) — but replaces **probabilistic matrices** with **reasoned acts**: an
> LLM that states *why* it plays what it plays, can be critiqued, and remembers.

---

## 1. One-paragraph thesis

Give Apollo a third "performance surface" alongside its WAV-crossfade pipeline: a
**live generative MIDI engine** where a real-time deterministic clock dispatches notes,
and an LLM reasons at **phrase cadence** (every 1–8 bars) to rewrite the patterns being
played. The dice of Archaeopteryx are replaced by *intention*: every mutation carries a
stated musical reason that can be logged, reviewed by the existing Critic phase, and
remembered across sessions in `memory.json`. The differentiator is not "smarter notes"
— it is **accountable, directable, self-revising** generative music.

---

## 2. Goals / Non-goals

### Goals
- G1. Real-time MIDI dispatch on a tight grid with **no LLM in the per-tick loop**.
- G2. Phrase-level **reasoned** pattern generation (intention, not probability).
- G3. Natural-language live direction ("darker", "bring it down", "build to a peak").
- G4. Every generative decision emits a machine-readable **reason** (log/critique/memory).
- G5. Reuse Apollo's existing live architecture (`LiveEngineProtocol`, `live_dj.py`
  event loop, checkpoints, memory) rather than forking a parallel system.
- G6. The deterministic core (pattern-spec → MIDI) is **fully unit-testable**.

### Non-goals (explicitly out of scope for v1)
- N1. Note-level real-time control by the LLM (physically impossible at tick rate — see A1).
- N2. Audio-to-symbol transcription (separate hard problem; the codex report flags it too).
- N3. Original "writes-a-hit" composition quality. v1 = *functional, directable* material.
- N4. Controlling Reason's internals via scripting (Reason is not scriptable — see D4).
- N5. Replacing the WAV pipeline. This is **additive**, a new engine, not a rewrite.

---

## 3. Functional specification

### 3.1 Two-plane architecture (the core constraint, made structural)
```
SLOW PLANE — "the mind"  (LLM, async, fires at phrase boundaries: every 1–8 bars)
  inputs : compact musical-state description + standing intent + recent history
  output : a pattern-spec (JSON) for the next phrase + a `reason` + `rethink_in_bars`
        │
        ▼  (hand-off is data, never audio)
FAST PLANE — "the muscle" (pure Python, real-time, fires every tick)
  holds   : the *current* pattern-spec
  does    : clock → interpret spec → emit MIDI messages → dispatch to a MIDI port
  signals : "phrase ending in N ticks → request next spec" back to the slow plane
```
This maps 1:1 onto Apollo today: `LiveEngineLocal` is a fast plane that runs its own
clock with no LLM; `live_dj.py` is a slow plane that consumes engine **events** and
decides at coarse cadence, talking only through `LiveEngineProtocol`. The new work is a
third implementation, provisionally **`LiveEngineGenerative`**, where "clips" are
live-generated MIDI patterns instead of WAV files.

### 3.2 The pattern-spec (slow plane → fast plane contract)
The LLM never emits notes in real time. It emits a small spec the fast plane loops:
```jsonc
{
  "for_bars": 8,
  "bpm": 122,
  "key": "8A",                       // Camelot — consistent with tracks.json
  "roles": {
    "kick": {"pattern": "4-on-floor", "vel": 110},
    "hats": {"pattern": "x.x.xx.x", "swing": 0.12},
    "bass": {"notes": [[0,"A1",1.0],[3,"E2",0.5]], "vel": 90},
    "pad":  {"chord": "Am9", "voicing": "wide", "vel": 60}
  },
  "reason": "16 bars of plateau — add bass syncopation + open hats to lift before peak",
  "rethink_in_bars": 8
}
```
Requirements on the spec:
- FS1. Deterministic: same spec + same seed → byte-identical MIDI message stream.
- FS2. Self-contained: fast plane needs no LLM to interpret it.
- FS3. Validated on ingest (bad key / BPM out of range / unknown role → reject, keep
  playing the previous spec; never drop audio).
- FS4. Carries `reason` (G4) and `rethink_in_bars` (controls slow-plane cadence).

### 3.3 Thin probabilistic layer at the bottom (the Archaeopteryx graft)
Reasoning sets **structure and intention**; cheap stochastic humanization adds **feel**:
velocity jitter, micro-timing, swing, occasional fills. The 2009 engine's idea lives
*underneath* the reasoning, not discarded. Hybrid > pure-reasoned (too rigid) and
> pure-probabilistic (no intention).

### 3.4 Human-in-the-loop
Direction is natural language, translated by the slow plane into spec mutations — reusing
the existing audience-request / checkpoint pattern (cf. `test_live_dj_audience_request.py`).
The 2009 workflow (live-editing Ruby) becomes live-*directing* in English.

### 3.5 Reason / observability loop (the real product)
- FS5. Each emitted spec's `reason` is logged with the musical state that prompted it.
- FS6. The Critic phase can review the reason trail cold (accountability).
- FS7. What worked (per genre/mood) is written to `memory.json` for future sessions.
- FS8. A novelty/repetition fingerprint over recent specs flags **mode collapse**
  (every phrase coming out the same) — mirrors the codex-live-bridge symbolic eval.

---

## 4. Assumptions (numbered, falsifiable — each is a bet to validate)

- **A1.** LLM latency (100s ms–seconds) forbids per-note reasoning; **phrase cadence
  (1–8 bars) is within budget.** → Validate in the spike: can the slow plane reliably
  return a spec before the current phrase ends?
- **A2.** A small JSON pattern-spec is **expressive enough** to sound musical when looped,
  yet **small enough** for low-latency generation. → Validate: does a hand-written spec
  loop sound like music, not a metronome?
- **A3.** Pure-Python timing (mido + a monotonic clock) is **tight enough** for groove
  without an audio-thread/C layer. → Validate: measure jitter on Windows; if audible,
  fall back to a sequencer lib or buffer-ahead scheduling.
- **A4.** The LLM produces **better-than-random** musical structure when given good state
  + intention (i.e., reasoning beats matrices on *direction*, not necessarily on novelty).
- **A5.** A compact, faithful **musical-state description** can be synthesized cheaply
  from the engine each phrase (energy, density, what's been tried). Reuses the
  `structured_problems`/memory vocabulary as a seed.
- **A6.** The existing `LiveEngineProtocol` is **general enough** to admit a generative
  engine without protocol changes (or with only additive ones).
- **A7.** Latency can be hidden by **reasoning one phrase ahead** (decide phrase N+1 while
  N plays), so the slow plane is never on the critical path.
- **A8.** Genre/mood + Camelot/BPM vocabulary already in Apollo **transfers** to steering
  generation (don't need a new music-theory model).

---

## 5. Dependencies

### 5.1 New runtime dependencies (all to be **optional**, like `madmom`/beatgrid)
| Dep | Purpose | Risk | Notes |
|---|---|---|---|
| `mido` | MIDI message construction/timing | Low | pure-Python, mature |
| `python-rtmidi` | MIDI I/O backend for mido | Low–Med | native build; Windows wheels exist |
| **loopMIDI** (Windows) | virtual MIDI port host→synth | Low | external app, free; user-installed |
| A sound source | actually make sound | **External unknown — see D-block** | see options below |
| `librosa` | (already present) round-trip verify if rendered to WAV | Low | reuse |

Packaging: `uv sync --group synth`, guarded imports, graceful "generative engine not
installed" message. **Never** make the core pipeline import these.

### 5.2 Sound-source options (pick per machine — the one real external unknown)
- **D-opt-1.** loopMIDI → **Reason Rack Plugin / Reason** as a MIDI receiver (uses the
  *Reason sound*, no scripting of Reason needed — it's just a MIDI sink).
- **D-opt-2.** loopMIDI → any standalone soft-synth (Surge XT, Vital, Dexed — free).
- **D-opt-3.** In-process **`pedalboard`** hosting a VST3 instrument (no DAW, deterministic,
  best for *offline* render + tests; can also feed live).
- **D-opt-4.** `fluidsynth` + a SoundFont (fully self-contained, CI-friendly, lower fidelity).
> Decision pending: **which source receives MIDI on the target machine?** This gates only
> the audible end; everything upstream of the MIDI port is pure Python and buildable now.

### 5.3 Internal dependencies (existing code to build on)
- `agent/live_engine.py` — `LiveEngineProtocol` (line ~152), `LiveEngineLocal`/`Browser`.
- `agent/live_dj.py` — slow-plane event loop (`run_live_session` / `_async`).
- `agent/phase_lock.py` — transition/phase coordination primitives.
- `agent/run.py` — agent runner, tool-schema builder, provider abstraction.
- `agent/tools.py` — tool convention `def tool(param, context_variables) -> str`;
  `start_live_session`, `suggest_bridge_track`/`insert_bridge_track`, `validate_audio`.
- `memory.json` + Critic phase — the accountability/memory home for `reason` trails.
- `tracks.json` — Camelot/BPM vocabulary to reuse; possibly a `source:"generated"` kind.

---

## 6. Open questions (resolve before/while building)
- Q1. ✅ **RESOLVED (brainstorm).** Sound source = **local virtual MIDI port** (loopMIDI
  on Windows) → external software that listens on it (a soft-synth, or Reason, etc.).
  This is the *Archaeopteryx model*: the transport is OS shared-memory, not a network —
  round-trip is microseconds, so it does not threaten the real-time tick budget. The
  fast plane targets a MIDI port, full stop; *what* makes sound is swappable and lives
  outside our code. D-opt-3/4 (`pedalboard`/`fluidsynth`) demoted to *offline render +
  CI* only, not the live path. See §10.
- Q2. Is reasoning "one phrase ahead" (A7) enough, or do we need a 2-phrase buffer?
- Q3. Pattern-spec vocabulary: how much music theory in the schema vs left to the LLM?
- Q4. ✅ **RESOLVED (brainstorm).** Start as a **standalone spike script**, not wired into
  the 7-phase orchestrator. Promote to `LiveEngineGenerative` + `start_generative_session`
  only after the spike proves timing (A3) and musicality (A2). See §10.
- Q5. How is "musical state" serialized for the slow plane (A5)? Minimal viable shape?
- Q6. Tempo/key changes mid-session — handled in-spec (`bpm`/`key`) or via engine commands?
- Q7. Where does this live in the 7-phase orchestrator — a new live phase, or standalone?
  (Deferred until after the spike — see Q4.)

---

## 7. Backlog (epics → stories, for later)

> Sizing: S ≈ <½d, M ≈ ½–1d, L ≈ 1–3d. Sequencing respects dependencies.

### EPIC A — Deterministic fast plane (no LLM, fully testable) — **do first**
- A-1 (M) Pattern-spec schema + validator (FS1–FS4). Reject-and-hold semantics.
- A-2 (M) `spec → MIDI message stream` interpreter (roles: kick/hats/bass/pad). Deterministic w/ seed.
- A-3 (S) Clock/scheduler: monotonic tick loop, BPM, swing; measure jitter (A3).
- A-4 (M) MIDI dispatch via mido/rtmidi → port; "phrase-ending" signal back out.
- A-5 (M) **Tests**: spec→MIDI determinism, bad-key/bad-BPM/unknown-role rejection,
  swing/velocity humanization bounds, clock tick accuracy. (Mandatory — mirrors
  `tests/test_live_engine_*.py`.)

### EPIC B — Sound source bring-up (resolve Q1)
- B-1 (S) Decide D-opt; document setup (loopMIDI/Reason/VST3/fluidsynth).
- B-2 (S) Smoke test: hardcoded spec → audible loop, no LLM. Validates A2/A3 end-to-end.
- B-3 (S) Optional offline path: spec → `pedalboard`/fluidsynth → WAV for CI + round-trip.

### EPIC C — Slow plane (reasoned generation)
- C-1 (M) Musical-state serializer (A5): compact "what's playing / energy / tried" blob.
- C-2 (M) Slow-plane prompt + tool: state + intent → next pattern-spec + `reason`.
- C-3 (M) Reason-ahead scheduling (A7): decide phrase N+1 while N plays; hide latency.
- C-4 (S) NL direction intake ("darker"/"lift") → intent mutation (reuse audience-request).
- C-5 (S) Thin probabilistic humanization layer (3.3) under the reasoning.

### EPIC D — Integrate as a Live engine
- D-1 (M) `LiveEngineGenerative` implementing `LiveEngineProtocol` (validate A6).
- D-2 (S) `start_generative_session` tool (Q4) wired through `live_dj.py` loop.
- D-3 (S) Decide orchestrator placement (Q7); checkpoints/quit/handoff parity.

### EPIC E — Accountability & memory (the differentiator)
- E-1 (S) Log `reason` + state per spec (FS5).
- E-2 (M) Critic-phase review of the reason trail (FS6).
- E-3 (M) Write what-worked to `memory.json` per genre/mood (FS7); recall next session.
- E-4 (S) Novelty/repetition fingerprint → mode-collapse flag (FS8).

### EPIC F — Hardening (later)
- F-1 Latency/jitter telemetry; graceful degradation if slow plane misses a deadline.
- F-2 Multi-role expansion (leads, arps, fills), per-role independent rethink cadence.
- F-3 Tempo/key automation mid-session (Q6).

### Recommended first slice (proves the whole thesis, ~½–1 day)
A-1 → A-2 → A-3 → A-4 (+A-5 tests) → B-1/B-2 → a single C-2 call at phrase boundary
with C-4 NL direction. If that feels musical at phrase cadence, the architecture holds
and EPIC D/E follow.

---

## 11. THIS ITERATION — the spike (scope: "thin vertical, with LLM")

Decision (§ AskUserQuestion, this session): build the **thin vertical** — EPIC A in full
*plus* one slow-plane call — so we answer the real question in one go: *does it sound like
directed music?* Not just "does the muscle tick."

### 11.1 Deliverable
A **standalone spike script** (not wired into the 7-phase orchestrator yet — see D-1/Q4):
provisionally `scripts/spike_generative.py` + a small `agent/generative/` core package so
the boundary (§D-2) is clean from day one and EPIC B can later wrap it.

Proposed shape (keeps the fast/slow boundary explicit):
```
agent/generative/
  spec.py        # pattern-spec dataclass + validator (A-1)  — pure, no MIDI, no LLM
  interpreter.py # spec → list[MidiEvent] (A-2)              — pure, deterministic+seed
  clock.py       # monotonic tick scheduler, BPM, swing (A-3)
  dispatch.py    # MidiEvent → mido/rtmidi → virtual port (A-4)
  state.py       # engine state → compact "musical state" blob (A-5 minimal)
  mind.py        # slow plane: state + intent → next spec + reason (C-2 single call)
scripts/spike_generative.py   # wires the above; REPL for NL direction (C-4)
tests/test_generative_*.py    # A-5: determinism, validation, swing/clock (no LLM)
```
Why a package, not one file: §D-2. `spec.py`+`interpreter.py`+`clock.py`+`dispatch.py`
are the **shared core** A and B both need. `mind.py` is the *only* piece B swaps for MCP.

### 11.2 Build order (each step de-risks the next)
1. **`spec.py` + tests** — freeze a *minimal* pattern-spec (resolves Q3 at MVP altitude:
   start theory-light — drum step-strings + explicit bass note list + a chord name; let
   the LLM do the musicality, the schema stays dumb). Reject-and-hold validation. **No
   external deps — fully testable in CI now.**
2. **`interpreter.py` + tests** — spec → deterministic MIDI-event list (seeded). Still no
   I/O, still CI-testable. This is the determinism guarantee (FS1).
3. **`clock.py`** — tick loop; **measure jitter** (kills/confirms A3, risk #1). Log p50/p99
   tick error. If audible-bad on Windows, note the fallback (buffer-ahead) before going on.
4. **`dispatch.py`** — send to the virtual port. **← FIRST STEP THAT NEEDS YOUR MACHINE**
   (loopMIDI + a synth listening). Everything above is pure and already green in CI.
5. **`state.py` (minimal)** — just enough for the mind to reason: current spec summary,
   bars elapsed, standing intent, last N reasons. (Seeds A5/Q5 without over-designing.)
6. **`mind.py` — ONE slow-plane call** — at each phrase boundary: state + intent → next
   spec + `reason`. Reuse `agent/run.py`'s provider abstraction (Anthropic/Azure/Ollama).
7. **`spike_generative.py`** — glue: clock runs, at phrase end calls mind, swaps spec,
   prints the `reason`. A REPL line lets you type "darker"/"more energy" → mutates intent.
   (A7 reason-ahead is a *stretch* for the spike; single-call inline is acceptable to
   start since local MIDI gives slack — note if the gap is audible.)

### 11.3 What this proves (and what it deliberately doesn't)
- Proves: A1 (latency fits at phrase cadence), A2 (spec is expressive *and* small enough),
  A3 (pure-Python timing holds), and the **whole reasoned thesis** end-to-end.
- Does NOT yet: implement `LiveEngineProtocol` (D), reason-ahead buffering (C-3), the
  Critic/memory accountability loop (E), or humanization (C-5). Those are post-spike,
  gated on the spike feeling musical.

### 11.4 The one dependency on YOU (the human)
Steps 1–3 and all tests I can build and verify **without your machine** (pure Python, CI).
Step 4 onward needs the audible end set up on this Windows box:
- **loopMIDI** installed (creates the virtual port), and
- **a synth listening on that port** — the Q1 decision said "swappable / external." For the
  fastest MVP I'd suggest a free standalone soft-synth (e.g. Surge XT) so we're not gated
  on Reason routing; Reason-as-sink can come later, it's the same MIDI port either way.
- Confirm the **provider** for `mind.py`: Anthropic / Azure / Ollama (whatever your `.env`
  already has wired — `run.py` auto-detects, so probably nothing to do).

### 11.5 Open micro-decisions (cheap, can default)
- Spec vocabulary depth (Q3): defaulting to **theory-light** unless you want chords/scales
  encoded richer. Easy to extend later; hard to simplify once code depends on it.
- Roles for the MVP: defaulting to **kick + hats + bass + one chord/pad** (4 roles) — enough
  to sound like music, few enough to reason about. More roles = EPIC F-2.

---

## 12. v0.3 — MUSICAL SENSE (ambient & lofi first)

> Planned 2026-07-07 after the spike was accepted. Goal: stop sounding like a
> validated grid and start sounding like *music from the channel's genres*.
> Ambient + lofi chosen first deliberately: they are Apollo's home genres
> (`tracks/lofi - ambient/`), tempo-tolerant, and forgiving of note-level
> simplicity while demanding exactly the things the spec can't do yet —
> harmony that moves, notes that breathe, and feel.

### 12.1 What "musical sense" decomposes into

| Gap today | What ambient/lofi need | Work item |
|---|---|---|
| Pad = 1 static chord, retriggered every bar | **Progressions**: chords change on chosen bars, sustain across bars, smooth **voice leading** between them | M-1 |
| Notes confined to one bar (≤4 beats) | **Drones/ties**: durations in bars, whole-phrase swells | M-2 |
| Key is metadata only — consonance is luck | **Scale guardrails**: Camelot → scale; validate bass/lead against it (reject-and-hold, like everything else) | M-3 |
| No melody surface | **`lead` role**: sparse phrase-level motifs, longer notes, octave range | M-4 |
| Humanization = velocity jitter only | **Feel profiles**: seeded micro-timing slop, ghost notes, swing depth per genre (lofi: sloppy-warm; ambient: near-rubato) | M-5 |
| Mind reinvents the genre every phrase | **Genre profiles**: tempo range, role palette, density defaults, feel profile, few-shot example specs — injected into the mind's prompt (`--genre lofi`) | M-6 |
| No arc — every phrase is "now" | **Section plan**: state carries a lightweight arc (intro → main → breakdown → outro) the mind proposes and then follows/revises | M-7 |
| One Surge = one timbre | **Multi-timbral routing**: per-role MIDI channels are already emitted; document Surge channel-split / second instance / port-per-role. Real fix is EPIC-B-class, not spec-class | M-8 (doc + setup first) |

### 12.2 Spec evolution (backward compatible)

- `pad.progression`: `[[bar, "Am9"], [4, "Fmaj7"], ...]` — replaces single
  `chord` (which remains valid = 1-entry progression). `hold: true` sustains
  through the next change instead of retriggering. Voicing chooses the
  **inversion minimizing voice movement** from the previous chord
  (deterministic, unit-testable — this is the single highest musical-value
  item in the plan).
- `bass.notes` / `lead.notes` durations allowed up to `for_bars * 4` beats.
- top-level `"feel"`: `{"timing_slop": 0-1, "ghost_notes": 0-1}` — rendered
  by the interpreter from the seeded RNG (determinism preserved).
- `key` gains teeth: notes outside the Camelot scale are rejected unless the
  spec sets `"chromatic": true` (escape hatch the mind must justify in
  `reason`).

### 12.3 Ordered slices (each independently shippable, daily-cycle sized)

1. **M-1 + M-2** — progressions, voice leading, cross-bar sustain. Ambient
   becomes *possible*: `--no-llm --genre ambient` seed spec sounds like a
   patient chord meditation, not a bar-stamped loop.
2. **M-3 + M-6** — scale guardrails + genre profiles w/ few-shot specs.
   The mind stops producing accidental dissonance and starts producing
   idiomatic material. (Prompt work + pure validation — cheap, high yield.)
3. **M-5** — lofi feel (timing slop, ghost hats, swing depth). The drum grid
   stops sounding quantized. A/B by ear against a reference lofi loop.
4. **M-4 + M-7** — lead motifs + section arc. This is where "directed music"
   becomes "a piece with a shape".
5. **M-8** — multi-timbral setup guide (Surge channel-split scenes A/B, or
   2nd instance on the port) so pad ≠ bass ≠ drums timbre. No code, pure doc,
   do whenever the single-timbre pain peaks.

### 12.4 Explicitly NOT in v0.3
- Audio analysis / mixing of the generative output into the WAV pipeline.
- New sound sources (still loopMIDI → whatever listens).
- MCP surface (unchanged: option B waits until the core sounds good).
- Odd meters, tempo automation (techno/deep-house pressure, not ambient/lofi).

### 12.5 Success test (ear, not metrics)
Play 3 minutes of `--genre lofi` to someone who knows the channel: do they
ask "which track is that?" rather than "what is that?" — that's the bar.

---

## 8. Risks (eyes open)
- R1. Phrase-level control ≠ note-level expressivity — accepted cost of the latency budget.
- R2. LLM pattern quality is "functional/directable", not virtuosic (N3). Win = control + memory.
- R3. Reason quality depends entirely on state fidelity (A5) — garbage state → generic music.
- R4. Live = non-deterministic = integration-test only; keep the deterministic core
  exhaustively unit-tested and treat reasoning as integration-level.
- R5. Native MIDI deps + external synth = setup friction; keep optional and documented.

## 10. Iteration decisions (brainstorm, this session)

Three decisions taken, captured here so the backlog reads in their light:

- **D-1. Option A first, Option B as a deferred spike.** Two surfaces were on the table:
  - **A — integrated engine:** the MIDI engine lives *inside* Apollo (brain + muscle in
    one process), like `LiveEngineLocal`. The engine must do everything itself.
  - **B — MCP MIDI server:** the MIDI surface is an external MCP server exposing
    "play / set-pattern" tools, that *any* agent could drive (the long game: an
    `MCP-Ableton` / `MCP-Reason` / `MCP-Serato` layer — none of which exists unified
    today; a real market gap).
  Decision: **build A now**, leave a documented spike for B. Rationale below.

- **D-2. A and B share the same core — so A is not throwaway for B.** The fast plane
  (clock + spec→MIDI interpreter + dispatch to a virtual port) is **identical** in both.
  The only difference is *who feeds the slow plane*: an in-process LLM call (A) vs. MCP
  tools receiving a pattern-spec from outside (B). If the core is built with a **clean
  boundary** ("a pattern-spec comes in → this plays it"), B becomes largely a *wrapper*
  around the same core. **A builds ~80% of B without trying.** Correct order: A proves the
  core sounds good; B (the reusable MCP asset) only earns its keep once that's true.

- **D-3. Latency is safe specifically *because* it stays local.** The whole real-time
  worry dissolves under the Archaeopteryx model: a virtual MIDI port has **no real network
  layer** — it's OS shared memory, microsecond round-trip. This is *why* A7 is mandatory
  (B over a real transport would be worse), and *why* the MCP in B must stay **local-only**
  to preserve the budget. An MCP is request/response: fine for the **slow plane** (brain),
  poison for the **fast plane** (muscle). So even in B, the muscle never crosses MCP.

> Net: this iteration = **EPIC A as a standalone spike**, with the core boundary drawn so
> that EPIC B (local MCP MIDI) can later wrap it. See the revised first slice in §7.

---

## 9. Provenance / references
- Archaeopteryx (Giles Bowkett, Ruby) — probabilistic generative MIDI; author's
  EuRuKo 2009 talk is the conceptual ancestor (this spec inverts its core: reason, not dice).
- `reporte-codex-musicians.html` (internal, 28 May 2026) — "adopt the pattern, not the
  repo"; source of the verify-by-playback + symbolic-eval ideas reused in §3.5.
- Apollo live stack: `agent/live_engine.py`, `agent/live_dj.py`, `agent/phase_lock.py`.
