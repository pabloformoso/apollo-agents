# scripts/ — spikes, benches, and smoke gates

- `spike_generative.py` — generative MIDI spike (`uv sync --group synth`,
  loopMIDI + a listening synth; see docs/reasoned-generative-engine.md).
- `render_generative.py` / `render_surge_live.py` — offline renders of
  the generative engine.
- `quality_bench.py` + `extract_quality_references.py` — the
  bench-vs-own-catalog gate: the generative engine's autonomous
  definition-of-done is scoring against curated catalog references.
  Two modes, mutually exclusive: the render mode (`--phrases/--seed/
  --llm/--intent`) synthesizes what it scores, and `--wav PATH` scores
  a render it did NOT make (the algorave/Strudel lane, `--genre` then
  says which bands to use). `--wav` prints and only writes with `-o`;
  it has no symbolic tier — novelty and note density need specs, and
  an external WAV arrives without them. Bands come from
  `--references` (default: the committed
  `agent/generative/quality_references.json`), and the same generous
  margins apply to both modes, so the gate still catches gross
  wrongness rather than taste.
- `smoke_local_llm.py` — **model-fitness gate for the live DJ's local
  LLM** (LM Studio, gemma). Run it before pointing a live session at a
  new/changed local model; a model that fails the smoke is not fit to
  drive a stream. Gotchas:
  - Since 2026-08-12 LM Studio is not on the LAN any more: it runs on
    the Tailscale node `tunel` at `100.68.5.104:1234` (was the LAN host
    `192.168.1.72`). Address it **by IP** — MagicDNS is disabled
    tailnet-wide, so `tunel` resolves neither on the host nor in the
    container. Tailscale must be logged in on the machine running the
    smoke, or every workload errors out on connect.
  - The env var is `OLLAMA_BASE_URL` (the `ollama` provider is really
    the generic OpenAI-compatible path), and containers need
    **recreating** — `docker compose up -d backend` — to pick up a
    change; a `restart` keeps the old env.
  - **Run each model twice.** The first call to an unloaded model pays
    LM Studio's JIT load and can report a false FAIL: bonsai-27b
    measured 27.8s cold vs 5.7s warm on the same tool call.
  - Latency is the live constraint, not raw capability. Measured warm
    over the tunnel (2026-08-12) — greeting / tool call:
    `gemma-4-e4b` 4.4s / 3.6s, `gemma-4-12b-qat` 6.8s / 8.1s,
    `bonsai-27b` 18.8s / 5.7s, `muse-glimmer` ~95s and unusable (LM
    Studio cannot parse its chat template, so control tokens leak into
    the text). e4b stays the default.
- `bench_extend_set.py` — **the gate that actually predicts live
  behaviour.** The smoke above is necessary but NOT sufficient: it asks
  a toy question (one tool, three short ids on a plate) that every
  model passes, including gemma-4-e4b, which contributed zero
  `extend_set` calls across 17 real `playlist_running_low` pokes. This
  bench replays the real turn instead — the full `_LIVE_DJ_SYSTEM`, all
  ten `_LIVE_TOOLS`, the real `_format_turn` text, and the REAL
  `pick_next_track` / `extend_set` against `tracks.json` (so the
  eligibility screen, the genre fence and the coaching error strings
  are all live). Only the audio engine is faked. Gotchas:
  - Needs `tracks/tracks.json` → run from the main checkout, or copy
    the catalog in (it is gitignored, so it won't dirty a worktree).
  - The symptom is a RATE, not an event: run ≥10 trials per model, and
    read the breakdown (`silent` vs `rejected` vs `picked_only`), not
    just the pass line. Those three are different bugs.
  - `appended` is ground truth from the fake engine's recorder, never
    from the model's prose — a model claiming it appended is the live
    failure mode itself.
  - It preflights the endpoint (reachable + models actually served) and
    refuses to run otherwise. Do not remove that check: importing
    `agent.run` fires `load_dotenv()`, so a stale worktree `.env` can
    silently override `--base-url`'s default — on 2026-08-14 it pointed
    at the pre-tunnel LAN host and 20 trials of timeouts were reported
    as a clean "0% append rate, silent=10". A dead endpoint and a mute
    model land in the SAME bucket. Pass `--base-url` explicitly.
- `bench_strudel_mind.py` — **the same gate for the algorave lane**
  (docs/algorave-livecoding-plan.md §8.3): can a model write valid
  Strudel, and how fast? It drives the real `agent/generative/
  strudel_mind.py`, so the system prompt, the `node validate.mjs`
  verdict and the one-retry reject-and-hold are measured as they will
  run live. Trials alternate generate-from-empty / mutate-the-committed
  -pattern over a fixed intent rotation. Gotchas:
  - **Two** preflights, both refusing rather than reporting: the Node
    validator (`npm install` in `scripts/algorave-spike`) and the
    endpoint (reachable + models actually served). With no validator
    every trial buckets identically, which reads like a model verdict
    and is not one.
  - Warm-up call per model, excluded from the stats (LM Studio JIT).
  - The finding is the breakdown, not the pass line: `invalid_js`,
    `no_events`, `palette` and `token_screen` are four different bugs
    (dialect, structure, prompt palette, prompt hygiene). Latency is
    reported over all attempts AND over valid ones only — a model that
    is fast only when it fails is not fast.
  - The number to beat is the JSON mind's: ~50% invalid, warm 8.6 s
    (gemma-4-e4b) / 12.5 s (qwen3.5-9b), measured 2026-08-28.
- `algorave-spike/palette.json` — the lane's ONE sound registry (plan
  §10): sample `sources`, drum/synth vocabularies, the bank→sounds
  matrix, per-genre entries. `validate.mjs` gates against it (`--genre`
  narrows; a (sound, bank) pair its matrix lacks = silence live =
  rejected), `strudel_mind.py` prompts from it, both spike pages fetch
  it at boot (`serve.mjs` serves it at `/palette.json`; b-cdn fallback).
  Add sounds/banks by editing it — self-hosting samples later is
  editing `sources`. Consistency is CI-tested from pytest
  (`test_registry_is_self_consistent`) because the spike's vitest does
  not run in CI.
- `algorave_playground.py` — the playground's mind button
  (docs/algorave-livecoding-plan.md §9 stage 1): a stdlib HTTP server on
  **4032** whose one endpoint, `POST /mind`, hands the editor's code +
  an intent to `StrudelMind` and returns the validated mutation. Pairs
  with `scripts/algorave-spike/patterns/playground.html` served by
  `serve.mjs` on 4031 (that page lives under `patterns/` because
  serve.mjs mounts nothing else). Gotchas:
  - **`--mock` builds no LLM client** — a canned deterministic mutation
    through the REAL validator, so the whole path is demoable with no
    tunnel. Use it before blaming the model for a page bug.
  - The four failure codes are deliberately distinct: 400 malformed,
    502 the mind failed twice (detail carries BOTH validator errors,
    caller holds), 503 the validator is missing (`npm install`), 500
    anything else. All of them carry CORS headers — a 502 the browser
    will not let the page read is a swallowed error.
  - `validate.mjs`'s token screen covers **comments**, so a comment
    saying "cannot import Python" rejects the whole buffer. Cost a 502
    on the seed file's own header, 2026-08-29.
  - **The pen** (§9.1, iteration 2) lives entirely in the page — no
    server change. `pen ∈ {mind, human}`, starts human; while the mind
    holds it a phrase scheduler POSTs every N bars (default 8) and
    **auto-applies** the mutation, one request in flight, a boundary
    reached mid-request skipped rather than queued. The decisions are a
    pure module, `scripts/algorave-spike/patterns/pen.js`, unit-tested
    in `test/pen.test.mjs`; only the wiring is browser-verified. To
    demo or debug it against `--mock` while a real-model instance is
    already on 4032, start a second server on another port and point
    `MIND_URL` at it — then put it back, the page must ship pointing at
    4032.
  - **B2B** (§9.2, iteration 3) is the pen on a timer: `mode ∈ {free,
    b2b}` (starts free, **never persisted**, unlike the `b2bBars` turn
    length, default 16 / floor 4, which is persisted like `phrase`),
    and `b2bDecide()` in the same `pen.js`, tested in `test/b2b.test.mjs`.
    Two things carry the whole contract: flips call the page's ONE
    `handOverThePen()` rather than duplicating it, and the tick runs the
    flip decision BEFORE the phrase decision — together with §9.1's
    "a handoff consumes the current bar" that is what stops a flip and a
    phrase boundary landing on the same bar from double-acting (the flip
    wins; the mind fires at its next boundary). The only server change
    in the whole iteration is one optional boolean: `b2b` in the POST
    (non-bool → 400), forwarded as `state["b2b"]` **only when true**, on
    which `strudel_mind` appends ONE line to the USER message. The
    system prompt is deliberately untouched, so a B2B session stays
    comparable to `bench_strudel_mind.py`.
- `smoke_azure.py` — same idea for the Azure OpenAI path.

Convention: scripts are operator-facing and safe to run against the
main checkout; none of them mutate `tracks/` or `output/` without
saying so in their `--help`.
