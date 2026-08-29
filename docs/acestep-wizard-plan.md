# ACE-Step in the wizard — integration plan (G0–G4)

> Status: G0 in progress (2026-08-29). Decision (Pablo, 2026-08-29): the
> Suno-like generation UX lives INSIDE Apollo's session wizard, not in a
> separate app. API contract: `docs/ACE-STEP-API-SPEC.md` (commit c96da9e).
> Catalog contract + VRAM protocol: agreed with the ACE session, recorded in
> the root CLAUDE.md ops rules.

## Slices (daily-cycle sized)

- **G0 — client + feature flag (backend only, this iteration)**
- **G1 — the wizard "generate" step** (Suno-mode surface, polling with ETA
  from `/v1/stats`, takes with player via a backend audio proxy,
  experimental panel collapsed)
- **G2 — publisher to the catalog** (download WAV → resample 48→44.1k/16-bit
  → validations (≥120 s, genre folder exists, BPM inside the genre window) →
  `keyscale→Camelot` converter (tests against the spec's table; inverse of
  `agent/generative/scales.py`) → **ingest v2 `--ingest`** born here: a
  tracks.json append from generation metas, no madmom for bpm/key (beatgrid
  backfilled later by `--fix-incomplete`); lyrics to an optional `.lrc`
  sidecar (inert today))
- **G3 — take editing** (repaint / cover / complete on a take before
  publishing — the wizard's "modify before verifying the playlist" step)
- **G4 — the critic scores takes** against the user's prompt (existing
  critic phase, new input kind)

## G0 contract

### `web/backend/acestep_client.py`

- Async httpx client. Env: `ACESTEP_BASE_URL` (unset ⇒ the generator is
  DISABLED — every caller must treat that as a normal state, per the VRAM
  protocol "design assuming ACE-Step may be off"); `ACESTEP_API_KEY`
  optional (`Authorization: Bearer`).
- Methods: `health()`, `stats()`, `release_task(payload) -> task_id`,
  `query_result(task_ids) -> list[TakeResult]` (NOTE: the spec's `result`
  field is a JSON **string** — parse it; each entry carries `file`,
  `status`, `prompt`, `lyrics`, `metas{bpm,duration,genres,keyscale,
  timesignature}`, `seed_value`), `audio_url(path)` (absolute URL for the
  audio proxy in G1).
- Unwraps the `{data, code, error, timestamp, extra}` envelope; raises typed
  errors; `429` surfaces as a retry-with-backoff signal (queue full,
  `ACESTEP_QUEUE_MAXSIZE`), never a crash.
- Short connect timeout on `health()` (the flag must answer fast when the
  box is off).

### `GET /api/generator/health`

- `{available: bool, blocked_by_live: bool, stats: {...}|null}`.
- `available` = env set AND `/health` answers. `stats` included when up.
- `blocked_by_live` = a live session is ACTIVE — read from the backend's own
  live-session state (the real registry in the app, NOT log grepping). This
  is Apollo's side of the VRAM protocol: G1's generation endpoints will
  REFUSE to release tasks while it is true; G0 ships the guard + surfaces it.

### Tests (mandatory, mocked HTTP — never call a real ACE server)

- health: env unset → disabled; server down → unavailable; up → stats.
- Envelope unwrap + error codes (400/401/415/429/500) → typed outcomes.
- `query_result` parses the string-encoded `result`, per-take fields land.
- Live guard: fake registry active/inactive → `blocked_by_live` flips.
- The endpoint shape itself (FastAPI TestClient) incl. auth header pass-through.

## Ops notes

- Port map: ACE API :8001 (LAN) — no conflict with 4010/4020 (prod),
  4011/4021 (dev), 4031/4032 (playground).
- VRAM: 16 GB shared with LM Studio — see the root CLAUDE.md rule. The
  symptom of violation is LM Studio 400 "Failed to load model" while
  `/v1/models` still lists (listed ≠ loadable).
- First published batch: the Apollo session validates the first tracks.json
  entry before the builder makes it canon (agreed with the ACE session).
