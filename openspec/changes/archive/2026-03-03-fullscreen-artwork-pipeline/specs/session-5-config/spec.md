## ADDED Requirements

### Requirement: Session 5 playlist configuration
The system SHALL include a `tracks/session 5/session.json` file that defines a curated LoFi study playlist with all 20 tracks in the session directory.

#### Scenario: Valid session.json exists
- **WHEN** the user runs `python main.py 5`
- **THEN** the system loads `tracks/session 5/session.json` and processes all 20 tracks in playlist order

#### Scenario: All tracks referenced
- **WHEN** `session.json` is parsed
- **THEN** every `.wav` file in `tracks/session 5/` has a corresponding playlist entry with `display_name`, `file`, `camelot_key`, and `genre` fields

### Requirement: Session 5 theme matches LoFi aesthetic
The session configuration SHALL include a theme block with anime artwork style, warm earth-tone colors, and the Quicksand font — matching Session 4's LoFi study aesthetic.

#### Scenario: Theme configuration
- **WHEN** Session 5's theme is loaded
- **THEN** `artwork_style` is `"anime"`, font is `"fonts/Quicksand-Regular.ttf"`, and colors use warm earth tones (similar palette to Session 4)

#### Scenario: Background brightness
- **WHEN** Session 5's theme is applied during video generation
- **THEN** `bg_darken` is set to 0.85 so artwork is prominently visible

### Requirement: Curated track ordering
The playlist SHALL order tracks to create a smooth listening flow: ambient opener → gentle builds → mid-session energy → warm wind-down → ambient closer.

#### Scenario: Flow progression
- **WHEN** the playlist is played in order
- **THEN** the first and last tracks are ambient/gentle, and mid-playlist tracks have more rhythmic energy

### Requirement: Session metadata
The session configuration SHALL include a descriptive name and description for the session.

#### Scenario: Session identity
- **WHEN** session metadata is read
- **THEN** the `name` field contains "Session 5 — LoFi Study II" and `description` describes the session's character

**Primary files**: `tracks/session 5/session.json` (new file only, no code changes)
