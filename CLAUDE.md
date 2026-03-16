# Deep Session Generator

Automated DJ mix generator that produces 1080p YouTube videos from audio tracks.
Takes audio files, BPM-matches them, applies crossfades, and renders video with
waveform visualizations, AI-generated artwork, and retro animated titles.

## Running

```bash
# Build/refresh the track catalog (run once after adding new WAV files)
python main.py --build-catalog

# Generate a session
python main.py --name "midnight-lofi" --genre "lofi - ambient" --duration 60
```

`--genre` must match a subfolder name under `tracks/` (case-insensitive).
`--duration` is in minutes (soft target — last track is never cut).

Requires an `.env` file with `OPENAI_API_KEY` for DALL-E 3 artwork generation.

## Project structure

```
main.py                        # Single-file implementation (~2500 lines)
tracks/
  tracks.json                  # Unified catalog: id, display_name, file, genre_folder,
                               #   genre, camelot_key, bpm, variant_of
  lofi - ambient/              # WAV files per genre
  deep house/
  techno/
  cyberpunk/
output/
  <session-name>/              # Final video and audio outputs
    mix.wav
    mix_video.mp4
    short.mp4
    session.json               # Saved playlist for reproducibility
    youtube.md                 # Upload metadata: title, description, tracklist, tags
artwork/
  <session-name>/              # DALL-E 3 generated backgrounds (cached)
fonts/
  PressStart2P-Regular.ttf     # Retro pixel font for titles
```

## youtube.md format

Auto-generated at `output/<session-name>/youtube.md` after every full pipeline run. Contains:

- **Title** — `Deep Session // <Name> — <Duration> of <Genre>`
- **Description** — intro paragraph, track count, timestamped tracklist, technical notes (lossless pipeline, Camelot harmonic progression), hashtags
- **Tags** — comma-separated genre tag list
- **Thumbnail Text Ideas** — 3 copy suggestions

Genre-specific hashtags/tags/intros are defined in `_GENRE_HASHTAGS`, `_GENRE_TAGS`, and `_GENRE_DESCRIPTION_INTRO` constants in `main.py`.

## Architecture decisions

- **Single file** — intentional, ~2000 lines is manageable for this scope
- **Lossless pipeline** — WAV throughout, only AAC compression at final video encode
- **Per-session output** — `output/session N/`, `artwork/session N/`
- **Artwork deduplication** — tracks with the same `display_name` share one image
- **Theme system** — sessions can override colors, font, bg style, artwork style

## Artwork styles

Available values for `artwork_style` in `session.json`:
`abstract`, `realistic`, `anime`, `dystopic-calm`, `dark-techno`, `organic-zen`, `deep-house-neon`

## Video outputs

- **Full session video** — 1920×1080, 24fps, spectral waveform, beat-reactive particles
- **YouTube Short** — 1080×1920, 20s teaser with centered artwork

## Dependencies

Managed with `uv`. Install:
```bash
uv sync
```

Key libs: `librosa`, `pyrubberband`, `moviepy`, `pydub`, `openai`, `Pillow`
