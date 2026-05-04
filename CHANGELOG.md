# Changelog

All notable changes to ApolloAgents are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project loosely follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
