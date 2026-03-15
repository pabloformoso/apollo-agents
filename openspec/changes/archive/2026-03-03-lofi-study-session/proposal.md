## Why

The current sessions (1-3) target synthwave/cyberpunk aesthetics with retro pixel fonts and abstract digital artwork. There's demand for a LoFi study/work session — a ~120-minute ambient mix with cosy, realistic room visuals that loop seamlessly. This expands the project's genre range and taps into the massive LoFi study music audience on YouTube.

## What Changes

- New session 4: ~120-minute LoFi playlist with curated track order for sustained focus
- New artwork style: realistic cosy room scenes (warm lighting, desk, plants, rain on window) generated via DALL-E 3 with style-appropriate prompts
- New video background pipeline: generate short loopable video clips from static artwork (subtle animation — steam from coffee, rain, flickering light)
- Session-level style configuration: allow sessions to override visual defaults (font, colors, title animation) so LoFi sessions use warm tones instead of neon green
- Loopable video generation: ensure video backgrounds crossfade seamlessly for 2-hour playback without visible jumps

## Capabilities

### New Capabilities
- `lofi-session-config`: Session 4 structure — session.json with LoFi tracks, Camelot keys, genres, and ~120min playlist order
- `realistic-artwork-gen`: Artwork generation with realistic/photographic style prompts (cosy room scenes) instead of abstract digital art. Configurable per-session style
- `artwork-to-video-loop`: Pipeline to convert static artwork into short loopable video clips with subtle animation (parallax, particle effects, ambient motion)
- `session-visual-theme`: Per-session visual theming — font choice, title color, background overlay opacity, waveform colors. Allows LoFi sessions to use warm/muted aesthetics vs. retro neon

### Modified Capabilities

## Impact

- **main.py**: New artwork prompt logic (branching by session style), video loop generation pipeline, per-session theme config loading
- **tracks/session 4/**: New directory with session.json and LoFi audio files (WAV)
- **fonts/**: May need a second font for LoFi aesthetic (e.g., a clean sans-serif or handwritten style)
- **Dependencies**: Possible new dependency for video animation (or leverage existing MoviePy transforms)
- **DALL-E API**: New prompt templates for realistic room scenes — higher detail prompts
- **Output**: `output/session 4/` and `artwork/session 4/` directories
