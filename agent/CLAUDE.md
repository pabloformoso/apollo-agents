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
- `generative/strudel_mind.py` — the algorave lane's slow plane (S2,
  docs/algorave-livecoding-plan.md §8.2): state + intent → **validated
  Strudel code**, the sibling of `generative/mind.py` with the private
  JSON spec swapped for the language LLMs already speak. Same
  reject-and-hold contract (one retry carrying the error, then
  `StrudelMindError` and the caller holds), three differences worth
  knowing: validation is a `node scripts/algorave-spike/validate.mjs`
  subprocess (JS can only be judged by evaluating it), so a missing
  node/`node_modules` is diagnosed by `require_validator()` with the
  `npm install` fix in the message instead of a traceback; a non-empty
  `state["current_code"]` turns the call into a MUTATION of that code
  (in an algorave the code on screen is the performance); and the model
  is `GENERATIVE_MODEL` > `AGENT_MODEL` > provider default, so the lane
  can run on a different model from the live DJ (#123 precedent).
  The sound vocabulary — drum roles, synth voices, sampled instruments
  (bankless: `piano`), each bank's
  actual sound set, and the melodic role table (voice + register per
  role, rendered by `roles_block()`; prompt-side only, the validator
  cannot attribute events to roles) — comes from
  `scripts/algorave-spike/palette.json`
  (ONE registry, plan §10; also read by `validate.mjs` and the spike
  pages). Add sounds/banks/roles THERE, never in this module: it loads the
  registry at import and fails LOUD on a missing/corrupt file, and
  `next_code` passes `--genre` so the validator enforces the same
  per-genre fence the prompt teaches (a (sound, bank) pair the matrix
  lacks plays silence live — the failure the pairing gate exists for).
  Benched by `scripts/bench_strudel_mind.py` before it goes anywhere
  near a stream.

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
- **No-repeat is take-aware (v3.10, `agent/track_identity.py`)**: a
  "piece" can live under several ids (Suno takes: `variant_of`/-vN
  ids, hand-saved 'x bis' files). Exclusion, the append guard, the
  planner, and the pick_next_track table all key on PIECE identity
  (structural key + genre-scoped normalized-name key). Same-stem ids
  with different UUID tails are separate GENERATIONS (distinct music,
  e.g. quiet_pages×13) and are deliberately NOT collapsed. Known
  limitation: bare '-2' collision renames only link when display
  names align.
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
- Poisoned BPMs in catalog: a handful of lofi@150 and synthware
  176–212 entries act as genre-drift bridges.
