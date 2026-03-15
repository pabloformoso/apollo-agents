## ADDED Requirements

### Requirement: CLI short flag
The system SHALL accept a `--short` CLI flag that triggers generation of a 20-second vertical teaser video for the specified session.

#### Scenario: Generate short for session 4
- **WHEN** user runs `python main.py 4 --short`
- **THEN** the system generates a 20-second vertical video at `output/session 4/short.mp4`

#### Scenario: Missing prerequisite files
- **WHEN** user runs `--short` but `output/session N/mix_output.wav` does not exist
- **THEN** the system exits with an error message indicating the full pipeline must run first

### Requirement: Highlight segment selection
The system SHALL automatically select the 20-second segment with the highest average RMS energy from the full mix audio.

#### Scenario: Peak energy detection
- **WHEN** the system analyzes the mix audio for highlight selection
- **THEN** it selects the 20-second window with maximum average RMS energy as the highlight segment

#### Scenario: Segment extraction with fades
- **WHEN** a highlight segment is selected
- **THEN** the system extracts that segment with a 0.5-second fade-in and 1.0-second fade-out

### Requirement: Vertical video format
The system SHALL render the short as a 1080×1920 (9:16) vertical video at 24fps.

#### Scenario: Output dimensions
- **WHEN** the short video is rendered
- **THEN** the output file is 1080 pixels wide and 1920 pixels tall

#### Scenario: Output codec
- **WHEN** the short video is encoded
- **THEN** it uses H.264 video codec and AAC audio codec in MP4 container

### Requirement: Vertical layout composition
The system SHALL compose the vertical frame with artwork background, track artwork, track title, waveform visualizer, and CTA overlay.

#### Scenario: Artwork background
- **WHEN** a frame is rendered
- **THEN** the track's artwork image fills the background using cover-crop scaling to 1080×1920 (no black/white borders), with Ken Burns animation and brightness matching the session's `bg_darken` theme setting

#### Scenario: Track artwork display
- **WHEN** a frame is rendered
- **THEN** the current track's artwork is displayed as a centered square image in the upper-middle area of the frame

#### Scenario: Track title display
- **WHEN** a frame is rendered
- **THEN** the current track name is displayed below the artwork square using the session's theme font and colors

#### Scenario: Waveform visualizer
- **WHEN** a frame is rendered
- **THEN** a spectral waveform visualizer (adapted to 1080px width) is displayed in the lower portion of the frame

#### Scenario: CTA overlay
- **WHEN** a frame is rendered
- **THEN** a "Watch full session" text overlay is displayed at the bottom of the frame

### Requirement: Session branding
The system SHALL display the session name at the top of the vertical frame.

#### Scenario: Session title display
- **WHEN** a frame is rendered
- **THEN** the session name from `session.json` (e.g., "Session 4 — LoFi Study") is displayed at the top of the frame using the session's theme styling

### Requirement: Artwork reuse
The system SHALL reuse existing per-track artwork from `artwork/session N/` without generating new images.

#### Scenario: Existing artwork used
- **WHEN** generating the short video
- **THEN** the system reads artwork from `artwork/session N/<track_name>.png` for the track playing during the highlight segment

#### Scenario: No artwork available
- **WHEN** no artwork PNG exists for the highlight track
- **THEN** the system uses the session's background color as a solid fill instead

### Requirement: Output path
The system SHALL write the short video to `output/session N/short.mp4`.

#### Scenario: Output file location
- **WHEN** the short generation completes for session 4
- **THEN** the file exists at `output/session 4/short.mp4`
