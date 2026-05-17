# Changelog

All notable changes to ApolloAgents are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project loosely follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] — 2026-05-17

Precision beat matching, end to end. Crossfades are no longer a
time-based overlap with accidentally-aligned beats — they are
sample-accurate, downbeat-locked, and placed on musical phrase
boundaries. And, critically for v3.0, the offline render, the
terminal-live engine, and the browser-live engine all share the same
implementation, so a session sounds the same wherever it plays.

### Added (offline pipeline — PR [#51](https://github.com/pabloformoso/apollo-agents/pull/51), landed via PR [#56](https://github.com/pabloformoso/apollo-agents/pull/56))

- **Phase-locked crossfades.** The first downbeat of the incoming track
  now lands exactly on a chosen downbeat of the outgoing — the heart of
  real DJ-style beat matching. Implemented via a sample-accurate
  equal-power overlay-add (`phase_locked_crossfade_np`) that replaces
  pydub's `AudioSegment.append(crossfade=)`. A 64-sample raised-cosine
  guard masks any one-sample rounding click at the overlap edges.
- **Phrase alignment.** Transitions are placed on 16-bar phrase
  boundaries (with 8/4/1-bar fallbacks logged per transition) instead
  of arbitrary timestamps near `duration − CROSSFADE_SEC`.
- **v2 beatgrid schema.** `tracks.json` now stores a full
  `downbeats_sec` array, `beats_per_bar`, `source` (madmom | librosa),
  and `version`. The mixer reads this at mix time; no more runtime
  librosa beat detection.
- **`madmom` integration.** RNN-based downbeat tracker installed via
  the new `beatgrid` optional extra (`uv sync --extra beatgrid`).
  Falls back gracefully to a librosa-extrapolated synthetic grid when
  madmom is unavailable or returns too few downbeats.
- **`--regenerate-beatgrid` CLI flag.** Upgrades legacy v1 entries to
  v2; `--force` re-analyses everything.
- **`GridTracker`.** Single source of truth for catalog↔mix time
  mapping across transitions so cumulative time-stretches don't drift.
- **Pickup-skip heuristic.** Incoming tracks whose first bar's RMS is
  < 40 % of track-mean RMS advance their anchor to `downbeats[1]` —
  avoids crossfading into atmospheric sweeps.

### Added (live-engine parity — new in PR [#56](https://github.com/pabloformoso/apollo-agents/pull/56))

This is the v3.0 fix the user actually felt: pre-v3.0, the same
playlist on `/live` was beat-aligning differently from the YouTube
render because the three transition paths each had their own crossfade
implementation. They now share one.

- **`agent/phase_lock.py`.** New shared module owning every primitive:
  `PhaseLockPlan`, `GridState`/`GridTracker`, `find_phrase_anchor`,
  `pick_incoming_anchor`, `compute_phase_lock`,
  `phase_locked_crossfade_np`, `resolve_downbeats`,
  `build_live_transition_plan`, `is_v2_beatgrid`,
  `synthesise_downbeats_from_v1`. `main.py` re-exports them under the
  historical underscore-prefixed names so existing tests are
  unmodified.
- **`LiveEngineLocal` (terminal mode).** `_prestretch_worker` computes
  the phase-lock plan against the post-stretch incoming buffer (so
  pickup-skip runs on the same bytes the user will hear);
  `_cf_point_samples` honours `plan.outgoing_anchor_sample` over hot
  cues; the audio-callback "crossfading" branch runs equal-power
  cos/sin curves with the 64-sample edge guard, byte-for-byte
  identical to the offline path.
- **`LiveEngineBrowser` + frontend (`/live`).** The backend computes
  the plan and emits it as a `phase_lock` payload on `track_started`,
  `approaching_crossfade`, and `engine_command:crossfade`. The
  frontend (`web/frontend/lib/live.ts`) seeks the incoming
  `<audio>` element to `incoming_anchor_sec` before `play()` (skipping
  pickup bars), and replaces its linear `GainNode` ramp with
  `setValueCurveAtTime` carrying cos/sin curves from a new
  `buildEqualPowerCurve` helper.

### Fixed

- **Deadlock on `report_playback_pos`.** During Stage 3c-backend
  development, `_cf_point_seconds` re-acquired the engine's
  non-reentrant `self._lock` from inside the `with self._lock` block
  at the head of `report_playback_pos`, hanging any browser session
  that had a v2 beatgrid. Pinned with
  `TestBrowserNoDeadlockOnReportPlaybackPos`.

### Changed

- `_adjust_outgoing_tail` and `_prepare_incoming` take explicit anchor
  parameters; both slice from a downbeat so first samples line up by
  construction post-stretch.
- `analyze_tracks` reads from the catalog (v2 → v1 → runtime librosa
  fallback ladder) instead of always running librosa.
- Three `_cf_point_*` methods (offline + both live engines) all use
  the same 3-tier ladder: phase-lock plan → OUT hot cue → legacy
  `duration - crossfade - 5`.

### Backward compatibility

Entries without `beatgrid` at all fall back to runtime librosa
analysis on the offline path and to the legacy hot-cue / duration
formula on the live paths. Entries with v1 beatgrid (`first_beat_sec`
+ `bpm` only) keep working — every path synthesises downbeats from
BPM via `synthesise_downbeats_from_v1`. Run `--regenerate-beatgrid`
once to upgrade the whole catalog for maximum precision.

### Tests

- Backend pytest: +~70 cases across `test_phase_lock.py` (19 → 43),
  `test_live_engine.py` (18 → 32), `test_live_engine_browser.py`
  (16 → 29), and a new `test_phase_lock_parity.py` (6 cases pinning
  cross-path agreement: offline / local-live / browser-live MUST
  produce the same anchors for the same input).
- Frontend vitest: 122 → 132. New `setValueCurveAtTime`-vs-linear-ramp
  branch coverage, incoming-deck seek behaviour with `loadedmetadata`
  belt-and-braces, and the `buildEqualPowerCurve` cos² + sin² = 1
  invariant test.

### Deferred to v3.0.1

- Pre-flight validator/critic warning when a planned transition falls
  back to `phrase_tier == "fallback"` (UX polish — structural parity
  is already enforced by `test_phase_lock_parity.py`).
- Mic VAD (WebRTC VAD WASM) — `voice_likelihood` still `null` from
  v2.5.1.
- Visualizer effect-switching glitches ([#44](https://github.com/pabloformoso/apollo-agents/issues/44)).
- pyrubberband on the browser live path via
  `/api/live/{id}/prestretched/{track_id}`.

## [2.5.1] — 2026-05-09

Patch release fixing two bugs surfaced during real-world testing of
v2.5.0:

### Fixed

- **Live track transitions stalling at end-of-track** ([#45](https://github.com/pabloformoso/apollo-agents/pull/45)) —
  `LiveEngineBrowser` is event-sourced via `playback_pos` pings from
  the browser. When `<audio>` finishes naturally it pauses and freezes
  `currentTime`, so the watchdog's edge-detector never crossed the
  crossfade threshold and the engine never advanced. Two-pronged fix:
  (a) the frontend hook attaches `addEventListener('ended', ...)` on
  each deck and forwards `{type: track_ended}` over WS; the backend's
  new `report_track_ended` advances the cursor explicitly. (b)
  `report_playback_pos` now has an endgame safeguard that synthesizes
  the same advance when `current_time` lands within the last 2 s of
  the track without a prior crossfade — catches the case where the
  browser's `ended` event is lost.
- **AgentStream infinite render loop** ([#45](https://github.com/pabloformoso/apollo-agents/pull/45)) —
  `getSecondNow()` returned `Date.now()` directly, producing a fresh
  number on every React render. `useSyncExternalStore` interpreted that
  as continuous external mutation and re-rendered forever. Fix: cache
  the snapshot at 1-second resolution; invalidate only inside
  `subscribeSecond`'s `setInterval` callback.

### Tests

- Backend pytest: 453 → 463 (+10).
- Frontend Vitest: 89 → 94 (+5).
- Playwright E2E: 29 → 30 (+1) — new
  `e2e/live-session-transition.spec.ts` reproduces the natural-end
  scenario with a short mock track and asserts the second track's
  stream is requested.

### Known issues (deferred)

- Visualizer effect switching glitches + strobe not firing — tracked
  in issue [#44](https://github.com/pabloformoso/apollo-agents/issues/44).
  v2.5.1 does not address these; they are scheduled for a follow-up
  patch or v2.6.

## [2.5.0] — 2026-05-09

Live performance release. Pivots the v2.5 line from "Plugin
Architecture" (deferred to v2.7+) to a live-DJ flow conducted by the
agent: it perceives the environment (text description + optional mic),
plays from the browser in real time, improvises beyond the initial
playlist, and runs a beat-synced visual layer. Rolls up the v2.4
react-hooks v7 cleanup and the v2.5.{0,1,1.1,2,3} feature drops into
a single tagged release.

### Added (Live performance — primary thesis of v2.5)

- **Environment description input + planner soft bias** (#37) —
  fourth field in the genre-guard CONFIRMED block; planner uses it
  as soft signal alongside `mood`. `_apply_environment_bias` helper
  in `propose_playlist` biases by BPM-as-energy proxy.
- **Web ↔ LiveEngine bridge** (#38, follow-ups #39/#40) — refactored
  `agent/live_engine.py` to a `LiveEngineProtocol` with two impls:
  `LiveEngineLocal` (sounddevice + pyrubberband, terminal mode v1.5
  preserved) and `LiveEngineBrowser` (event-sourced, audio plays in
  browser via dual `<audio>` + `AudioContext` + `GainNode` crossfade).
  New `WS /ws/live/{id}`, `phase_live` in pipeline, `useLiveSession`
  hook, `<LiveStage>` component, `/session/[id]/live` route.
- **Go Live button** (#39 + #40) — surfaces during `phase=editing`
  as alternative to Build, with fallback at `phase=rating` and
  `phase=complete`.
- **Live DJ improvisation** (#42) — `_LIVE_DJ_SYSTEM` rewrite:
  playlist becomes guidance, not contract. Three new tools:
  `get_perception_window`, `pick_next_track` (full catalog search,
  not just queue), `emit_chat` (DJ replies to audience without
  acting). Mic perception module (`lib/mic_perception.ts`) captures
  RMS / onset / voice-likelihood client-side; backend synthesizes
  `environment_changed` events at ±6 dB deltas. Audience requests
  treated as soft signal — "accept maybe 1 in 5".
- **Beat-synced visual layer** (#41) — `<VisualLayer>` with three
  effects (particles, strobe, fractal) synced to active deck's
  `currentTime + beatgrid`. Three.js (~131 KB gzipped). Strobe
  capped at 3 Hz for epilepsy safety. New OBS-friendly route
  `/session/[id]/live/visual-only` (no chrome) prepares v2.6 broadcast
  without rework.

### Fixed (UX issues caught in real-world testing)

- **LiveStage runtime bugs** (#39) — cursor "X of N" off-by-one,
  empty `nextTrack`, static progress bar, silent autoplay block.
  Now: cursor derived from `playlist.findIndex` of current track,
  `nextTrack` derived from `playlist[idx+1]`, progress bar wired to
  `<audio>.timeupdate` (250 ms throttled, transition CSS), autoplay
  block surfaces "Click to start" overlay calling
  `audioCtx.resume() + el.play()`.

### Changed (developer ergonomics)

- **react-hooks v7 rules re-enabled** (#36) — `set-state-in-effect`
  and `refs` rules disabled in v2.2.1 are now back on. Call-sites
  refactored to canonical React 19 patterns: derived state, event-
  handler-driven setState, `useEffectEvent`, hydration via centralized
  `useAuth()` hook.

### Tests

- Backend pytest: 348 → 453 (added live-engine protocol, browser
  engine, perception buffer, environment bias, audience request
  rejection rate, `pick_next_track`, plus follow-ups for autoplay /
  cursor / nextTrack / progress fixes).
- Frontend Vitest: 33 → 89 (live hook, mic perception, beat clock,
  visualizer, react-hooks v7 compliance fixes).
- Playwright: 19 → 29 (live session, mic perception, audience
  request, visualizer, visual-only route, Go Live button placement).
- All four CI jobs (Backend Python 3.12 + 3.13, Frontend Node 20,
  E2E Playwright) green on every PR before merge.

### Out of scope (deferred)

- **Broadcast externo** (RTMP / Icecast / WebRTC / YouTube / Twitch)
  — diferido a v2.6. v2.5.3 deja la ruta `/visual-only` capturable
  por OBS para que v2.6 enchufe encoder + tokens + UI sin rework.
- **Webcam / pose detection** — descartado.
- **Custom shader editors / parameter UI** — diferido.
- **Adaptación BPM dinámica mid-track** — diferido.
- **Reorden masivo del set restante mid-sesión** — diferido.
- **Memoria per-sesión-live** en `agent/memory.json` — diferido a
  v2.6 con un memory v3 rework dedicado.
- **Plugin Architecture** (la antigua v2.5 del ROADMAP) — diferido
  a v2.7+.

### Known follow-ups

- Mic VAD (`voice_likelihood`) shipped without WebRTC VAD WASM
  integration — currently `null`. Add in v2.5.x patch if useful.
- Time-stretch (pyrubberband) intentionally not on the browser path
  for v2.5.1 — graduate to it (`/api/live/{id}/prestretched/{track_id}`)
  if audio quality demands it.

## [2.3.0] — 2026-05-06

Agent ↔ user-data integration release. The conversational agent now
reads the logged-in user's playlists and per-track ratings (delivered
in v2.2.0/v2.2.1) and uses them as soft signal during planning,
critiquing, and editing. No UX changes for the user — sessions still
flow the same; the agent is simply better informed.

### Added
- **`user_id` threaded into agent context** — `_handle_ws_message`
  injects `user_id` and `username` into `context_variables` once per
  session so every agent phase can identify the requester (#32).
- **`pipeline.load_user_context(user_id)`** — orchestrates
  `db.list_playlists_by_user` + `db.get_user_ratings`, returns
  `{playlists, ratings, favorite_ids, dislike_ids}`. Cached at 60s
  TTL keyed by `(user_id, time_bucket)` (#32).
- **Four new agent tools** in `agent/tools.py` (lazy-import
  `web.backend.db` and `pipeline` to avoid circulars):
  - `get_user_playlists(ctx)` — Markdown table of saved playlists.
  - `get_playlist_tracks(playlist_id, ctx)` — hydrated tracks of a
    given playlist with ownership check.
  - `get_user_ratings(ctx, min_rating)` — JSON map filtered by
    threshold.
  - `get_favorite_tracks(ctx, genre)` — ★4+ tracks intersected with
    the optional genre filter (#32).
- **Planner prompt block "USER PREFERENCES"** — when a user is
  authenticated, `phase_plan` injects a capped summary (10 favorites,
  5 dislikes, 5 playlists) before invoking the LLM (#32).
- **`_apply_user_rating_bias` helper** — pure function that reorders
  each BPM cluster to put favorites at the front and dislikes at the
  back, preserving harmonic adjacency among same-rated tracks. Wired
  into `propose_playlist` between Camelot sort and `_fill_duration`,
  so favorites are picked first and dislikes only land in the output
  if duration forces it (#33).
- **Editor + Critic awareness of ratings** — `_EDITOR_SYSTEM` and
  `_CRITIC_SYSTEM` prompts gain a "USER PREFERENCES SIGNAL" section.
  Critic does a deterministic post-process pass appending a
  `structured_problem` for each track in the playlist that the user
  has rated ★1 or ★2. `swap_track.prefer_favorites=True` (default)
  ranks favorite candidates first when present. New
  `_hydrate_user_context()` helper in `pipeline.py` ensures
  `phase_critique` and `phase_editor` get the same `favorite_ids`
  / `dislike_ids` keys that `phase_plan` already had (#34).

### Tests
- 24 new pytest cases for v2.3.0 (load_user_context, prompt
  formatting, tool surface, phase_plan integration).
- 16 new pytest cases for v2.3.1 (`_apply_user_rating_bias` purity,
  cluster reordering, dislike-only-when-needed semantics, mutation
  test caught the obvious swap of arg order).
- New pytest cases for v2.3.2 across critic dislike-flagging,
  editor prompt content, swap_track ranking, and phase hydration.
- Total backend pytest: 305 → 321 → 348 (across the three PRs).
- New Playwright spec for v2.3.0 (`user-context.spec.ts`); full E2E
  suite remains green at 19+ tests.
- All four CI jobs (Backend Python 3.12 + 3.13, Frontend Node 20,
  E2E Playwright) green on every PR before merge.

### Out of scope (deferred)
- "Generate from my playlist X" as direct session input — left for
  v2.4 if interesting.
- Per-user memory (`memory.json` v3 with `user_id`) — v2 stays
  intact; the agent reads SQLite at runtime and does not persist
  per-user signals to memory.
- Per-track ratings within session records (`write_session_record`
  unchanged).
- Frontend changes — none. UX is identical to v2.2.1.

### Open follow-ups
- #29 — re-enable `react-hooks/set-state-in-effect` and
  `react-hooks/refs` rules (disabled in v2.2.1's #27 cleanup batch
  to keep scope small). Dedicated React-19 ergonomics PR pending
  for v2.4.

## [2.2.1] — 2026-05-05

Patch release closing the v2.3 cleanup backlog accumulated against
v2.2.0 — six follow-up issues identified during the v2.2.0 release
review (#11, #12, #13, #16, #17, #18). No new features; no behavior
change for the user beyond perf and bug fixes.

### Fixed
- **Race condition in `add_tracks_to_playlist`** — concurrent
  `POST /api/playlists/{id}/tracks` from two clients no longer raise
  `IntegrityError` on the `(playlist_id, position)` primary key.
  `db.py` now wraps the read-modify-write in a `BEGIN IMMEDIATE`
  transaction (#16, #30).
- **Catalog hydration O(catalog) per GET** — `pipeline.load_catalog`
  now memoizes the parsed `tracks/tracks.json` keyed on
  `(mtime, size)`. New `get_track_by_id()` provides O(1) lookups for
  `/api/playlists/{id}` hydration. ~253× speedup on the smoke
  benchmark (#17, #30).
- **`npm run lint` broken on Next 16** — `next lint` was deprecated
  and removed; migrated to ESLint flat config
  (`web/frontend/eslint.config.mjs`) composing
  `eslint-config-next/core-web-vitals` + `next/typescript`. Pinned
  ESLint to v9.x for plugin compatibility (#11, #27).
- **`tsconfig.tsbuildinfo` polluting `git status`** — added
  `*.tsbuildinfo` to `.gitignore` (#12, #27).
- **Mock pipeline silence file leaking into `tracks/lofi/`** —
  `_ensure_mock_audio_file` now writes to `<root>/.tmp/` instead;
  the streaming endpoint's path-traversal guard now accepts both
  `tracks/` and `.tmp/` (#13, #27).

### Tests
- **Charmap regression** — cross-platform unit tests that simulate
  Windows cp1252 default encoding by wrapping `builtins.open`,
  exercise every agent tool that PR #22 hardened. Mutation-tested:
  reverting any of the 25 `encoding="utf-8"` additions causes the
  suite to fail with the original `0x9d` error (#22 follow-up, #26).
- **Drag-and-drop reorder coverage** — extracted `handleDragEnd`'s
  pure logic into `computeDragReorder()` and added 6 vitest cases
  covering happy path, no-op branches, and the duplicate /
  direction-sensitive corners that `arrayMove` gets wrong if you
  swap its arguments. Mutation-tested (#18, #28).
- **Concurrent append race** — `tests/web/test_playlist_race.py`
  fires 20 concurrent `httpx.AsyncClient` POSTs and asserts no 500s
  + dense 0..19 positions. Negative control: reverting the
  `BEGIN IMMEDIATE` causes 18/20 to fail with IntegrityError.
- **Catalog cache** — 7 unit tests covering memoization, mtime/size
  invalidation, deleted-file fallback, and warm-from-cold lookups.

### Chores
- Followed up the cosmetic genre-guard banner (#23) — no separate
  v2.2.1 fix; the banner was solved as part of v2.2.0's last
  hotfix.

### Open follow-ups
- #29 — re-enable `react-hooks/set-state-in-effect` and
  `react-hooks/refs` (disabled in #27 to keep scope small;
  documented as React-19 ergonomics tech debt for v2.4).

## [2.2.0] — 2026-05-04

UX & catalog workflow release. Adds in-browser audio streaming, named
playlists, per-user track ratings, and standardizes the local dev ports
to the 4000 range so they stop colliding with common Node tooling.

### Added
- **In-browser audio streaming** — `GET /api/tracks/{id}/stream?token=<jwt>`
  with Range/206 support. Persistent `<MiniPlayer>` mounted at the root
  layout, queue + next/prev, hover-visible play overlay on every catalog
  tile, prominent play button in the detail drawer (#10).
- **MP3 support end-to-end** — `--build-catalog` scans `*.wav` and `*.mp3`,
  streaming endpoint dispatches the right `Content-Type`, agent tools and
  pipeline read MP3 transparently. Output renders stay WAV (lossless rule)
  (#10).
- **Named playlists with CRUD + drag-drop reorder** — `playlists` and
  `playlist_tracks` SQLite tables, 8 REST endpoints under `/api/playlists`,
  `/playlists` list + detail pages (dnd-kit reorder, missing-track stubs),
  `+` button on every catalog tile and `+ PLAYLIST` in the detail drawer,
  "Play all" reuses the v2.2.0 player (#15).
- **Per-user track ratings (1–5★) + Favorites filter** — `track_ratings`
  table, `PUT/DELETE /api/tracks/{id}/rating`, `/api/catalog` enriched
  with `user_rating`, reusable `<StarRating>` widget on `TrackCard` and
  `TrackDetail`, `★ Favoritos` filter chip in the toolbar (#14).

### Changed
- **Default dev ports** — frontend 3000 → **4010**, backend 8000 →
  **4020**. E2E test ports unchanged (3001/8801) — intentionally distinct
  from dev defaults (#21).

### Fixed
- **Playwright config double-unlink on Windows** — sentinel env-var
  (`APOLLO_E2E_DB_PURGED`) prevents worker-subprocess re-import from
  purging the SQLite db while uvicorn holds it open (#19, #20).
- **UTF-8 reads in agent tools** — `agent/tools.py`, `agent/run.py`,
  `agent/live_engine.py`, `main.py` now open JSON with
  `encoding="utf-8"`. On Windows, default cp1252 was choking on UTF-8
  byte sequences (`0x9d` at position 259716 of `tracks.json`) (#22).
- **Genre Guard banner UX** — no longer emits "Could not confirm genre"
  on every in-progress confirmation turn. Distinguishes "still asking"
  (non-empty agent response, under 8 turns) from "gave up" (empty
  response or turn cap) (#23, #24).

### Tests
- 258 pytest passing (was 213 in v2.1.0): added 9 stream + 4 catalog-mp3
  + 13 playlists + 11 ratings + 8 genre-guard regressions.
- 27 Vitest passing (was 8): added 7 player + 5 playlists + 7 star-rating.
- 16 Playwright passing (was 11): added 2 player + 3 playlists + 2
  ratings, all reproducible on Windows after #20.

### Out of scope (deferred to v2.3+)
- Agent integration with playlists/ratings (the agent currently does not
  read user ratings or named playlists when planning — that's the v2.3
  thesis).
- Pre-existing follow-ups in issues #11 (`npm run lint` broken on Next
  16), #12 (`tsbuildinfo` not gitignored), #13 (mock pipeline leaks
  `mock-silence.wav`), #16 (race in `add_tracks_to_playlist`), #17
  (catalog cache for hydration O(N) per GET), #18 (`handleDragEnd` has
  no direct test coverage).

## [2.1.0] — 2026-05-04

First minor release after the v2.0 Web UI launch. Focus: cleaner audio mixes
and a browseable catalog UI, plus a long tail of web/render/test fixes.

### Added
- **Catalog UI** — `/catalog` page in the web frontend lists every track in
  `tracks.json` with genre, BPM, and Camelot key (`9e8a2e5`).
- **Suno-aware track names** — catalog builder strips Suno's UUID suffixes and
  surfaces clean display names (`9e8a2e5`).
- **Per-genre crispness override** — `RUBBERBAND_CRISPNESS_BY_GENRE` lets
  transient-heavy genres (techno, cyberpunk) keep crispness 5 while pads and
  ambient genres use the smoother default of 4 (`81d0ec7`).
- **`tests/test_bpm.py` + `tests/test_mix.py`** — 24 new unit tests covering
  the BPM octave ladder, soft-fade branching, and crispness propagation
  (`81d0ec7`).
- **`CHANGELOG.md`** — this file.

### Changed
- **Per-track LUFS normalization + bus brick-wall limiter** — replaces the
  static -3 dB attenuation with ITU-R BS.1770 loudness normalization to
  -16 LUFS per track, and a Pedalboard-Compressor brick-wall at -0.5 dBFS
  on the final bus. Eliminates audible clipping at crossfades between
  loud Suno masters and quieter ambient pieces (`aa7358b`).
- **Soft-fade for big BPM jumps** — when the stretch ratio exceeds 1.4×
  (where Rubber Band quality degrades sharply), `build_mix` now skips
  time-stretching entirely and overlaps both tracks at native BPM with a
  24 s crossfade. Falls back gracefully to meet-in-middle when the
  incoming track is shorter than the soft-fade window (`30c596c`,
  `81d0ec7`).
- **BPM detection: octave ladder** — `detect_bpm` evaluates ¼/½/1/2/4×
  candidates and picks the one closest to the genre midpoint that fits the
  range. Outliers surface their real BPM rather than being silently clamped,
  and unknown genres pass through `raw_bpm` (`30c596c`, `81d0ec7`).
- **Rubber Band crispness 4 by default** — smoother phase coherence for
  pad-heavy genres (`30c596c`).
- **Frontend deps** — Next 16 + React 19, dropping all known CVEs
  (`4c8087e`).
- **`pyproject.toml` version** bumped from `0.1.0` (untouched since
  scaffolding) to `2.1.0`, in line with the existing tags.

### Fixed
- **Render pipeline UTF-8** — force UTF-8 on stdout, stderr, and text-mode
  file writes so non-ASCII track names don't crash on Windows
  (`75faa40`).
- **Render audio path** — bypass moviepy's audio path with a direct ffmpeg
  mux to avoid a moviepy 2.x regression (`c338f44`).
- **Web — sessions persisted to SQLite** with live build progress and
  WebSocket hardening (`1727edf`).
- **Web — pre-flight catalog checks per phase** with actionable error
  messages instead of silent failures (`7049de3`).
- **Web — dev API/WS port aligned to 8000** in proxy and fallback
  (`55245b0`).
- **Web — frontend pointing at backend port 8800** (`9e8e44c`).
- **Web — dashboard hydration mismatch** on initial user load
  (`67cba89`).
- **Web — infinite `/api/sessions` polling + WS thrash** stopped
  (`6ec6e11`).
- **Web — UI no longer blocks after the Critique phase** (`fd69eb1`).
- **Web — unique playlist keys + favicon** (`133dfb8`).

### Tests
- **Playwright E2E suite + mock pipeline + `phase_complete` fix**
  (`19a347b`).
- **v2.0 backend + frontend tests, fix 500 on register** (`995b0cf`).
- **`check_catalog` stub in mock pipeline** (`92e8b3d`).

### Chores
- **Ignore Suno `.wav.txt` sidecars** under `tracks/` (`a127693`).

## [2.0.0] — 2026-04-18

- v2.0 Web UI launch — FastAPI backend + Next.js frontend.

(Earlier versions tagged in git: `v1.5.1`, `v1.3`, `v1.2`, `v1.1.2`,
`v1.1.1`, `v1.1`. No release notes were captured at the time.)
