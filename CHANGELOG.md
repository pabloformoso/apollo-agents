# Changelog

All notable changes to ApolloAgents are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project loosely follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v2.5.3 — Visual layer beat-sync

Beat-synced visual layer for the live performance flow. The visual slot
left as a placeholder by v2.5.1 in `<LiveStage>` is now a fully
functional canvas with three switchable effects, all driven by the
active deck's `currentTime` plus the catalog's `beatgrid` metadata.

### Added
- **`web/frontend/lib/visualizer/beat_clock.ts`** — pure function
  turning `(bpm, first_beat_sec, current_time_sec)` into
  `{beat_index, phase_in_beat, is_downbeat}`. Edge-case-safe (bpm=0,
  pre-first-beat, NaN inputs all return zeros).
- **`web/frontend/lib/visualizer/effects/{particles,strobe,fractal}.ts`**:
  - `particles` — Three.js `Points` field (~1500 particles), beat-pulse
    on size + opacity, hue rotation every 16 beats keyed to the
    Camelot-key palette.
  - `strobe` — DOM overlay div, exponential-out flash on every Nth
    downbeat. Default safety cap at 3 Hz to mitigate
    photosensitive-epilepsy risk.
  - `fractal` — Julia-set fragment shader (~30 lines GLSL) on a
    fullscreen quad; zoom breathes per-beat, twist drifts, color
    pulled from the Camelot palette.
- **`web/frontend/components/VisualLayer.tsx`** — owns the canvas
  + effect selector + fullscreen toggle, drives a `requestAnimationFrame`
  loop wrapped in `useEffectEvent` (v7 react-hooks compliant). Tracks
  without `beatgrid` show a degraded-sync banner.
- **`/session/{id}/live/visual-only`** — OBS-friendly fullscreen route.
  Reuses `useLiveSession` over the existing `/ws/live/{id}` so an OBS
  browser source can capture it without any chrome. Lays the groundwork
  for v2.6 broadcast without rework.
- **`<VisualLayer>` mounted into `<LiveStage>`** — replaces the
  v2.5.1 visual-slot placeholder div.

### Tests
- 13 new vitest cases covering `beat_clock` math + edge cases.
- 11 new vitest cases covering particles / strobe / fractal lifecycle
  and the strobe rate-cap.
- 4 new Playwright E2E cases (3 effect toggles + fullscreen button +
  OBS visual-only route + auth gate).

### Notes
- Three.js was chosen over vanilla WebGL: bundle size impact ~131 KB
  gzipped (well under any "unacceptable" threshold), and the
  Scene/Camera/Material API saved meaningful boilerplate over raw
  WebGL for the particle field.
- No backend changes were necessary — `track_started` events already
  forward the full track dict including `beatgrid`.

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
