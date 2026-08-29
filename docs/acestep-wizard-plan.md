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

## G1 contract (2026-08-29) — the wizard "generate" step

### Backend (`web/backend/generator.py` grows three endpoints, all authed)

- **`POST /api/generator/tasks`** — body (Suno-mode surface):
  `{prompt, lyrics?, audio_duration (120–600, default 180), vocal_language?
  ("en"), genre_folder (must exist — drives the bpm default), bpm?,
  key_scale?, batch_size? (1–8, default 2), experimental?: {inference_steps,
  seed, time_signature, ...passthrough}}`.
  Server fills: `audio_format: "wav"`, `thinking: true`, and — when `bpm`
  is absent — the CENTER of the genre's `BPM_GENRE_RANGES` window (the
  spec's §5.5 advice, enforced server-side so metas come back in-window).
  Refusals: generator disabled → **503**; `live_session_active()` → **409**
  with a message naming the VRAM protocol (THE G0 guard doing its job);
  bad genre / out-of-range fields → 422. Success → `{task_id,
  queue_position, eta_seconds}` (eta = stats `avg_job_seconds` ×
  (queue_position + running), null when stats are unavailable).
- **`GET /api/generator/tasks/{task_id}`** — maps `query_result` status
  0/1/2 → `{status: "pending"|"done"|"failed", takes: [{index, file,
  prompt, lyrics, metas{bpm,duration,genres,keyscale,timesignature},
  seed_value}], eta_seconds}`. Poll-friendly: transport errors to ACE
  surface as `{status: "pending", degraded: true}` (a poll must survive a
  blip), and `result_parse_error` on a take is carried through, not fatal.
  Polling/audio are allowed during a live session — only task RELEASE
  touches the GPU.
- **`GET /api/generator/audio?path=...`** — streaming proxy of ACE's
  `/v1/audio` (the browser never talks to :8001 directly; auth + LAN
  isolation live here). Superseded 2026-08-29 (proxy-root-check fix):
  the path is forwarded UNREWRITTEN but not unexamined — an absolute
  decoded path (bare or inside the `/v1/audio?path=` shape) must sit
  under `ACESTEP_AUDIO_ROOT` on every route, same rule as publish;
  schemes/hosts/drives/traversal are 400; relative still streams (ACE
  resolves it against a root only ACE knows).

### Frontend (the wizard)

- Entry: a **"Generar (ACE)"** affordance in the wizard's track-selection
  stage, feature-flagged by `/api/generator/health`: hidden when
  `available` is false; visible-but-disabled with a "protocolo VRAM:
  directo en el aire" tooltip when `blocked_by_live`.
- Form = the Suno surface (§3.1 of the API spec): prompt, lyrics textarea
  (placeholder hinting `[Verse]`/`[Chorus]`, empty = instrumental),
  duration (120–300, default 180), language, genre (existing genres only —
  drives the bpm default shown as helper text), takes (batch_size, default
  2), and a **collapsed "Experimental"** panel (inference_steps, seed,
  key_scale, time_signature). Submit → task card.
- Task card: queue position + **ETA countdown** (from `eta_seconds`,
  refreshed each poll), poll every 3 s (house fetch conventions), then the
  takes: audio `<audio>` players via the backend proxy + metadata chips
  (bpm · key · duration · seed). Errors human-readable; a 409 renders the
  VRAM message verbatim. **No publish action this slice** — a disabled
  "Publicar al catálogo (G2)" placeholder marks the seam.
- Reuse the wizard's existing player/components and visual voice — explore
  before inventing.

### Tests

- Backend (`tests/web/`): 409-when-live (fake registry), 503-when-disabled,
  defaulting (bpm center, wav, thinking), 422s, status mapping incl.
  degraded-poll and parse-error passthrough, proxy streaming + auth +
  path validation. MockTransport only.
- Frontend: vitest for the polling hook/state machine (pending→done,
  degraded blip, failed) and the flag gating; Playwright E2E with stubbed
  `/api/generator/*` walking form → task card → takes rendered (house
  stub conventions from the existing E2E specs).

## G2 contract (2026-08-29) — publisher to the catalog

Split in two, collision-driven: **G2a (ingest machinery)** builds against
origin/main in parallel with G1 (disjoint files); **G2b (publish endpoint +
wizard button)** lands after G1 merges (both touch `generator.py` + the
wizard).

### G2a — `agent/keyscale.py` + `main.py --ingest`

- **`agent/keyscale.py`**: `keyscale_to_camelot(keyscale: str) -> str` —
  parses ACE's `metas.keyscale` forms ("A Minor", "C# Major", "Ab minor",
  flats/sharps, tolerant of case/whitespace) into Camelot per the spec §5.3
  table; `ValueError` naming the offending input when unparseable.
  Consistency asserted against `agent/generative/scales.py` where the two
  overlap.
- **`main.py --ingest`** (the agreed ingest v2; sits beside
  `--build-catalog`/`--fix-incomplete`):
  `--ingest <wav> --genre <genre_folder> --display-name <name>
  (--bpm N --keyscale "A Minor" | --sidecar meta.json) [--variant-of <id>]
  [--lyrics <file>] [--dry-run]`.
  Sidecar shape (v2): `{bpm, keyscale, display_name, variant_of?, lyrics?}`.
  Pipeline: genre folder must exist → probe audio (soundfile): duration
  ≥ 120 s or refuse → resample to 44.1 kHz/16-bit/stereo via an ffmpeg
  subprocess ONLY when not already conformant → bpm inside the genre's
  `BPM_GENRE_RANGES` window or refuse (naming the window) → WAV lands in
  `tracks/<genre>/` → tracks.json entry `{id, display_name, file,
  genre_folder, genre, camelot_key, bpm, variant_of}` following the SAME
  id/display conventions `--build-catalog` uses (read and mirror them; no
  id collisions) → **tracks.json backed up before writing** (house rule) →
  optional `.lrc` sidecar next to the WAV. **No madmom anywhere in this
  path** (beatgrid backfill stays `--fix-incomplete`'s job). `--dry-run`
  prints the full plan and touches nothing.
- Tests: the full §5.3 table (24 rows) + enharmonics + garbage; ingest
  happy path into a tmp catalog fixture; every refusal (short, bad genre,
  out-of-window bpm, unparseable keyscale); a REAL tiny-ffmpeg resample
  (48 k in → 44.1/16 out, probed); conformant input NOT re-encoded;
  variant_of passthrough; backup file created; dry-run leaves zero writes;
  id-collision behavior.

### G3 contract (draft 2026-08-29) — take editing before publishing

- **Backend**: `POST /api/generator/edit` — body `{file (the SOURCE take's
  persisted decoded path — the persistence rule: no task_id, ever), mode:
  "repaint"|"cover"|"complete", prompt?, repainting_start?,
  repainting_end?, audio_cover_strength?, genre_folder? (for the bpm
  default), experimental?}` → validates `file` with THE validator
  (root-checked — this value is sent to ACE as `src_audio_path`), releases
  with `task_type` set, returns `{task_id, queue_position, eta_seconds}`
  served by the existing polling endpoint. Refusals mirror `POST /tasks`
  (503 / 409-VRAM / 422 — an edit releases GPU work too). On ACE's 400
  "absolute audio file paths are not allowed" (the TMPDIR caveat below):
  degrade to multipart — download via `stream_audio`, re-release as a
  multipart upload — never a fatal error.
- **Source audio: CONFIRMED by the ACE session (verified in their server
  code, 2026-08-29)** — the result's `file` is `/v1/audio?path=<server
  path>`; the URL-DECODED path is directly reusable as `src_audio_path`
  (their validator admits paths under the process tmpdir, where results
  live). No multipart in the client. Same-server only.
- **Persistence rule (applies to G1/G2b/G3 alike)**: ACE's job RECORDS
  expire (in-memory store, 24 h max age, dies with the process — and the
  VRAM protocol stops the server between batches); the result FILES are
  never reaped and survive restarts. Therefore the PAGE persists each
  take's decoded path + metas + prompt/lyrics the moment a poll returns
  them, and every later flow (publish, edit) carries that data FROM THE
  CLIENT — the backend never re-queries `query_result` for an old task.
- Repaint: `repainting_start/end` in SECONDS of the source audio,
  `end=-1` = to the end; `chunk_mask_mode: "explicit"` applies the range
  as an exact mask; `thinking` is auto-ignored in repaint.
- **Path shape (ACE session, code-verified 2026-08-29)**: the decoded
  `path` param is an ABSOLUTE POSIX path on ACE's disk, prefix
  `/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio/` in this
  deployment (UUID-ish name + take-index suffix + extension), encoded with
  `quote(path, safe="")` — TOTAL percent-encoding, slashes as `%2F`.
  Apollo validates by decoding once and prefix-matching a CONFIGURED base
  dir (env `ACESTEP_AUDIO_ROOT`); `http(s)`-prefixed values are rejected.
- **G3 fallback caveat**: ACE validates `src_audio_path` against ITS
  process's `gettempdir()`, which a foreign `TMPDIR` in the launch env
  could point elsewhere — the server would then 400 its own result paths.
  G3's client treats a 400 "absolute audio file paths are not allowed" as
  DEGRADE TO MULTIPART (upload the downloaded take), never a fatal error.
- **Frontend**: per-take "Editar" → mode selector + a range control over
  the take's duration for repaint (+ strength for cover); the edited result
  renders as a CHAINED task card under its source (lineage visible — on
  stream and in the wizard, "v2 of take 1" must read at a glance).
- Tests both sides, house patterns (MockTransport / vitest + one E2E stub).

### G4 contract (draft 2026-08-29) — the critic scores takes

An LLM cannot hear, so the SCORE comes from machinery that can, and the
LLM adds the read. Two layers, one endpoint:

- **Backend**: `POST /api/generator/critique` — body `{file (persisted
  decoded path), metas{bpm, keyscale, duration}, prompt, genre_folder}`
  (`extra="forbid"`, the persistence rule as ever). Flow: validate path
  (THE validator, root-checked) → download via `stream_audio` to a temp
  file → run **`bench_wav`** (agent/generative/bench.py, PR #127 — the
  project's own definition-of-done gate) against `genre_folder`'s
  references → optional LLM layer: ONE completion (the `GENERATIVE_MODEL`
  precedent, e4b-class; env-gated, degraded gracefully to null when the
  LLM is off/unreachable) given the bench numbers + the request's prompt +
  metas, returning one paragraph: does this take match what was asked, and
  what would you fix. Response: `{passed, reference_informed, advisory,
  bands, critique: str|null}`. 503 generator-off; NO 409 (disk + a small
  LLM call, not the ACE GPU — but the LLM lives on tunel too: use a SHORT
  timeout and degrade, never block the wizard on it). Genres without
  committed references → `{passed: null, ...}` with a clear note, not an
  error.
- **Frontend**: a per-take "Score" action (button first, auto later):
  renders the bench verdict as compact chips (each reference_informed
  metric in/out of band, LUFS advisory) + the critique paragraph. Scoring
  never gates publishing — it informs the human (the bench's
  merge-gate philosophy: automated evidence, human decision).
- **Tests**: backend — happy score with a synthetic in-band WAV +
  injectable references (the #127 pattern), out-of-band rendering,
  missing-references genre, LLM layer mocked (present/absent/timeout →
  critique null), path validation, 503; frontend — score state machine +
  chips rendering; E2E — stub critique, walk take → score → chips.

### G2b — publish endpoint + wizard button (queued behind G1's merge)

- `POST /api/generator/publish` — body `{file (the take's /v1/audio path
  param, URL-decoded, AS PERSISTED BY THE PAGE per the G3 persistence
  rule), metas{bpm, keyscale, duration}, prompt?, lyrics?, display_name,
  genre_folder, variant_of?}`: downloads the audio via the client, runs
  THE SAME ingest path (import it, don't reimplement), publishes into the
  catalog. No task_id in the contract — the backend never re-queries an
  old task (ACE's job store is mortal; the file is not). Refuses while
  the builder is running.
- Wizard: the G1 placeholder button comes alive; per-take publish with
  genre + name prefilled from the form; first-batch validation handshake
  with the Apollo session stays the agreed manual step.

## G5 runbook (draft 2026-08-29) — the first real batch, end to end

The definition-of-done of the whole lane. Split so the risky half stays
gated:

### G5a — headless real batch (autonomous, no deploy)

Drives the REAL flow with the merged code, without touching the prod
containers: a script/session using `acestep_client` + `main.py --ingest`
directly. The GPU-sharing constraint SELF-SEQUENCES thanks to the
persistence rule — result files are immortal, so each phase can run with
the GPU in a different hands:

1. **Coordinate** with the ACE session: server up on :8001, no live set
   (`live-ws` check), GPU handed to ACE. **The exclusivity is
   SYMMETRIC** (learned the hard way, first real batch 2026-08-29:
   LM Studio JIT-loaded e4b mid-phase-A — a playground /mind click is
   enough — and ACE's 5 Hz LM died OOM at init): before phase A,
   `lms unload --all` on tunel AND stop every Apollo-side LLM caller
   (playground server, benches); they come back in phase C.
   **Poisoned-init cure** (first batch, 2026-08-29): after an OOM, ACE
   caches `_llm_init_error` and every `thinking` release fails
   INSTANTLY without touching the GPU. The cure is
   `POST /v1/init {init_llm: true}` — re-runs the LM init and clears
   the cached error, DiT untouched. No restart needed.
2. **Generate**: one release per target genre (deep house first),
   `bpm` = window center, `audio_duration ≥ 150`, `thinking: true`,
   `batch_size 2`, `audio_format wav`. Poll to done; PERSIST decoded
   paths + metas (the rule). **Lazy-load warning (ACE session)**: the
   FIRST release after server start pays the model load (DiT + the 5 Hz
   LM for thinking) — several extra minutes on that first poll, and
   `/health` answers before models are loaded. A slow first poll is the
   load, not a failure; `avg_job_seconds` only means something after it.
   Both takes of the batch share the piece → the keeper publishes first,
   the sibling as `variant_of` its display name.
3. **Download WHILE the server is up** (runbook fix 2026-08-29:
   `/v1/audio` dies with the server — the download is the TAIL of phase
   A, before the stop signal; scp over SSH is the fallback if the server
   already stopped, since the files themselves survive).
4. **ACE unloads** (the VRAM protocol; they ping when free).
5. **Score with the GPU back**: `quality_bench --wav` per downloaded
   take vs the genre references; optional LLM critique now that LM
   Studio can load.
6. **Publish the keeper**: `main.py --ingest` with the generation metas
   (backup automatic); second take as `variant_of`. **The Apollo session
   validates the first tracks.json entry before anything else** — the
   agreed handshake.
7. `--fix-incomplete` (detached Docker) backfills duration/beatgrid/MP3.
8. **Prove the loop closed**: the eligibility screen accepts it and
   `pick_next_track` can surface it (a dry selection check, not a live
   set).

Writes to the real catalog (main checkout) with the ingest's automatic
backup — reversible; scheduled to avoid any catalog build.

### G5b — deploy the wizard to prod (GATED on Pablo's explicit OK)

The sanctioned path, nothing new: merge `origin/main` into the deploy
branch in the main checkout (live-ws check first — never mid-broadcast),
set `ACESTEP_BASE_URL` (+ optionally `ACESTEP_AUDIO_ROOT`,
`GENERATIVE_MODEL`) in `.env`, recreate backend (`up -d backend` — a
restart keeps old env), verify `/api/generator/health` from the wizard.
After G5b the whole G1–G4 surface is live in the editor.

## Ops notes

- Port map: ACE API :8001 (LAN) — no conflict with 4010/4020 (prod),
  4011/4021 (dev), 4031/4032 (playground).
- VRAM: 16 GB shared with LM Studio — see the root CLAUDE.md rule. The
  symptom of violation is LM Studio 400 "Failed to load model" while
  `/v1/models` still lists (listed ≠ loadable).
- First published batch: the Apollo session validates the first tracks.json
  entry before the builder makes it canon (agreed with the ACE session).
