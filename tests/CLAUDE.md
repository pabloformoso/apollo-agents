# tests/ — backend pytest suite

Run: `uv run pytest tests/ -q` (frontend tests live in
`web/frontend/__tests__`, run with vitest — see `web/CLAUDE.md`).

## Rules

- **Unit tests are mandatory for every new function and endpoint**
  (happy path + auth + validation + edge cases). Never report a change
  "done" without them.
- **Read the FULL failure list** before concluding anything:
  `tests/web/test_youtube_chat.py` (13 tests) fails locally and passes
  in CI — a run with only those failures is effectively green.

## Conventions & gotchas

- Track factories (`_track(...)`) must default `duration_sec` ≥ 120 —
  anything fed to a SELECTION path (`_autoplay_pick`, mocked
  `_load_catalog`, `pick_next_track`) passes through the
  session-eligibility screen (v3.9.1, `agent/eligibility.py`).
  Playlist tracks handed straight to `engine.play()` are NOT screened,
  so tests that poke positions near a 60 s end keep explicit
  `duration_sec=60`.
- Catalog mocking patterns (pick one, they're all in use):
  - `monkeypatch.setattr(tools, "_CATALOG_PATH", tmp_json)` — tools
    that read tracks.json directly (`propose_playlist`, `swap_track`).
  - `patch.object(web.backend.pipeline, "load_catalog", ...)` — tools
    with the lazy pipeline import (`pick_next_track`, `extend_set`).
  - `monkeypatch.setattr("agent.live_engine._load_catalog", ...)` —
    endless fallback paths.
- `LiveEngineBrowser` is the integration surface for engine tests (no
  audio device); drive it with `report_playback_pos` /
  `report_track_ended` pokes.
