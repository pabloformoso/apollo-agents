## Context

The Deep Session Generator currently supports 5 sessions across two visual aesthetics: retro cyberpunk (Sessions 1-3, neon green, Press Start 2P font, abstract artwork) and warm lo-fi (Sessions 4-5, warm earth tones, Quicksand font, anime artwork). Session 6 introduces a third aesthetic: dark techno — industrial, minimal, monochrome with harsh neon accents.

The existing theme system (`_get_session_theme`, `DEFAULT_THEME`, `ARTWORK_PROMPTS`) already supports per-session font, colors, artwork style, and visual parameters. Session 6 primarily requires new content (tracks, config, prompts) and a new artwork prompt template.

## Goals / Non-Goals

**Goals:**
- Create Session 6 with ~20 dark techno tracks in curated playlist order
- Add a "dark-techno" artwork prompt template for industrial/underground visuals
- Add an industrial font (Share Tech Mono or Orbitron) for the dark techno title aesthetic
- Produce YouTube metadata (title, description, tags) for Session 6
- Maintain visual consistency: dark bg, red/magenta neon accents, aggressive waveform

**Non-Goals:**
- No changes to the mixing engine or crossfade logic
- No new video effects or rendering pipeline changes
- No changes to the theme system architecture (it already handles this)
- No changes to existing sessions

## Decisions

### 1. Font: Share Tech Mono
**Decision**: Use Share Tech Mono for the industrial monospace aesthetic.
**Rationale**: It's a free Google Font with a techy, industrial feel. Orbitron is more sci-fi; Share Tech Mono is more raw/underground which fits dark techno better. Monospace fonts evoke terminal/hacker aesthetics.

### 2. Artwork style key: "dark-techno"
**Decision**: Add `"dark-techno"` to `ARTWORK_PROMPTS` dict in main.py.
**Rationale**: Follows the existing pattern (`"abstract"`, `"realistic"`, `"anime"`). The prompt will request industrial warehouse / underground club visuals — concrete, strobes, fog, monochrome with accent lighting. No text, no people.

### 3. Color palette: Deep black + red/magenta neon
**Decision**:
- `bg_color`: [5, 2, 8] (near-black with slight purple tint)
- `title_color`: "#FF1744" (harsh red)
- `title_stroke_color`: "#4A0010" (dark red)
- `waveform_color`: [255, 23, 68] (matching red)
- `particle_color`: [255, 50, 80] (red-pink particles)
- `bg_darken`: 0.7 (darker than lo-fi, more atmosphere)

**Rationale**: Dark techno visuals are dominated by darkness with harsh accent colors. Red/magenta is the canonical color for dark techno — it evokes warehouse strobes and danger.

### 4. Track generation and playlist structure
**Decision**: ~20 tracks generated via Suno AI, BPM range 128-140, curated order following a DJ set arc: ambient intro → building tension → peak energy → breakdown → dark closer.
**Rationale**: Follows the same pattern as all other sessions. Camelot key assignments enable harmonic mixing.

### 5. YouTube metadata as standalone file
**Decision**: Create `output/session 6/youtube.md` following the Session 3 v2 / Session 5 format.
**Rationale**: Established pattern — same structure with genre-appropriate copy and hashtags.

## Risks / Trade-offs

- **[Risk] DALL-E prompt quality for dark techno**: Industrial/warehouse scenes might get repetitive or miss the mark → Mitigation: Prompt includes varied elements (strobes, fog, concrete, steel, cables) and references track name for variety
- **[Risk] Font download availability**: Share Tech Mono must be manually downloaded → Mitigation: It's a free Google Font, widely available. Fallback to Orbitron if needed.
- **[Risk] Track content depends on Suno generation**: Actual track names and characteristics are determined at generation time → Mitigation: session.json can be adjusted after tracks are generated

## Parallelism Considerations

Three fully independent work streams:

1. **Session config + tracks** (`tracks/session 6/session.json`, WAV files, font): Self-contained. No code changes. Can be done by one agent who creates the session directory, downloads font, and writes session.json.

2. **Artwork prompt** (`main.py`): Single addition to `ARTWORK_PROMPTS` dict. No dependencies on session config — just needs the key name `"dark-techno"` agreed upon (defined in proposal).

3. **YouTube metadata** (`output/session 6/youtube.md`): Depends on knowing the final tracklist and total duration. Must wait until session.json is finalized.

**Serialization point**: YouTube metadata (stream 3) depends on session config (stream 1) being complete for accurate tracklist/timestamps. Streams 1 and 2 are fully parallel.
