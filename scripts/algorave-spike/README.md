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

`node record.mjs`, route B, after the brightness pass below:

```
duration      31.967 s      (16.25 bars — the extra quarter bar lets the fill
sample rate   48000 Hz       and the delay/reverb tails ring into the loop point)
channels      2 (true stereo)
bit depth     16
RMS           0.13062  (-17.68 dBFS)
peak          0.90256  (-0.89 dBFS)
quietest 5 s  0.12795
render time   ~11 s
```

RMS and peak move by ~0.3 % between runs — see surprise 7. The route
A/route B and pre-brightness-pass numbers above (RMS 0.14419, peak 0.88477,
route A within 1 %) predate this pass and were not re-verified against the
brightened pattern — only route B was re-run, since that is what the
brightness-pass measurement loop uses.

## Brightness pass (deep-house quality-bench brightening)

`agent/generative/quality.py`'s `analyze_wav` (the same function
`scripts/quality_bench.py` runs against catalog references) scored this
render as slightly dark against the deep-house references in
`agent/generative/quality_references.json`: `centroid_hz` and
`tilt_db_per_oct` both sat below the `deep` genre's band. This section is the
record of closing that gap — every number below came from the same loop:
`node record.mjs`, `docker cp` the WAV into the backend container (it has
`agent/generative` and its deps; a worktree does not), run `analyze_wav`
inside it.

### Measurement-basis correction

The first three iterations measured the render at its native 48 kHz. Partway
through, it turned out the committed references were extracted at 44.1 kHz
mono, and `centroid_hz`/`tilt_db_per_oct` are **not** sample-rate invariant in
practice: `spectral_centroid_hz` sums over the *entire* rfft range up to
Nyquist with no upper cutoff, so a 48 kHz render (Nyquist 24 kHz) and a
44.1 kHz one (Nyquist 22.05 kHz) of the same musical content integrate a
genuinely different slice of spectrum — 48 kHz native reads meaningfully
*lower* on this render than the 44.1 kHz-resampled version of the exact same
audio (`tilt_db_per_oct` is less affected, since that metric already masks
its regression to ≤16 kHz internally, but still shifts a little under
resampling). From iteration 3 onward every measurement was taken both ways;
the trajectory table below reports both, and the pass/fail calls against the
target bands use the 44.1 kHz **canonical** column, since that is the basis
the bands themselves were computed on. Iterations 1-2 only have a native-48 k
reading — reproducing the canonical one for them would have meant re-rendering
configurations already superseded, which was not worth spending render budget
on.

### Round 1 — hats and the stab filter (iterations 1-3)

The cheapest, safest energy to add was in the two roles that are already
broadband/high-frequency by nature: `closedHat` (gain raised and the four-step
velocity accent flattened upward) and `openHat` (flat gain raise only —
see the code comment on why its decay/release were deliberately left alone:
with none of `attack`/`decay`/`sustain`/`release` set, superdough's sampler
already plays the "oh" sample to its full natural length, so there was no
"longer tail" left to unlock). `stabs` kept its `triangle` oscillator (see
below) but opened its `lpf` and added `lpq` resonance so the fast 8 ms attack
transient rings the cutoff band, the same trick `bass` already used. Each
step traded `MASTER_TRIM` down to hold peak under control. By iteration 3,
`centroid_hz` had moved from the baseline's 4037.7 Hz to 5107.6 Hz
(native) — comfortably past the target band — while `tilt_db_per_oct` had
only crept from -5.03 to -4.16, still short of its band. Peak also touched
0.951 mid-pass, over the 0.95 target.

**Why `.s('triangle')` was never swapped for `square`/`sawtooth`, and why the
stab voice was never doubled an octave up:** `test/pattern.test.mjs` (not
this task's to edit) hard-codes the stabs' sound name in the final-bar
sound-name-set assertion, and hard-codes 8 raw onsets/bar for stabs in two
places (the role-level query and the same count filtered by `s === 'triangle'`
at the pattern level). A different oscillator name or a second stacked voice
at the same onset positions both fail one of those. Brightening the stab had
to happen through parameters that don't change its identity or event count:
filter cutoff, resonance, and decay.

### Round 2 — rebalance + the `air` layer (iterations 4-5)

The measurement-basis correction landed here too: on the canonical 44.1 kHz
basis, iteration 3's already-rendered WAV actually measured centroid 4957.7 Hz
(over the band) and tilt -4.47 (still under it) — confirming round 1's
overshoot-without-proportionate-tilt-gain problem was real, not a rendering
artifact.

The diagnosis: every round-1 lever (hat gain, stab cutoff/resonance) adds
energy mostly in the 3-6 kHz range, which `centroid_hz` (an energy-weighted
*linear*-frequency mean) is very sensitive to, but which is only mildly above
the log-frequency midpoint `tilt_db_per_oct`'s regression pivots on. Across
iterations 1-3 the two metrics moved at a fairly consistent, unfavourable
exchange rate: roughly 1100-1300 Hz of centroid per 1 dB/oct of tilt. Pushing
that same lever mix further would only run centroid further past its ceiling
for a shrinking tilt return.

Round 2 first pulled back the two round-1 changes that read as the most
centroid-expensive relative to their tilt contribution — `openHat` gain
0.80 → 0.55, `stabs` cutoff 4800 → 3600 Hz and `lpq` 6 → 3 — which alone
brought centroid back to 4535.0 Hz (canonical), comfortably mid-band. It then
added a new layer, `air`: the closed-hat sample itself, pitched up
(`speed()`) so its spectral content is transposed out of the crowded 3-6 kHz
region into 6-16 kHz where almost nothing else in the mix has energy, gated
to bars 8-16 (the `lift`/`peak` sections — chosen so it only *adds* to the
`carries the arrangement` test's later-section margins rather than inflating
the `intro`/`groove` baseline it's compared against), and deliberately kept
out of `roles`/`description.roles` since it is a mix-bus embellishment, not a
named musical part.

The first `air` calibration (iteration 4: gain 0.16, `speed(1.6)`, no
`.late()`, trim still 0.6) undershot on tilt — it landed at -4.69 (canonical),
*worse* than iteration 3's -4.47: the two round-1 pull-backs (`openHat`,
`stabs`) cost more tilt than this first, quiet `air` pass bought back. It also
failed outright: peak came in at 0.992, over even the hard-tested 0.99
ceiling, despite `air` being the quietest layer in the mix. The cause turned
out not to be level: `air`'s un-swung 16ths share 8 of their 16 hits/bar with
the exact instants `closedHat`'s own on-grid (unswung) hits land on, which are
themselves the same instants `kick` fires on — a three-way coincidence, four
times a bar, only in bars 8-15 where `air` is active.

Iteration 5 (final) fixed and re-tuned `air` in one pass, since it was the
last render in budget: `.late(1/32)` — a legitimate off-grid shaker
placement, not just a technical patch — moves every hit off that shared
instant, which alone dropped peak to 0.903 with no change in level. With the
spike gone there was room to push `air` harder to chase tilt further: gain
0.16 → 0.4, `speed(1.6)` → `speed(1.75)`. `MASTER_TRIM` also came down
0.6 → 0.55 for extra margin. Net result: tilt recovered to -4.35 (canonical,
better than iteration 3), but centroid — which the louder, more-transposed
`air` also feeds — came back up to 4831.5 Hz, 57.7 Hz past the top of the
band. Because the `.late()` fix and the `air` re-tune were not tested
separately (one render, both changes), it is not possible to say from this
data alone how much of the tilt recovery came from the louder `air` versus
how much headroom the peak fix alone bought back.

### Trajectory

All `centroid_hz`/`tilt_db_per_oct` pass/fail calls are against the
44.1 kHz canonical column. Target: centroid_hz [4336.9, 4773.8],
tilt_db_per_oct [-3.89, -3.03], advisory lufs [-18.0, -16.9], peak < 0.95.

| # | change | centroid (native 48 k) | centroid (canonical 44.1 k) | tilt (native) | tilt (canonical) | lufs | peak |
|---|---|---|---|---|---|---|---|
| 0 | baseline | 4037.7 | *n/m* | -5.03 | *n/m* | -18.03 | 0.885 |
| 1 | closedHat/openHat gain up, stab `lpf`/decay | 4537.4 | *n/m* | -4.64 | *n/m* | -17.66 | 0.942 |
| 2 | closedHat/openHat/stab pushed further | 4782.6 | *n/m* | -4.43 | *n/m* | -17.69 | 0.951 |
| 3 | closedHat/openHat/stab pushed further again | 5107.6 | 4957.7 | -4.16 | -4.47 | -17.67 | 0.944 |
| 4 | pulled openHat/stab back, `air` v1 (0.16 gain, speed 1.6) | *n/m* | 4535.0 | *n/m* | -4.69 | -17.86 | 0.992 (fail) |
| 5 (final) | `air` v2 (0.4 gain, speed 1.75, `.late(1/32)`), trim 0.55 | 5037.95 | 4831.5 | -4.16 | -4.35 | -18.59 | 0.903 |

*n/m = not measured on that basis at that iteration (see "Measurement-basis
correction" above).*

### Where this landed

Final (iteration 5, canonical basis): `centroid_hz` 4831.5 — **57.7 Hz above**
the band's top (4773.8). `tilt_db_per_oct` -4.35 — **0.46 short** of the
band's floor (-3.89). Advisory `lufs` -18.59, 0.59 below its floor
(report-only, not test-enforced — traded off deliberately, see below). Peak
0.903, comfortably inside the 0.95 target and the hard-tested 0.99 ceiling.
`npm test` is fully green (25/25); no `test/wav.test.mjs` threshold needed
changing — every existing margin held on its own once the musical content
moved.

This is reported as the honest result of a 5-render budget, not a converged
pass. Two things are worth saying plainly:

- **Iteration 4 → 5 likely overshot.** Iteration 4 (centroid safely mid-band,
  tilt short by 0.80) and iteration 5 (centroid over by 0.06, tilt short by
  0.46) bracket a probably-better `air` calibration somewhere between gain
  0.16-0.4 and speed 1.6-1.75 — interpolating the observed deltas linearly
  suggests a setting that lands centroid exactly on the ceiling would still
  leave tilt short by roughly 0.5, i.e. still not enough to clear both bands
  at once with this lever alone. Worth a targeted follow-up iteration with a
  fresh render budget rather than a guess spent here.
- **The deeper constraint looks structural, not a tuning miss.** Every
  available brightening lever in this pattern — sample gain, filter
  cutoff/resonance, a pitched-up layer — draws on the same small set of
  sources (TR909 `hh`/`oh` samples, a `triangle` synth), and all of them have
  their own energy concentrated in roughly 3-8 kHz rather than genuinely in
  8-16 kHz. `air` (pitching an existing sample up) was the closest tool
  available to relocate energy into the top octave without synthesizing new
  material, and it measurably improved the centroid-to-tilt exchange rate
  (~870 Hz/dB vs. ~1100-1300 Hz/dB for the round-1 levers) but a quiet layer
  covering half the track was not enough leverage over a whole-file average
  dominated by 16 bars of kick, bass and the main hats. Closing the rest of
  the gap likely needs either a genuinely bright new source (a real
  shaker/ride/cymbal sample — not attempted here: `RolandTR909` has no ride,
  and fetching an unverified sample name from the CDN bank risked a broken,
  untested render with no iterations left to debug it) or superdough's
  worklet-based `distort`/`shape` fx (also not attempted: these run through
  an `AudioWorkletNode`, an untested code path in this project's specific
  offline `OfflineAudioContext` render pipeline, and risking a full render
  iteration on unverified infrastructure with the budget this tight was not
  a good trade). Both are legitimate next steps, not ruled out — just not
  attempted with the iterations available here.
- **No metric was gamed.** Every change above is a real, audible, genre-typical
  mixing/sound-design move (hotter hats, a resonant filter on a synth stab, a
  pitched-up shaker layer, a trim pass) — nothing here is inaudible noise
  added purely to move a number.

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
