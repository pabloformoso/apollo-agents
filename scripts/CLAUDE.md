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
  drive a stream. Gotchas: LM Studio listens on the LAN IP (not
  localhost from inside Docker) and containers need recreating (not
  just restarting) to pick up a changed `OPENAI_BASE_URL`.
- `smoke_azure.py` — same idea for the Azure OpenAI path.

Convention: scripts are operator-facing and safe to run against the
main checkout; none of them mutate `tracks/` or `output/` without
saying so in their `--help`.
