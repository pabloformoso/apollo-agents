## Why

The project has covered electronic, cyberpunk, lo-fi, and dark techno genres — all synthesizer-driven. A handpan meditation session opens a completely new acoustic/organic direction, broadening the channel's appeal to meditation, yoga, and ambient music audiences. This also requires a new artwork style ("organic-zen") since no existing visual theme fits the earthy, warm aesthetic of handpan music.

## What Changes

- Add new `organic-zen` DALL-E artwork prompt template to `ARTWORK_PROMPTS` in `main.py`, targeting warm painterly landscapes with earth tones
- Create `tracks/session 8/session.json` defining a 12-track handpan meditation session ("Resonance") with:
  - Plateau-style energy arc (gentle fade in → sustained meditative plane → gentle fade out)
  - Three track types: pure handpan solos (bookends), handpan + ambient pads (core), handpan + kalimba/organic accents (variety)
  - Organic-zen visual theme: amber/terracotta palette, Quicksand font, warm tones
  - BPM range 75-85, harmonically coherent Camelot key progression

## Capabilities

### New Capabilities
- `handpan-session-config`: Session 8 configuration — track list, playlist order, Camelot keys, genres, and organic-zen theme definition
- `organic-zen-artwork`: New DALL-E artwork prompt template for warm, painterly, earth-toned visuals

### Modified Capabilities

(none — no existing spec requirements change)

## Impact

- `main.py`: New entry in `ARTWORK_PROMPTS` dict (~5 lines)
- `tracks/session 8/`: New directory with `session.json` and WAV track files (user-supplied from Suno)
- `output/session 8/`: Generated at runtime
- `artwork/session 8/`: Generated at runtime via DALL-E
- No breaking changes, no dependency changes
