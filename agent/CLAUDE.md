# agent/ — orchestrator, live engines, and LLM tools

## What lives here

- `run.py` — Apollo orchestrator + agent loops (planner → critic → editor).
- `live_dj.py` — LiveDJ loop that narrates and steers a live session.
- `live_engine.py` — TWO engines behind one protocol: `LiveEngineLocal`
  (PortAudio, has its own clock) and `LiveEngineBrowser` (ping-driven —
  **no clock of its own**; every advance is driven by `playback_pos`
  pings or `track_ended` from the browser). The v3.6.3 stall watchdog
  exists because a wedged browser stops pinging and the set dies.
- `tools.py` — all LLM-callable tools.
- `eligibility.py` — session-eligibility rules (v3.9.1): tracks under
  `MIN_TRACK_DURATION_SEC` (120 s, env `APOLLO_MIN_TRACK_DURATION_SEC`)
  are never SELECTED into a session.
- `phase_lock.py` / `transition_styles.py` — beatmatch planning shared
  by offline render and both live engines.

## Decisions (do not re-litigate without a reason)

- **Tool signature convention**: `def tool(params..., context_variables: dict) -> str`.
  `context_variables` is injected by the orchestrator, never by the LLM.
  List parameters travel as JSON strings (schema-builder limitation).
- **Eligibility screens at SELECTION time, not catalog time.** Short
  tracks stay in `tracks.json` (stream-by-id, ratings, artwork must
  still resolve). Screening lives in: `propose_playlist`,
  `pick_next_track`, `extend_set`, `swap_track`, `_autoplay_pick`, and
  `main.load_catalog`. Manual swaps in the web UI are a deliberate
  human override and are NOT screened.
- **The confirmed ctx genre beats the LLM's tool argument**
  (`propose_playlist`, PR #91) — small local models pass their prior
  ("lofi - ambient") instead of the confirmed genre.
- **Tool error strings coach the model**: on a bad id / ineligible
  track, tell the LLM exactly which tool to re-run (`pick_next_track`)
  — never a bare "not found".

## Known issues / gotchas

- Local LLM (gemma via LM Studio) **hallucinates track ids** shaped
  like real ones but with non-hex UUID chars — `extend_set` rejects
  them; the `[llm-shim]` recovers textual tool calls.
- **Pending**: dedupe in extend/append (same track appended twice in a
  row → self-crossfade, seen 2026-08-01 'Golden Groove'×2).
- **Pending**: stall-watchdog alarm — after N consecutive forced
  advances it should stop/alert instead of silently burning the
  catalog (2026-08-01: 21 tracks announced but never played).
- Poisoned BPMs in catalog: a handful of lofi@150 and synthware
  176–212 entries act as genre-drift bridges.
