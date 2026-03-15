## MODIFIED Requirements

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

**Primary files**: `main.py` — functions `generate_short`, `_render_short_frame`, `_short_ken_burns_frame`
