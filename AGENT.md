# Agent Guidelines — Deep Session Generator

## What this project is

A Python tool that automates production of DJ mix videos for YouTube. It reads
audio tracks, BPM-matches them, applies smooth crossfades, and renders a 1080p
video with animated visualizations and AI-generated artwork backgrounds.

## Key conventions

- **Do not split `main.py`** — single-file architecture is intentional.
- **No lossy intermediate audio** — always work in WAV; only compress to AAC at
  the final `ffmpeg` video encode step.
- **Session isolation** — every session has its own subdirs under `output/` and
  `artwork/`. Never write into another session's directory.
- **Artwork is cached** — DALL-E 3 images are saved to `artwork/session N/`.
  Do not regenerate if the file already exists.
- **Backward compatibility** — sessions without `session.json` must still work
  (they fall back to flat dir scan + BPM sort, as in Session 1).

## Adding a new session

1. Create `tracks/session N/` and drop audio files (WAV preferred) inside.
2. Create `tracks/session N/session.json` with the playlist, BPM, Camelot keys,
   and optional theme overrides.
3. Run `python main.py N`.

## Configuration constants (top of `main.py`)

Tune these before changing any logic:

| Constant | Purpose |
|---|---|
| `CROSSFADE_SEC` | Crossfade overlap length |
| `TEMPO_RAMP_SEC` | Gradual BPM ramp after crossfade |
| `BPM_MATCH_THRESHOLD` | Min BPM diff to trigger tempo matching |
| `VIDEO_SIZE` | Output resolution (default 1920×1080) |
| `RETRO_TITLE_COLOR` | Neon green `#00FF88` — keep unless theme overrides |
| `FONT_PATH` | Press Start 2P pixel font |

## Theme system

Sessions can override visual style via the `"theme"` block in `session.json`.
All fields are optional — unset fields inherit `DEFAULT_THEME` from `main.py`.
Available `artwork_style` values: `abstract`, `realistic`, `anime`,
`dystopic-calm`, `dark-techno`, `organic-zen`, `deep-house-neon`.

## What to avoid

- Do not add a duration cap unless explicitly asked — full sessions play through.
- Do not change the WAV → AAC pipeline to an all-MP3 pipeline.
- Do not refactor into multiple files without explicit instruction.
- Do not call the OpenAI API unless generating artwork for a new session.
