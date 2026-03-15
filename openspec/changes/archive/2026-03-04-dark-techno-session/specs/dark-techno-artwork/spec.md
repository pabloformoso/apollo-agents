## ADDED Requirements

### Requirement: Dark techno artwork prompt template
The `ARTWORK_PROMPTS` dict in main.py SHALL include a `"dark-techno"` key with a DALL-E 3 prompt template for industrial/underground visuals.

#### Scenario: Dark techno artwork generation
- **WHEN** session theme has `artwork_style` set to `"dark-techno"` and artwork is generated for a track
- **THEN** DALL-E 3 is called with a prompt requesting an industrial/underground scene — concrete warehouse, steel beams, fog, strobes, cables, monochrome with red/magenta accent lighting — inspired by the track name

#### Scenario: Prompt includes track name
- **WHEN** artwork is generated for a track named "Warehouse Protocol"
- **THEN** the prompt incorporates `{track_name}` to vary the visual composition per track

### Requirement: Dark techno artwork visual characteristics
Dark techno artwork SHALL depict industrial/underground environments with dark, moody atmosphere. Images SHALL have no text and no people.

#### Scenario: Industrial elements present
- **WHEN** a dark-techno artwork image is generated
- **THEN** the image depicts industrial elements such as concrete walls, steel structures, fog/smoke, laser strobes, or underground tunnel aesthetics

#### Scenario: No text or people in artwork
- **WHEN** a dark-techno artwork image is generated
- **THEN** the prompt explicitly excludes text and people to ensure clean backgrounds for video overlay

### Requirement: Artwork caching applies to dark-techno style
The existing artwork caching (skip if `artwork_dir/track_name.png` exists) SHALL work identically for dark-techno-style artwork.

#### Scenario: Cached dark-techno artwork reused
- **WHEN** `artwork/session 6/track_name.png` already exists
- **THEN** generation is skipped and the cached file is used

**Primary files**: `main.py` (`ARTWORK_PROMPTS` dict, ~line 82-101)
