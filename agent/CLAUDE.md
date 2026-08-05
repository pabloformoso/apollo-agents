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
- **Live picks are genre-fenced (v3.9.2)**: `pick_next_track` /
  `extend_set` only surface/accept the session's ctx genre. One
  out-of-genre pick flips the endless engine's genre permanently (it
  inherits genre from the current track — aural→synthware 2026-07-28,
  aural→lofi 2026-08-04). The `include_other_genres` /
  `allow_other_genre` escape hatch is reserved for EXPLICIT audience
  requests; never loosen the default.
- **Appends are dedupe-guarded (v3.9.2)**: `append_track` (both
  engines) rejects an id that is currently playing or queued ahead,
  and the endless pickers hard-exclude the upcoming queue in every
  tier (`_autoplay_pick(never_ids=...)`). Played tracks stay
  appendable — recycling is what keeps a 24/7 set alive.
- **Tool error strings coach the model**: on a bad id / ineligible
  track, tell the LLM exactly which tool to re-run (`pick_next_track`)
  — never a bare "not found".

## Known issues / gotchas

- Local LLM (gemma via LM Studio) **hallucinates track ids** shaped
  like real ones but with non-hex UUID chars — `extend_set` rejects
  them; the `[llm-shim]` recovers textual tool calls.
- **Pending**: stall-watchdog alarm — after N consecutive forced
  advances it should stop/alert instead of silently burning the
  catalog (2026-08-01: 21 tracks announced but never played).
- **Pending**: take-aware no-repeat — the anti-repeat window works on
  ids, but Suno takes ('x' / 'x bis' / 'x-v2', `variant_of`) are the
  same piece under several ids, so the audience can hear a "repeat"
  within minutes (2026-08-04). Needs a variant_of/display_name-aware
  window.
- Poisoned BPMs in catalog: a handful of lofi@150 and synthware
  176–212 entries act as genre-drift bridges.
