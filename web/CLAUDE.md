# web/ — FastAPI backend (:4020) + Next.js frontend (:4010)

Run both from the **main checkout** (worktrees lack tracks/.env/venv).
Ports 4010/4020 are the live prod stack — dev servers go on 4011/4021.

## Architecture decisions

- **Catalog loaders here must NOT filter session eligibility.**
  `pipeline.load_catalog` feeds stream-by-id, ratings and the library
  UI — a short track must still resolve. The eligibility screen lives
  in the SELECTION paths (`agent/eligibility.py` consumers).
- **`brief_parser` follows `AGENT_PROVIDER`, never a hardcoded
  vendor** (v3.11). It called Anthropic unconditionally, so on this
  box — no `ANTHROPIC_API_KEY` since the move to local LM Studio —
  every free-text brief silently parsed to all-null and the planner
  fell back to the conversational genre-guard. Detection is read at
  CALL time (not import) so a late-loaded `.env` still works, and
  `AGENT_PROVIDER=mock` short-circuits before any network. The local /
  Azure path asks for a JSON object rather than a forced tool call:
  small models are markedly better at emitting JSON than at
  function-calling, and `_normalize` treats the payload as untrusted
  either way.
- **Live WS roles**: `/live/stream` = PRIMARY (drives playback, sends
  `playback_pos` every ~250 ms and `track_ended`); `/live/viewer` =
  read-only follower (OBS). Viewers never send. A wrongly-primary OBS
  page tears the session down on disconnect (v3.6.2 fix).
- **Server-side stall watchdog** (v3.6.3, `app.py` + engine
  `check_stall`): the browser engine is ping-driven, so a frozen tab
  wedges the set; the watchdog synthesises the missing `track_ended`.
- **`[engine track_ended]` diagnostic** (v3.9.3): every `track_ended`
  logs the reported position vs `duration_sec` plus a `src=` label
  (`client` = browser message, `endgame` = last-2-s safeguard, `stall`
  = watchdog). A `src=client` line marked `PREMATURE` is the signature
  of a skip-on-load-failure. Before this the WS handler logged nothing,
  so a browser-side skip and a track finishing were identical in the
  backend log; don't reach for `[beatmatch]` or `[live_dj]` timestamps
  to reconstruct on-air time — the first is emitted at plan time (late
  whenever the endless queue is dry) and the second is gated by LLM
  latency, so both drift by a minute or more.

## Frontend playback substrate (v3.4+, `lib/audio_buffer_decks.ts` + `lib/live.ts`)

- AudioBufferSourceNode decks, PCM decoded via `BufferCache`.
- **The cache is a working set, not an archive** (v3.9): after every
  successful schedule it is pruned to {current, preloaded-next}.
  Never remove the prune — an endless session that keeps every
  decoded track OOMs the renderer (~50–100 MB/track; the 2026-08-01
  30 h collapse).
- **Load-failure taxonomy** (v3.9): fetch-stage failures leave the
  deck INERT (the E2E suite drives the UI against 404ing mock streams
  and depends on that); decode failures/timeouts send a synthetic
  `track_ended` (skip), capped at 3 consecutive, streak reset on a
  healthy schedule. `BufferCache.load` races a 20 s deadline.

## Testing

- Unit: `npx vitest run` in `web/frontend` (hook tests use the
  FakeWebSocket + FakeAudioContext harness in `__tests__/live.test.ts`).
- E2E: `npx playwright test` — the transition spec stubs
  `decodeAudioData` and shims stream fetches; other specs rely on the
  404→inert contract above.

## Known issues

- 2 pre-existing eslint errors in `lib/live.ts`
  (`set-state-in-effect`, refs-during-render) — old debt, not from
  v3.9; fix in its own change, not as a drive-by.
- `tests/web/test_youtube_chat.py` fails LOCALLY only; passes in CI.
