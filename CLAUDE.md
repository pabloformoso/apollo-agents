# ApolloAgents — Developer Notes

Automated DJ mix generator + multi-agent AI pipeline. Takes WAV audio files,
BPM-matches them, applies crossfades, and renders 1080p YouTube videos with
waveform visualizations, AI-generated artwork, and retro animated titles.

Folder-specific decisions and gotchas live in nested CLAUDE.md files:
`agent/CLAUDE.md`, `web/CLAUDE.md`, `tests/CLAUDE.md`, `scripts/CLAUDE.md`.
Update the one next to the code you touch instead of growing this file.

## Running

```bash
# Build/refresh the track catalog (run once after adding new WAV files)
python main.py --build-catalog

# Re-analyse catalog entries with missing BPM or Camelot key
python main.py --fix-incomplete

# Generate a session directly (no agent)
python main.py --name "midnight-lofi" --genre "lofi - ambient" --duration 60

# Run the conversational agent
uv run python agent/run.py

# Generative MIDI spike (needs `uv sync --group synth`, loopMIDI running,
# a synth listening on the port — see docs/reasoned-generative-engine.md)
uv run python scripts/spike_generative.py            # LLM-driven; type "darker"/"build"/"quit"
uv run python scripts/spike_generative.py --no-llm   # loop the seed groove only
```

## Web app

Backend (FastAPI) on `:4020`, frontend (Next.js) on `:4010`. Run both from the project root in the **main checkout** (not a worktree — worktrees lack tracks/.env/venv).

```bash
# Backend — install web deps once, then run from project root
uv sync --group web
uv run uvicorn backend.app:app --reload --port 4020 --app-dir web

# Frontend (in another shell)
cd web/frontend
npm run dev   # serves on :4010, proxies /api to :4020
```

`--genre` must match a subfolder name under `tracks/` (case-insensitive).
`--duration` is in minutes (soft target — last track is never cut).

Requires an `.env` file — see `.env.example`.

### Docker (dev stack)

Alternative to the host-side `uv` / `npm` workflow above — both services
in containers with hot reload. Requires Docker Desktop.

```bash
docker compose up --build       # first run / after dep changes
docker compose up               # subsequent runs
docker compose down             # stop, keep cached volumes
docker compose down -v          # also wipe venv + node_modules caches
```

- `./tracks`, `./output`, `./artwork`, and `./agent` bind-mount from the
  host so the catalog's relative paths resolve unchanged, new WAVs are
  visible immediately, and generated mixes land back on the host.
- `.env` is loaded via compose's `env_file` — same file the CLI uses.
- One-off commands: `docker compose run --rm backend uv run pytest tests/`.
- `--build-catalog` / `--fix-incomplete` need madmom — rebuild with
  `docker compose build --build-arg INSTALL_BEATGRID=1 backend`.
- **The frontend container mirrors the REPO, not just `web/frontend`.**
  The frontend reaches two levels up for things outside its own tree —
  `@algorave/pen` (the one copy of the pen module), `turbopack.root`,
  and the palette/validate routes' spike dir. Mounted as
  `./web/frontend:/app` those resolved to `/`, and in `next dev` a
  single unresolvable import is a GLOBAL compile error: every route
  500s, the DJ lane included. It is `./:/repo` with the workdir at
  `/repo/web/frontend` for that reason. Any new `../..` path from the
  frontend needs the container to keep that shape.
- **The frontend image is Node 22 because of the validator**, not
  because of Next. `validate.mjs` imports `registerHooks` from
  `node:module` (Node 22+) and the live-validation route spawns it; on
  Node 20 the spawn dies and the route answers "validator produced no
  verdict" — the editor silently stops checking what a performer types.
- **CI cannot catch either of these.** It builds on the host layout and
  never starts the compose stack, so the only proof is bringing the
  stack up and hitting the routes. Both bugs shipped green (2026-09-02).

## Project structure

```
main.py                        # Single-file pipeline (~2600 lines)
packages/
  py-obs/                      # `deus_obs` — OTel traces to Phoenix.
                               #   Standalone, zero-dependency, NOT apollo_*
                               #   on purpose. Its own README.
agent/
  run.py                       # Apollo orchestrator + all agent loops
  tools.py                     # Tool functions (catalog, playlist, validator, memory)
  memory.json                  # Session history — gitignored, auto-created
tracks/
  tracks.json                  # Unified catalog: id, display_name, file,
                               #   genre_folder, genre, camelot_key, bpm, variant_of
  lofi - ambient/              # WAV files per genre
  deep house/
  techno/
  cyberpunk/
output/
  <session-name>/              # Final video and audio outputs (gitignored)
    mix_output.wav
    mix_video.mp4
    short.mp4
    session.json
    transitions.json
    youtube.md
artwork/
  <session-name>/              # DALL-E 3 generated backgrounds (gitignored)
fonts/
  PressStart2P-Regular.ttf
```

## Architecture decisions

- **Single file (`main.py`)** — intentional, ~2600 lines is manageable for this scope
- **Lossless pipeline** — WAV throughout, only AAC compression at final video encode
- **Per-session output** — `output/<session-name>/`, `artwork/<session-name>/`
- **Artwork deduplication** — tracks with the same `display_name` share one image
- **Agent memory** — `agent/memory.json` is gitignored; each user builds their own
- **Session eligibility (v3.9.1)** — tracks shorter than 120 s
  (`APOLLO_MIN_TRACK_DURATION_SEC`) are never SELECTED into a session;
  they stay in the catalog for stream-by-id/ratings. Screen lives in the
  selection paths only — see `agent/CLAUDE.md`.

## Deploy & operations (read before touching prod)

Prod = `docker compose` in the **main checkout**
(`C:\Users\pablo\Documents\GitHub\apollo-agents`), which sits on
`main` and tracks `origin/main` directly (the `deploy/*` branch era
ended 2026-08-29). The repo is bind-mounted into the containers and
the backend runs `uvicorn --reload`.

The only sanctioned path to prod:

1. Feature branch (worktree) → PR → **squash-merge to `main`** with CI
   green (read the FULL failure list; `youtube_chat` fails local-only).
2. In the main checkout: `git fetch && git merge --ff-only origin/main`.
3. Restart containers if needed (`docker compose restart backend frontend`).

Hard rules:

- **The main checkout stays a pure mirror of `origin/main`** — no local
  commits, no deploying unmerged work. If `--ff-only` refuses, the
  checkout has drifted (first check `git branch --show-current` still
  says `main`); investigate, don't force a merge.
- **Never merge into the main checkout or restart containers while a
  live session is running** — `--reload` watches `agent/` and `web/`,
  so a merge mid-stream kills the broadcast. Check first:
  `docker logs --since 30m apollo-backend | grep live-ws`.
- Ports **4010/4020 are the prod stack** — dev servers go on 4011/4021.
- **The first backend start after the migrations PR converts
  `web/backend/apollo.db` to WAL and writes one
  `apollo.db.<stamp>.bak` beside it.** The conversion is one-way and a
  property of the FILE, so rolling the code back does not undo it (any
  SQLite since 3.7 reads it fine). Verified on a copy of the live 782 KB
  database: schema byte-identical, all 82 rows intact, `user_version`
  0 → 1. Keep the `.bak` until the stack has served real traffic — there
  is no `down()`, by design; see `web/CLAUDE.md`.
- Worktrees have no `tracks/`, `.env`, or venv — copy `.env` from the
  main checkout; run anything runtime-ish from the main checkout.
- `--build-catalog` needs madmom → run it in detached Docker
  (~1.25 min/track, serial; writes tracks.json only at the end).
- **The `tunel` GPU (16 GB) is SHARED** with the ACE-Step project
  (music generation, same box as LM Studio). Protocol agreed 2026-08-29:
  ACE never holds VRAM idle (lazy-load, unload after batches) and never
  during a live session (same `live-ws` check as above); it pings this
  project's session via SendMessage when it frees the GPU. Symptom of a
  violation: LM Studio returns 400 "Failed to load model" for EVERY
  model while `/v1/models` still lists them — *listed ≠ loadable*; check
  `nvidia-smi` on tunel before blaming the model or the gateway.
  **The exclusivity is SYMMETRIC**: while an ACE generation batch runs,
  LM Studio must hold NO model — `~/.lmstudio/bin/lms unload --all` on
  tunel and stop every Apollo-side LLM caller (playground server on
  :4032, benches) first. A single playground /mind click mid-batch
  JIT-loads a model and OOMs ACE's 5 Hz LM at init (first real batch,
  2026-08-29). LLM work resumes when ACE frees the GPU.

## Observability (`packages/py-obs`, stage 1)

Traces go to the **Arize Phoenix on this box** (`http://localhost:6006`,
OTLP/HTTP on that same port — 20.x has no separate receiver port, and its
gRPC 4317 is exposed but not published, so gRPC cannot work here). That
Phoenix is **SHARED with eOS/SynapseFlow**: always set `OBS_PROJECT`, or
Apollo's spans land in `default` next to theirs.

- Opt-in by design: `uv sync --group obs`. The group is NOT in
  `default-groups`, so CI never installs the OTel SDK and "unconfigured is
  a no-op" is enforced structurally rather than by a runtime flag.
  Unconfigured saves ~80 ms of interpreter start per process — the whole
  reason the SDK import lives inside `install()`.
- **`localhost:6006` in `.env` is the HOST's Phoenix and would be the
  CONTAINER itself.** Both compose files pin `OTEL_EXPORTER_OTLP_*` and
  `OBS_ENDPOINT` to empty under `environment:` (which beats `env_file:`)
  and read `APOLLO_OTLP_ENDPOINT` instead — a different name, so the host
  value cannot leak in. Turning it on in a container means putting
  `APOLLO_OTLP_ENDPOINT=http://host.docker.internal:6006` in `.env`;
  `extra_hosts: host-gateway` is what makes that name resolve on Linux.
- `OBS_CAPTURE` defaults to `metadata` — argument names and return types,
  never values. Apollo passes `context_variables` (which carries API keys)
  into every agent tool, and the trace store is shared.
- Stage 1 wires the bootstrap only: `install()`/`shutdown()` in the FastAPI
  lifespan. Nothing is instrumented yet, so a configured backend that has
  served no explicitly-spanned code sends no spans at all.
- Everything else — precedence table, the ten public names, why this is not
  `arize-phoenix-otel` — is in `packages/py-obs/README.md`.

## Known issues / backlog

- Stall-watchdog alarm: after N consecutive forced advances the session
  should alert/stop instead of silently churning tracks (2026-08-01).
- Poisoned BPMs in catalog (lofi@150, synthware 176–212) act as
  genre-drift bridges.
- `tests/web/test_youtube_chat.py` fails locally, passes in CI.
- eslint baseline in `web/frontend`: 17 errors + 6 warnings across 11
  files (2026-08-31). CI does not run lint; see `web/CLAUDE.md`.

## Key constants (top of `main.py`)

| Constant | Purpose |
|---|---|
| `CROSSFADE_SEC` | Crossfade overlap length (default 12s) |
| `TEMPO_RAMP_SEC` | Gradual BPM ramp after crossfade (default 16s) |
| `BPM_MATCH_THRESHOLD` | Min BPM diff to trigger tempo matching (default 5) |
| `VIDEO_SIZE` | Output resolution (default 1920×1080) |
| `FONT_PATH` | Press Start 2P pixel font |

## Genre themes

Defined in `GENRE_THEMES` dict in `main.py`. Each genre has: `artwork_style`,
`title_color`, `title_stroke_color`, `bg_color`, `waveform_color`, `particle_color`.

Available `artwork_style` values: `abstract`, `realistic`, `anime`,
`dystopic-calm`, `dark-techno`, `organic-zen`, `deep-house-neon`,
`healing-aura`.

An unknown `artwork_style` falls back to `abstract` **silently**, so a typo
costs a whole session's artwork before anyone notices — `tests/test_genre_healing.py`
asserts every `GENRE_THEMES` entry points at a real `ARTWORK_PROMPTS` key.

## Adding a new genre

One definition, in `agent/genres.py`. It used to be six edits across three
files — `BPM_GENRE_RANGES` and `GENRE_THEMES` in both `main.py` and
`agent/tools.py`, `GENRE_STYLE_PROMPTS` in `agent/tools.py`,
`GENRE_NEIGHBOURS` in `agent/live_engine.py` — and five of the six omissions
failed silently. Those four names still exist and still work; they are now
read-only VIEWS of the one definition, so they cannot drift.

1. Create `tracks/<genre-name>/` and add WAV files
2. Add an entry to `GENRE_DEFAULTS` in `agent/genres.py` **before** building
   the catalog. All four fields, or `tests/test_genres_source_of_truth.py`
   fails — deliberately, because each omission is invisible at runtime:

   | field | what a missing one costs |
   |---|---|
   | `bpm` | the raw detection is stored verbatim, poisoning tempo matching for every set that touches the genre |
   | `theme` | artwork falls back to `abstract` without a word |
   | `style_prompt` | ACE generates off-genre and the take cannot be promoted |
   | `neighbours` | an endless set cannot widen out of the genre |

   Make the BPM window exactly one octave wide (`hi == 2 * lo`) for slow or
   beatless material: librosa locks onto 2-4x the real pulse on drones and
   pads, and the window drives the octave ladder that corrects it. One octave
   means only one rung can qualify.

   Write `neighbours` symmetrically — the test suite enforces it. Never let
   adjacency be inferred from tempo: a soul jazz entry stored at 165 BPM
   matched a 164 BPM synthware track and put twenty techno tracks on a live
   "meditación non stop" broadcast (2026-09-07).

3. Run `python main.py --build-catalog` (see the Docker note below — madmom
   is not installed on the host)
4. If no existing `artwork_style` fits, add an `ARTWORK_PROMPTS` template in
   `main.py` and point the theme at it. An unknown style falls back to
   `abstract` **silently**, so a typo costs a whole session's artwork.

### Genres added by an installation

`GENRE_DEFAULTS` is layer one: shipped, versioned, reviewable in a PR, and it
reaches every installation on the next update. Layer two is genres added by a
running installation (from the catalog UI), which live in SQLite and are
merged over the defaults per FIELD — an override of one BPM window keeps the
shipped theme and prompt.

The layering is not incidental. Seeding the database with today's defaults
instead would freeze them into every install forever, so a BPM window found
to be wrong could never be corrected for anyone. Register the source with
`genres.register_loader()`; with none registered — `main.py --build-catalog`,
worktrees, CI — the defaults are the whole answer, which is why the CLI needs
no database.

## Agent tool conventions

All tools in `agent/tools.py` follow this signature:
```python
def tool_name(param: type, context_variables: dict) -> str
```
`context_variables` is injected by the orchestrator — never passed by the LLM.
List parameters are passed as JSON strings to stay within the schema builder's type system.

## Dependencies

Managed with `uv`. Install: `uv sync`

Key libs: `librosa`, `pyrubberband`, `moviepy`, `pydub`, `openai`, `anthropic`, `Pillow`
