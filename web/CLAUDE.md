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
- **Generator module (`generator.py` + `acestep_client.py`, G0)** —
  ACE-Step lives behind its own router (one `include_router` line in
  `app.py`, the `render.py` precedent). `GET /api/generator/health`
  returns `{available, blocked_by_live, stats}`; "unavailable" is a
  NORMAL answer, never a 5xx — `ACESTEP_BASE_URL` unset disables the
  feature with zero HTTP, and the box is off most of the time by
  design. Env is read at CALL time (the `brief_parser` lesson below).
  `live_session_active()` is Apollo's half of the **VRAM protocol**:
  ACE-Step retains ~12.5 GB of the shared 16 GB once loaded, so
  generating during a broadcast starves the DJ's LM Studio model. It
  reads the REAL registry — `ws_manager`'s `live`-channel entries,
  written by the primary live WS handler — never log output. G1's
  generation endpoints import this helper and refuse to release tasks
  while it is true; keep one definition of "a set is on air".
- **Generation endpoints (G1)** — `POST /api/generator/tasks` is the
  ONLY GPU-touching call, so it is the only one behind the 409 VRAM
  guard (`VRAM_CONFLICT_MESSAGE`, rendered verbatim by the wizard, hence
  English like the rest of the wizard's copy); polling and the audio
  proxy stay open during a live set.
  Refusal ladder: 503 disabled/unreachable → 409 live → 422 bad
  genre/field → 429 ACE queue full → 502 ACE broke. The body is
  `extra="forbid"` (a silently ignored knob only surfaces hours later as
  an ordinary take); `experimental` is a verbatim passthrough that may
  NOT shadow server-owned fields — `audio_format: "wav"` and
  `thinking: true` are the catalog contract, not preferences.
  **`bpm` defaults to the centre of the genre window** (spec §5.5:
  pinned at release time so `metas.bpm` comes back in-window and G2
  never has to re-detect it). That table is bound to
  `agent.tools._BPM_GENRE_RANGES`, NOT to the canonical
  `main.BPM_GENRE_RANGES`: importing `main` costs ~2.6 s and ~1800
  modules (librosa/numba/moviepy) inside a request handler. Since that
  copy is knowingly partial, the window table is used ONLY for the
  default and never as the genre allow-list — a genre the table misses
  but the catalog has (`aural`, `synthware`) still generates, logs
  `no BPM window for genre`, and lets the LM pick the tempo.
- **A poll must never 5xx** — the wizard polls every 3 s, so an
  ACE-Step transport blip, a 500, a malformed batch or an id the box
  does not know yet all answer `200 {status: "pending", degraded:
  true}`; only an auth/bad-request failure (a misconfiguration retrying
  cannot fix) becomes a 502. A take's `result_parse_error` is carried
  through, never raised. Keys are always present so the poll loop never
  feature-detects.
- **`GET /api/generator/audio` is a streaming proxy, not a redirect** —
  the browser never talks to :8001 (auth + LAN isolation live here).
  `path` is the take's `file`, forwarded opaque to
  `AceStepClient.stream_audio`; a value carrying a host or naming a
  local file is a 400. `Range` is forwarded and upstream's 206 +
  range headers are mirrored, so `<audio>` seeking works as it does on
  `FileResponse` without buffering a 35 MB WAV. Auth accepts a bearer
  header OR `?token=`, the same escape hatch as `stream_track`.
- **One validator decides what "a take's audio" is** (G2b):
  `validate_ace_audio_path` — the proxy and the publisher both call it,
  so flipping the accepted location is a constant, not a refactor. Three
  shapes, deliberately unequal in trust: `/v1/audio?path=<encoded>` is an
  ACE *endpoint*, so proxying it leaves the inner path opaque (ACE's own
  validator is the authority, and Apollo only screens for hosts and
  traversal); a bare absolute path and everything **publish** resolves
  name a FILESYSTEM location and must sit under `ACESTEP_AUDIO_ROOT`
  (default `/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio`,
  comma-separated for several, read at CALL time). Confirmed with the ACE
  session 2026-08-29: the encoding is `quote(p, safe="")`, so slashes
  arrive as `%2F` and there are **no literal `/` in the query param** —
  decode once, then prefix-match. Decoding uses `unquote`, never
  `parse_qs`, which would turn a `+` in a filename into a space. A
  relative path still streams (ACE resolves it) but can never publish.
- **`POST /api/generator/publish` (G2b) runs the CLI's ingest, not a
  copy.** It downloads the take through `stream_audio` and calls
  `main.ingest_track` — the same function `python main.py --ingest`
  runs — with `main` imported **inside the handler** (~2.61 s, ~1800
  modules: unacceptable at module scope per the G1 rule, fine as a
  one-off for a rare human action, and the only way not to fork the
  catalog's id/filename conventions). Body carries the take's
  DECODED path + metas from the PAGE (`extra="forbid"`): ACE's job
  records expire but its result files never do, so the backend never
  re-queries an old task and there is no `task_id` in the contract.
  `lyrics` is TEXT (the sidecar's semantics), bridged to the ingest's
  file-taking `--lyrics` through one temp file. **Ingest refusals pass
  through as 422 with the message verbatim** — "bpm 90 is outside the
  'techno' window 120-160 BPM" is what the user has to act on, and
  paraphrasing it would fork the wording from the CLI; `main.IngestRefused`
  (a `SystemExit` subclass carrying `.message`) is what makes that
  possible without changing the CLI's behaviour. There is **no 409**:
  publishing touches the disk, not the GPU, so the VRAM protocol has
  nothing to protect here.
- **Publishing while `--build-catalog` is running is a human-scheduling
  problem, not a lock** (same class as the VRAM rule). The builder is
  serial, takes ~1.25 min/track, and writes `tracks.json` **only at the
  very end** — so a publish that lands mid-build is silently discarded
  when the builder overwrites the file. The backend deliberately does
  NOT introspect Docker to detect it: that check would be unreliable,
  untestable and one more thing to keep true. What the ingest path does
  give for free is that it re-reads `tracks.json` inside the same call
  that appends to it and backs it up first (`tracks.json.<stamp>.bak`),
  so the loser of a race loses one entry and the backup is the way back.
  Rule: don't publish while a catalog build is in flight — check with
  `docker ps | grep apollo-build` first.
- **Live WS roles**: `/live/stream` = PRIMARY (drives playback, sends
  `playback_pos` every ~250 ms and `track_ended`); `/live/viewer` =
  read-only follower (OBS). Viewers never send. A wrongly-primary OBS
  page tears the session down on disconnect (v3.6.2 fix).
- **Server-side stall watchdog** (v3.6.3, `app.py` + engine
  `check_stall`): the browser engine is ping-driven, so a frozen tab
  wedges the set; the watchdog synthesises the missing `track_ended`.
- **Endless safety top-up** (v3.9.4): `_try_endless_extend_inflight`
  runs from every `playback_pos` ping, not just past the crossfade
  point. The watchdog can only RAMP into a deck the browser already
  pre-loaded, so a track playing with `remaining_after == 0` can only
  ever be hard-cut. It self-gates (endless on + empty queue + grace
  elapsed) and a healthy agent holds `remaining >= 1`, so it engages
  only when the agent has stopped extending. Appending two tracks at
  end-of-track does NOT substitute: that gate only runs at zero, and
  the cursor advance puts the queue straight back to zero.
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

- **A `playback_pos` ping's `track_id` and `currentTime` must come from
  the same object** (v3.9.5): both are read off the active deck, never
  the id from `currentTrackIdRef` and the clock from the deck. Those
  refs flip at different moments during a crossfade, so the ping went
  out with the INCOMING track's id and the OUTGOING deck's position;
  the engine compared that near-end position against the new, shorter
  track's duration and ended it on arrival, leaving both decks audible
  (2026-08-23). The backend cannot defend against this — a
  misattributed position is indistinguishable from a real one, and
  every wall-clock heuristic breaks legitimate resumes where the deck
  is legitimately far ahead of `_track_started_mono`.
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

## Frontend generator surface (G1, `lib/generator.ts` + `components/ember/Generator*`)

- **Entry lives in the Editor's track row** — the "Generate (ACE)" tile
  sits beside "Add a track", because that row IS the wizard's
  track-selection stage; generating and picking are two ways into the
  same slot. `GenerateTrackTile` renders NOTHING while
  `/api/generator/health` is loading or `available` is false: the ACE box
  is off most of the time by design, so absent is the normal look, not an
  error state. `blocked_by_live` renders it disabled with the VRAM
  tooltip — a courtesy, since the POST's **409 is the authoritative
  guard** and its message is shown verbatim (never paraphrase a protocol
  refusal). Health is read once on mount, deliberately not polled.
- **A degraded poll is a blip, not a failure.** `applySnapshot` /
  `applyPollError` are pure folds so the transitions are testable without
  timers: a `degraded` snapshot keeps the task pending AND keeps the ETA
  it could not refresh, so the countdown ticks on through the blip. A
  thrown poll degrades too — only 401/403/404 ends the loop, otherwise a
  wrong turn spins forever. Cadence is 3 s with an immediate first poll.
- **The ETA is `(server estimate, capture time)`, not a local timer.**
  Every poll that carries `eta_seconds` restamps both, so the countdown
  resets to the server's newer number instead of drifting off a stale one.
- **Takes play through the existing `PlayerProvider`.** `Playable =
  Track & { stream_url?: string }` — catalog tracks still resolve via
  `streamUrl(id)`; a take is not a catalog entry and carries the
  `/api/generator/audio` proxy URL instead. The JWT rides the query
  string there for the same reason it does on `streamUrl`: `<audio>`
  can't set an Authorization header.
- Genres in the form come from `/api/catalog` (the same fetch
  `TrackPicker` makes) — ACE writes into a real genre folder. The BPM
  default is NOT duplicated client-side: the helper text says the server
  fills the centre of the genre's window. A third copy of
  `BPM_GENRE_RANGES` in TS is exactly the drift the root CLAUDE.md warns
  about.
- **Publish is per-take, confirmed, and one-way** (G2b). The G1
  placeholder is now a real button: `idle → confirm → publishing →
  published | failed`, all pure folds in `lib/generator.ts` so the
  machine is testable without a DOM. The confirm step exists because
  `display_name` becomes the WAV's filename and the track's name in
  every set forever — it is prefilled from the prompt
  (`suggestDisplayName`) and the genre from the form, both editable.
  A take that came back without `metas.bpm`/`keyscale` cannot publish at
  all (`canPublishTake`): the ingest refuses to guess, and guessed
  metadata is how the catalog got its poisoned BPMs. `decodedTakePath`
  is the page's half of the persistence rule — ACE's `file` is decoded
  ONCE here (with `decodeURIComponent`, never `URLSearchParams`, which
  would eat a `+` in a filename) and the decoded path is what publish
  sends. After the first take publishes, later takes in the same batch
  are offered `variant of <that name>` — the only way two takes of one
  prompt link as a single piece for the no-repeat machinery. Server
  refusals render VERBATIM, the same rule as the 409.

## Testing

- Unit: `npx vitest run` in `web/frontend` (hook tests use the
  FakeWebSocket + FakeAudioContext harness in `__tests__/live.test.ts`).
- E2E: `npx playwright test` — the transition spec stubs
  `decodeAudioData` and shims stream fetches; other specs rely on the
  404→inert contract above. `generator-wizard.spec.ts` uses the same
  `addInitScript` fetch shim to script `/api/generator/*` (including two
  degraded polls), so it passes whether or not ACE is running.
  `generator-publish.spec.ts` picks up where it stops and walks take →
  confirm → refusal → published chip → variant, capturing the POST body
  so the DECODED-path contract is asserted on the wire.

## Known issues

- 2 pre-existing eslint errors in `lib/live.ts`
  (`set-state-in-effect`, refs-during-render) — old debt, not from
  v3.9; fix in its own change, not as a drive-by.
- `tests/web/test_youtube_chat.py` fails LOCALLY only; passes in CI.
