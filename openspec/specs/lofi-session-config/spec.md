## Purpose

Session configuration support for LoFi-style sessions, including session directory structure, playlist metadata, duration targets, and an optional theme configuration block in session.json for visual customization.

## Requirements

### Requirement: Session 4 directory and session.json
The system SHALL support a `tracks/session 4/` directory containing a `session.json` file that defines a LoFi study/work playlist of approximately 120 minutes total duration.

#### Scenario: Valid session 4 configuration
- **WHEN** `python main.py 4` is executed
- **THEN** the system loads `tracks/session 4/session.json` and processes all listed tracks in playlist order

#### Scenario: Session.json structure matches existing format
- **WHEN** session.json for session 4 is parsed
- **THEN** it contains `name`, `description`, `playlist` array, and optionally `video_backgrounds` and `theme` fields

### Requirement: LoFi playlist entries with standard metadata
Each playlist entry in session 4 SHALL include `display_name`, `file` (relative path to WAV), `camelot_key`, and `genre` fields, consistent with session 2/3 format.

#### Scenario: Track entry structure
- **WHEN** a playlist entry is read from session 4's session.json
- **THEN** it contains all required fields: display_name (string), file (string path to WAV), camelot_key (string, Camelot notation), genre (string)

#### Scenario: Audio files exist
- **WHEN** session 4 is loaded
- **THEN** every `file` path in the playlist resolves to an existing WAV audio file

### Requirement: Session 4 targets approximately 120 minutes
The session 4 playlist SHALL contain enough tracks to produce a mix of approximately 120 minutes (+/-10 minutes after crossfading).

#### Scenario: Duration range
- **WHEN** all session 4 tracks are mixed with crossfades
- **THEN** the total mix duration is between 110 and 130 minutes

### Requirement: Theme configuration block in session.json
Session.json SHALL support an optional `theme` object that overrides default visual settings. Sessions without a `theme` block SHALL use existing defaults (backward compatible).

#### Scenario: Theme block present
- **WHEN** session.json contains a `theme` object
- **THEN** the system uses theme values for font, title_color, title_stroke_color, bg_color, waveform_color, particle_color, bg_darken, title_font_size, and artwork_style

#### Scenario: Theme block absent (backward compatibility)
- **WHEN** session.json does not contain a `theme` object
- **THEN** the system uses existing hardcoded defaults (Press Start 2P font, neon green, etc.)

**Primary files**: `tracks/session 4/session.json`, `main.py` (session loading logic around line 850-900)
