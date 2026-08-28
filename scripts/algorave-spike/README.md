# algorave spike — iteration 0

Thirty seconds of deep house, played by a [Strudel](https://strudel.cc) pattern
that lives in this repo, with the pattern source on screen while it plays.
Implements `docs/algorave-livecoding-plan.md` §3–§5.

**North star:** `output/algorave/deephouse-30s.wav` — 48 kHz stereo, ≥30 s.
Everything else here exists to produce and defend that file.

Self-contained npm package. It does **not** touch `web/frontend` deps or the
root CI, and it serves on **4031** (4010/4020 are the prod stack, 4011/4021 are
dev — see the repo `CLAUDE.md`).

## Run it

```bash
cd scripts/algorave-spike
npm install

npm test           # deterministic pattern tests (no audio, no network)
node record.mjs    # -> ../../output/algorave/deephouse-30s.wav, prints its metrics
npm test           # now includes the WAV smoke

npm run serve      # http://127.0.0.1:4031 — Play / Record 32 s / Render offline
```

`record.mjs` starts its own server on an ephemeral port, so it does not collide
with `npm run serve`. Flags: `--route a|b`, `--out <path>`, `--seconds <n>`
(route A only), `--headed`, `--keep-intermediate`.

Network is needed at play/record time: the TR909 samples come from Strudel's CDN.
The pattern tests need neither network nor a browser.

## Files

| file | what |
|---|---|
| `patterns/deephouse.js` | the pattern **and** a plain-object `description`. Pure — imports only the engine, so Node can `queryArc` it. |
| `index.html` | the spike page: the pattern source on screen, Play / Record / Render. |
| `serve.mjs` | dependency-free static server, port 4031. |
| `record.mjs` | Playwright driver → WAV + metrics. |
| `wav.mjs` | ~150-line RIFF reader. Shared by `record.mjs` and the WAV test so the reported numbers and the asserted numbers come from one place. |
| `vitest.config.mjs` | test config + the `@kabelsalat/web` alias (see below). |
| `test/pattern.test.mjs` | spec §5.1 — 18 deterministic tests, CI-safe. |
| `test/wav.test.mjs` | spec §5.2 — 7 tests, `describe.skipIf` when the WAV is absent. |

## Pinned versions

Exact pins, no ranges. `package-lock.json` is committed.

| package | version |
|---|---|
| `@strudel/web` | 1.3.0 |
| `@strudel/webaudio` | 1.3.0 |
| `@strudel/core` | 1.2.6 |
| `@strudel/mini` | 1.2.6 |
| `@strudel/tonal` | 1.2.6 |
| `@strudel/transpiler` | 1.2.6 |
| `superdough` (transitive) | 1.3.0 |
| `@kabelsalat/web` (transitive) | 0.4.1 |
| `vitest` | 3.2.4 |
| `playwright-core` | 1.60.0 |

`playwright-core` 1.60.0 matches the `chromium-1223` build already installed
under `%LOCALAPPDATA%\ms-playwright`, so nothing is downloaded. `record.mjs`
finds the newest installed `chromium-*` itself; override with `SPIKE_CHROMIUM`.

Note the upstream repo moved: it is **codeberg.org/uzu/strudel**, not
github.com/tidalcycles/strudel. Raw GitHub URLs for package sources 404.

## Capture route: B (offline render)

The plan called route A the default and route B a timeboxed probe. The probe
succeeded immediately — `@strudel/webaudio` 1.3.0 exports

```js
renderPatternAudio(pattern, cps, begin, end, sampleRate, maxPolyphony, multiChannelOrbits, name)
```

which is a genuine `OfflineAudioContext` render producing 16-bit PCM at the
requested sample rate. **Route B is the default**: faster than real time (~11 s
for 32 s of audio), deterministic, and lossless — no opus round trip.

It still needs a browser (`OfflineAudioContext` + AudioWorklets), so Playwright
stays in the loop. It hands the result over by clicking a synthetic
`<a download>`, so the page borrows the Blob as it passes `URL.createObjectURL`
and swallows the click — no download plumbing.

**Route A stays implemented and verified** (`node record.mjs --route a`, and the
page's "Record 32 s" button): a `MediaStreamAudioDestinationNode` tap mirrored
onto every connection that reaches an `AudioDestinationNode`, into a
`MediaRecorder`. It is the route that will still work when the audio comes from
somewhere the offline renderer cannot reach — which is exactly the `/live` page.
Measured within 1 % of route B on RMS and peak.

Both routes end in `ffmpeg -ar 48000 -ac 2 -c:a pcm_s16le`, so the deliverable's
format is guaranteed regardless of what the page produced.

## API surprises vs. the strudel.cc docs

The plan's §7 flagged API drift as the top risk. It was right. Everything below
was found by reading the installed packages, not the docs.

1. **`@strudel/core` 1.2.6 cannot be imported from Node at all, out of the box.**
   `core/repl.mjs` does `import { SalatRepl } from '@kabelsalat/web'`;
   `@kabelsalat/web` 0.4.1 has no `exports` map and its `main` points at
   `dist/index.js`, which is an **IIFE** bundle (`var kabelsalat=function(l){…}`),
   not CommonJS. Node reports *"does not provide an export named 'SalatRepl'"*
   and every import of the package root dies — including `@strudel/mini`, which
   imports it. `dist/index.mjs` is the real ESM build and loads fine, so
   `vitest.config.mjs` aliases the specifier to it. The alias also needs
   `server.deps.inline`, because Vitest externalises `node_modules` by default
   and hands resolution back to Node, silently bypassing `resolve.alias`.

2. **There is no module-level `setcps` export.** In the REPL that name arrives
   through `evalScope`, injected by `repl()`. Programmatically you keep the repl
   object `initStrudel()` resolves with and call `repl.setCps(cps)`.

3. **`@strudel/web` bundles no samples.** Its `defaultPrebake()` only calls
   `registerSynthSounds()`, and its `@strudel/soundfonts` import is commented out
   upstream. `bank('RolandTR909')` resolves to nothing unless you register the
   map yourself. The URLs the strudel.cc REPL prebakes are on
   `https://strudel.b-cdn.net` (`tidal-drum-machines.json` +
   `tidal-drum-machines/machines/`), and that is what `index.html` uses.

4. **`maxPolyphony` is a hard global cap in an offline render, and its default of
   128 silently guts anything longer than a few bars.** `renderPatternAudio`
   schedules the *entire* pattern before `startRendering()`, so superdough's
   `activeSoundSources` set never drains — nothing has ended yet. Past event 128
   every new voice ramps an older one to zero. The first render of this pattern
   came out with bars 5–11 at 40 % of the level of bars 0–4 and 12–15, which
   looks exactly like a mix problem and is not one. The page passes 100 000.
   Route A is unaffected: in real time the voices drain normally.

5. **`miniAllStrings()` does not patch `String.prototype`.** It only installs the
   `reify` string parser, so bare strings passed *into* pattern functions become
   mini-notation but `'[0.3 0.14]*4'.mul(…)` throws. The REPL's transpiler is
   what rewrites string literals into `mini(…)` calls; without it, call `mini()`
   by hand.

6. **Control names in the event are not the method names.** `.lpf()` writes
   `cutoff`, `.lpq()` writes `resonance`. `.note()` values stay **strings**
   (`'a3'`), and `.scale()` emits capitalised names (`'A1'`). `hap.whole.begin`
   is a `Fraction`; call `.valueOf()`. The tests assert against this verified
   shape, which is why they are worth having.

7. **The render is not bit-reproducible.** The *pattern* is fully deterministic
   (`test/pattern.test.mjs` proves it), but superdough builds its reverb impulse
   response from `Math.random()` (`reverbGen.mjs`), so two renders of the same
   pattern differ in the tail. Measured spread over repeated runs: RMS and peak
   within ±0.3 %. Structure and level are reproducible; a checksum is not, so do
   not build a golden-file test on this.

## The music (spec §4)

122 BPM, A minor (8A), one cycle = one bar, 16 bars. Seven roles, each a
separate export so tests can query them in isolation:

| role | bars | what |
|---|---|---|
| `kick` | 0–16 | four-on-the-floor, `RolandTR909` |
| `openHat` | 0–16 | offbeat 8ths — the deep house signature |
| `closedHat` | 0–16 | 16ths, accented, `swingBy(1/8, 8)` ≈ 15 ms push on the off-16ths, energy rising per section |
| `clap` | 4–16 | beats 2 & 4, own reverb bus |
| `bass` | 0–16 | 9 onsets/bar, syncopated, filtered saw; scale degrees so it is inside A natural minor *by construction*; roots walk A→F with the chords; `lpf` 400 → 620 → 800 across the arrangement |
| `stabs` | 4–16 | Am7 / Fmaj7 on the "and" of 2 and 4, delay + room, own orbit |
| `fill` | 15–16 | rising 909 snare roll into the loop point |

The arrangement is expressed as per-bar `<…>` words (`mask`, patterned `lpf`,
patterned gain) rather than callbacks, so every entry and every level is a fact a
test can query. `description` mirrors it as plain JSON.

### Levels

Seven layers into one bus clipped at unity (measured true peak 1.33), so the
stack ends with `.mul(gain(MASTER_TRIM))`. `.mul()` scales the gain field;
a plain `.gain(x)` would *overwrite* it and flatten the hat accents and the
fill's ramp. `MASTER_TRIM = 0.62` was measured, not guessed: render at 0.5, read
the peak, solve for a −1 dBFS target.

The hat energy curve is wider than it "should" be because the kick dominates
broadband RMS: the whole clap-and-stabs entry at bar 4 moves full-band RMS by
~3 %. `test/wav.test.mjs` therefore measures the arrangement **above 1.5 kHz**,
where the kick and bass are gone, and sees a clean +11 % step at bar 4.

## Measured output

`node record.mjs`, route B:

```
duration      31.967 s      (16.25 bars — the extra quarter bar lets the fill
sample rate   48000 Hz       and the delay/reverb tails ring into the loop point)
channels      2 (true stereo)
bit depth     16
RMS           0.14419  (-16.82 dBFS)
peak          0.88477  (-1.06 dBFS)
quietest 5 s  0.14201
render time   ~11 s
```

RMS and peak move by ~0.3 % between runs — see surprise 7. Route A
(`--route a`) lands within 1 % of these: RMS 0.14441, peak 0.87402.

## Deviations from the plan

- **Route B, not route A, is the default.** §3 allowed it if a real offline
  render existed. It does.
- **`index.html` does not embed the `@strudel/repl` web component.** It drives
  `@strudel/web` programmatically and prints the pattern source in a styled
  `<pre>`, which §3 lists as acceptable for iteration 0. Two reasons beyond
  convenience: the page `fetch`es and displays the *same file* it imports, so the
  code on screen can never drift from the code that is playing; and driving the
  graph directly is what makes the master tap and the offline render reachable.
  Adopting the real editor (with its live highlighting) belongs to the S3 stream
  slice, where the code needs to be *editable* on screen, not just visible.
- **Two files the §3 layout does not list:** `wav.mjs` (so the recorder's metrics
  and the test's assertions cannot disagree) and `vitest.config.mjs` (forced by
  surprise 1). Plus a local `.gitignore`, because the repo root only ignores
  `web/frontend/node_modules`.
- **The stabs are a synth, not an e-piano sample.** `@strudel/soundfonts` is
  commented out of `@strudel/web`'s prebake upstream, so there is no GM e-piano
  without adding another package and another CDN dependency. A `triangle` with a
  pluck envelope, `lpf`, delay and room carries the part for iteration 0.
- **`MASTER_TRIM` is not in §4** — §4 never mentions a mix level, and without one
  the render clips.
- **Spec §5.3 (advisory quality bench) was not run.** `scripts/quality_bench.py`
  cannot score an external WAV: it drives `agent.generative.bench.run_bench`,
  which *renders its own audio* from a `PatternSpec` over `GENRE_PACKS`. Feeding
  it this file needs a new `--wav` ingestion path. Worth deciding before the gate
  is meant to bind — and a worktree has no `tracks/` for the references anyway.

## What to try next (the `/live` slice)

The tap in `index.html` is the piece that transfers. `/live` already is a browser
graph captured by OBS, so wiring Strudel in means: mount `@strudel/web` next to
the existing deck players, give it its own orbit range, and crossfade the
Strudel bus against the WAV decks with the same curve `main.py` uses — the
pattern becomes one more deck rather than a separate mode. The pattern source
`<pre>` becomes the on-stream visual, so it should move to the live page early,
before the LLM starts writing patterns (S2) — a visible, human-readable pattern
is the thing that makes a wrong one obvious.

Self-host the samples before the stream depends on them: the CDN fetch is a
single point of failure that currently sits between "start the set" and "any
sound at all".
