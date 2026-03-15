## Why

The artwork backgrounds in the video output are heavily blurred and darkened to 25% brightness, making them barely visible. The DALL-E generated artwork is a key visual element that should be prominent (85% visible). Additionally, artwork can show black/white borders when aspect ratios don't perfectly match 1920×1080. Session 5 (a new LoFi study session with 20 tracks) needs a session.json configuration to work with the curated playlist system.

## What Changes

- Increase artwork background brightness from 25% to 85% (`ARTWORK_DARKEN_FACTOR` 0.25 → 0.85)
- Remove or heavily reduce the Gaussian blur on artwork backgrounds so the art is clearly visible
- Implement proper cover-crop scaling for artwork to guarantee full-screen coverage with zero black/white borders
- Adjust overlay element opacity/contrast (waveform, titles, particles) to remain readable against brighter backgrounds
- Create `tracks/session 5/session.json` with curated LoFi study playlist matching Session 4's style and theme
- Update the per-session theme `bg_darken` to support the new brightness model where artwork is the primary visual

## Capabilities

### New Capabilities
- `session-5-config`: Session 5 playlist configuration (session.json) with track order, Camelot keys, genre tags, and anime-style LoFi theme matching Session 4
- `fullscreen-artwork`: Artwork scaling and compositing pipeline that guarantees full-frame coverage with no letterboxing, reduced blur, and configurable brightness (defaulting to 85%)

### Modified Capabilities
- `youtube-short`: Short generation artwork background must also use the new fullscreen cover-crop logic and brightness settings

## Impact

- **Files**: `main.py` (artwork loading, background compositing, constants), `tracks/session 5/session.json` (new file)
- **Constants**: `ARTWORK_DARKEN_FACTOR`, `ARTWORK_BLUR_RADIUS`, `ARTWORK_API_SIZE`
- **Functions**: `_load_artwork_images`, `_generate_artwork`, `_get_artwork_frame`, `_ken_burns_frame`, `_render_short_frame`, `generate_short`
- **Visual**: Existing sessions will look brighter — artwork becomes the dominant visual element
- **Dependencies**: No new dependencies; Pillow and numpy already handle image transforms
