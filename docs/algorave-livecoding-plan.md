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
