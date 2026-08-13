# scripts/ — spikes, benches, and smoke gates

- `spike_generative.py` — generative MIDI spike (`uv sync --group synth`,
  loopMIDI + a listening synth; see docs/reasoned-generative-engine.md).
- `render_generative.py` / `render_surge_live.py` — offline renders of
  the generative engine.
- `quality_bench.py` + `extract_quality_references.py` — the
  bench-vs-own-catalog gate: the generative engine's autonomous
  definition-of-done is scoring against curated catalog references.
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
- `smoke_azure.py` — same idea for the Azure OpenAI path.

Convention: scripts are operator-facing and safe to run against the
main checkout; none of them mutate `tracks/` or `output/` without
saying so in their `--help`.
