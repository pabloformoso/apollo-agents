## Purpose

Session 6 playlist configuration for a dark techno session with industrial theme, curated track ordering, and dark visual parameters.

## Requirements

### Requirement: Session 6 directory and session.json
The system SHALL include a `tracks/session 6/` directory containing a `session.json` file that defines a dark techno playlist with approximately 20 tracks.

#### Scenario: Valid session 6 configuration
- **WHEN** `python main.py 6` is executed
- **THEN** the system loads `tracks/session 6/session.json` and processes all listed tracks in playlist order

#### Scenario: Session.json structure
- **WHEN** session.json for session 6 is parsed
- **THEN** it contains `name`, `description`, `theme`, and `playlist` fields consistent with sessions 4-5

### Requirement: Dark techno playlist entries
Each playlist entry SHALL include `display_name`, `file` (relative path to WAV), `camelot_key`, and `genre` fields. All genre values SHALL be dark techno sub-genres (e.g., "Dark Techno", "Industrial Techno", "Acid Techno", "Hard Techno").

#### Scenario: Track entry structure
- **WHEN** a playlist entry is read from session 6's session.json
- **THEN** it contains all required fields: display_name (string), file (string path to WAV), camelot_key (Camelot notation), genre (string)

#### Scenario: Audio files exist
- **WHEN** session 6 is loaded
- **THEN** every `file` path in the playlist resolves to an existing WAV audio file

### Requirement: Dark techno playlist order
The playlist SHALL follow a DJ set arc: ambient/atmospheric intro → building tension → peak energy dark techno → breakdown → dark atmospheric closer.

#### Scenario: Flow progression
- **WHEN** the playlist is played in order
- **THEN** the opening tracks are atmospheric/ambient, mid-session tracks have maximum energy and BPM, and closing tracks wind down to a dark atmospheric finish

### Requirement: Dark techno theme configuration
Session 6's session.json SHALL include a `theme` block with dark industrial visual parameters.

#### Scenario: Theme values
- **WHEN** session 6's theme is loaded
- **THEN** it specifies: font as `"fonts/ShareTechMono-Regular.ttf"`, artwork_style as `"dark-techno"`, title_color as a harsh red/magenta neon, bg_color as near-black, and bg_darken as 0.7

#### Scenario: Theme integrates with existing system
- **WHEN** session 6's theme is merged via `_get_session_theme()`
- **THEN** all theme values override defaults and are applied throughout the video rendering pipeline

### Requirement: Industrial font file
The project SHALL include `fonts/ShareTechMono-Regular.ttf` for the dark techno session title rendering.

#### Scenario: Font file exists
- **WHEN** session 6 is processed
- **THEN** `fonts/ShareTechMono-Regular.ttf` exists and is a valid TrueType font

**Primary files**: `tracks/session 6/session.json` (new), `fonts/ShareTechMono-Regular.ttf` (new)
