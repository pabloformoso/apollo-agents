# Deep Session Generator

Automated DJ mix generator that produces 1080p YouTube videos from audio tracks.
Takes audio files, BPM-matches them, applies crossfades, and renders video with
waveform visualizations, AI-generated artwork, and retro animated titles.

## Running

```bash
python main.py <session_number>
# e.g. python main.py 2
```

Requires an `.env` file with `OPENAI_API_KEY` for DALL-E 3 artwork generation.

## Project structure

```
main.py                        # Single-file implementation (~2000 lines)
tracks/
  session 1/                   # Flat dir, no session.json (legacy fallback)
  session 2/                   # WAV files + session.json
  session N/
    session.json               # Playlist order, BPM, Camelot keys, artwork style
output/
  session N/                   # Final video and audio outputs
artwork/
  session N/                   # DALL-E 3 generated backgrounds (cached)
fonts/
  PressStart2P-Regular.ttf     # Retro pixel font for titles
```

## session.json format

```json
{
  "theme": {
    "artwork_style": "deep-house-neon"
  },
  "tracks": [
    {
      "file": "Track Name.wav",
      "display_name": "Track Name",
      "bpm": 120,
      "key": "8A"
    }
  ]
}
```

Tracks without `session.json` fall back to flat directory scan + BPM sort.

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
