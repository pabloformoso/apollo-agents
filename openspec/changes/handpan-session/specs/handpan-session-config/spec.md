## ADDED Requirements

### Requirement: Session 8 directory and configuration
The system SHALL have a `tracks/session 8/session.json` file defining Session 8 — "Resonance", a 12-track handpan meditation session.

#### Scenario: Session 8 loaded by CLI
- **WHEN** the user runs `python main.py 8`
- **THEN** the system loads `tracks/session 8/session.json` and processes all 12 tracks in playlist order

### Requirement: Session 8 playlist structure
The session.json playlist SHALL contain exactly 12 entries with the following display names in order: First Resonance, Clay and Rain, Suspended Breath, Kalimba Offering, Temple Drift, Warm Geometry, Root and Overtone, Stone Water, Open Vessel, Amber Frequency, Slow Metal, Last Overtone. Each entry MUST specify `display_name`, `file`, `camelot_key`, and `genre`.

#### Scenario: Playlist order preserved
- **WHEN** Session 8 is processed
- **THEN** tracks play in the defined playlist order from First Resonance through Last Overtone

### Requirement: Session 8 genre values
Each track genre SHALL be one of: `Handpan`, `Handpan Ambient`, or `Handpan Folk`. Tracks 1 and 12 (solo bookends) SHALL use `Handpan`. Tracks 4 and 7 (organic accent) SHALL use `Handpan Folk`. All other tracks SHALL use `Handpan Ambient`.

#### Scenario: Genre metadata correct
- **WHEN** Session 8 artwork is generated
- **THEN** each track's genre value is available for metadata and prompt context

### Requirement: Session 8 organic-zen theme
The session.json SHALL include a `theme` object with: font `fonts/Quicksand-Regular.ttf`, title_color `#D4A574`, title_stroke_color `#5C3D2E`, bg_color `[25, 18, 12]`, waveform_color `[212, 165, 116]`, particle_color `[200, 160, 120]`, bg_darken `0.75`, title_font_size `36`, artwork_style `organic-zen`.

#### Scenario: Theme applied to video rendering
- **WHEN** Session 8 video is rendered
- **THEN** the video uses amber/terracotta title colors, dark warm background, and Quicksand font

### Requirement: Session 8 Camelot key coherence
All tracks SHALL use minor keys (A-column Camelot). Adjacent tracks SHALL differ by at most 2 Camelot steps. The first and last tracks SHALL share the same Camelot key for a circular feel.

#### Scenario: Harmonic crossfades
- **WHEN** the system crossfades between adjacent Session 8 tracks
- **THEN** the key difference is at most 2 Camelot steps, producing harmonically smooth transitions
