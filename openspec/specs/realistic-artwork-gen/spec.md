## Purpose

Artwork style selection system that supports generating photorealistic cosy room artwork via DALL-E 3 as an alternative to the default abstract style, driven by the session theme configuration.

## Requirements

### Requirement: Artwork style selection based on theme config
The artwork generation system SHALL select a prompt template based on the `artwork_style` field in the session's theme configuration. When `artwork_style` is `"realistic"`, DALL-E 3 SHALL be called with a photorealistic cosy room prompt instead of the default abstract prompt.

#### Scenario: Realistic artwork generation
- **WHEN** session theme has `artwork_style` set to `"realistic"` and artwork is generated for a track
- **THEN** DALL-E 3 is called with a prompt requesting a photorealistic cosy room scene with warm ambient lighting, study desk, books, warm lamp, rain on window, plants, and soft shadows -- inspired by the track name

#### Scenario: Default abstract artwork (no artwork_style or "abstract")
- **WHEN** session theme has no `artwork_style` or it is set to `"abstract"`
- **THEN** DALL-E 3 is called with the existing abstract digital artwork prompt

### Requirement: Realistic artwork visual characteristics
Realistic artwork SHALL depict a cosy indoor study environment with warm lighting. The generated images SHALL have no text and no people.

#### Scenario: Cosy room elements present
- **WHEN** a realistic artwork image is generated
- **THEN** the image depicts indoor elements such as a desk, warm lamp, books, plants, or window with ambient lighting

#### Scenario: No text or people in artwork
- **WHEN** a realistic artwork image is generated
- **THEN** the prompt explicitly excludes text and people to ensure clean backgrounds for video overlay

### Requirement: Artwork caching applies to realistic style
The existing artwork caching (skip if `artwork_dir/track_name.png` exists) SHALL work identically for realistic-style artwork.

#### Scenario: Cached realistic artwork reused
- **WHEN** `artwork/session 4/track_name.png` already exists
- **THEN** generation is skipped and the cached file is used

### Requirement: Artwork deduplication by display_name
Tracks sharing the same `display_name` SHALL share artwork, regardless of artwork style.

#### Scenario: Duplicate display_name shares artwork
- **WHEN** two playlist entries have the same `display_name`
- **THEN** only one artwork image is generated and both entries use it

**Primary files**: `main.py` (`_generate_artwork` function, ~line 783)
