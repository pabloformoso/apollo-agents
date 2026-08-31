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

## Project structure

```
main.py                        # Single-file pipeline (~2600 lines)
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
(`C:\Users\pablo\Documents\GitHub\apollo-agents`), which sits on a
`deploy/*` branch (currently `deploy/endless-w4-20260711`) carrying
main + not-yet-merged live work. The repo is bind-mounted into the
containers and the backend runs `uvicorn --reload`.

The only sanctioned path to prod:

1. Feature branch (worktree) → PR → **squash-merge to `main`** with CI
   green (read the FULL failure list; `youtube_chat` fails local-only).
2. In the main checkout: `git fetch && git merge origin/main` into the
   deploy branch, resolve, re-run tests there.
3. Restart containers if needed (`docker compose restart backend frontend`).

Hard rules:

- **Never deploy from `main` directly** — the deploy branch is the
  prod truth; skipping it strands its extra commits.
- **Never merge into the main checkout or restart containers while a
  live session is running** — `--reload` watches `agent/` and `web/`,
  so a merge mid-stream kills the broadcast. Check first:
  `docker logs --since 30m apollo-backend | grep live-ws`.
- Ports **4010/4020 are the prod stack** — dev servers go on 4011/4021.
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

1. Create `tracks/<genre-name>/` and add WAV files
2. Add a `BPM_GENRE_RANGES` entry in `main.py` **before** building the catalog.
   This is not optional for slow or beatless material: librosa locks onto
   2-4× the real pulse on drones and pads, and the range drives the octave
   ladder that corrects it. Make the window exactly one octave wide
   (`hi == 2 * lo`) so only one rung of the ladder can qualify. A genre with
   no range gets its raw detection stored verbatim, which poisons BPM
   matching for every set that touches it.
3. Run `python main.py --build-catalog` (see the Docker note below — madmom
   is not installed on the host)
4. Add a theme entry to `GENRE_THEMES` in `main.py`, and a new
   `ARTWORK_PROMPTS` template if no existing style fits
5. Mirror the genre into `agent/tools.py` — it keeps its **own copies** of
   `_BPM_GENRE_RANGES` and `GENRE_THEMES` for the web render endpoint and the
   playlist energy curve. These have drifted from `main.py` before; a missing
   entry degrades silently rather than raising

`--build-catalog` needs madmom, which only exists in the backend image. Run it
detached so it survives the host shell, layering worktree code over the main
checkout:

```bash
docker compose run -d --no-deps --name apollo-build -v "$PWD/main.py:/app/main.py" backend python main.py --build-catalog
```

It is strictly serial (~1-2 min/track) and writes `tracks.json` **only at the
very end** — back the catalog up first, an interrupted run loses everything.

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
