## Why

Session 6 introduces a dark techno aesthetic — a new sonic and visual direction for the Deep Session Generator. Sessions 4 and 5 established the warm lo-fi study vibe; Session 6 swings to the opposite end: industrial, minimal, pounding dark techno. This expands the channel's genre range and audience reach.

## What Changes

- New `tracks/session 6/session.json` with ~20 dark techno tracks, curated playlist order, and a dark industrial theme
- New `"dark-techno"` artwork prompt template in `ARTWORK_PROMPTS` — industrial warehouses, concrete, strobes, fog machines, monochrome with accent neon
- New font for the dark techno aesthetic (bold, industrial — e.g., Orbitron or Share Tech Mono)
- Session 6 theme block: dark colors (near-black bg), harsh neon accent (red or magenta), minimal particles, aggressive waveform colors
- Track generation via Suno AI (WAV format, ~20 tracks, 2-4 min each, 128-140 BPM range)
- YouTube description and metadata for Session 6

## Capabilities

### New Capabilities
- `dark-techno-session-config`: Session 6 directory structure, session.json with dark techno playlist, theme configuration, and industrial visual parameters
- `dark-techno-artwork`: New "dark-techno" artwork prompt template for DALL-E 3 that generates industrial/warehouse/underground club visuals
- `dark-techno-youtube`: YouTube title, description, tags, and thumbnail text for Session 6

### Modified Capabilities
_(none — the existing theme system, artwork pipeline, and video generator already support custom themes, fonts, and artwork styles without requirement changes)_

## Impact

- **Files**: `main.py` (add artwork prompt template), `tracks/session 6/session.json` (new), `fonts/` (new industrial font), `output/session 6/youtube.md` (new)
- **Audio**: ~20 new WAV tracks in `tracks/session 6/`
- **Dependencies**: New font file download needed
- **No breaking changes**: Existing sessions unaffected — Session 6 uses the same theme override system
