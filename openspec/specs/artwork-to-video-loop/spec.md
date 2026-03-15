## Purpose

Automated generation of loopable video clips from static DALL-E artwork images using Ken Burns animation and ambient overlay effects, enabling sessions without explicit video backgrounds to have animated visuals.

## Requirements

### Requirement: Generate loopable video clips from static artwork
The system SHALL generate short loopable video clips (approximately 10 seconds) from static DALL-E artwork images using subtle animation effects. These clips SHALL be usable by the existing video loop playback infrastructure.

#### Scenario: Video loop generated from artwork
- **WHEN** session has `artwork_style` set to `"realistic"` and no `video_backgrounds` are explicitly listed
- **THEN** the system generates a loopable MP4 video clip for each unique artwork image and stores it alongside the artwork

#### Scenario: Generated clip is loopable
- **WHEN** a generated video clip reaches its end and loops back to the start
- **THEN** there is no visible seam or jump -- the last frame crossfades smoothly into the first frame

### Requirement: Ken Burns animation effect
Each generated video loop SHALL apply a Ken Burns effect (slow zoom and subtle pan) to create gentle motion from the static image.

#### Scenario: Zoom animation
- **WHEN** a video loop plays
- **THEN** the image slowly zooms from 1.0x to approximately 1.05x scale and back (ping-pong) over the loop duration

#### Scenario: Pan animation
- **WHEN** a video loop plays
- **THEN** the image subtly pans (shifts) horizontally or vertically by a few pixels to add motion

### Requirement: Ambient overlay effects
Generated video loops SHALL include subtle ambient overlay effects: floating dust/bokeh particles and gentle brightness modulation simulating light flicker.

#### Scenario: Floating particles visible
- **WHEN** a video loop plays
- **THEN** soft, semi-transparent particles drift slowly across the frame

#### Scenario: Light flicker effect
- **WHEN** a video loop plays
- **THEN** overall brightness oscillates subtly (+/-3%) with a slow period, simulating natural light variation

### Requirement: Video loop output format
Generated video loops SHALL be MP4 files at 1920x1080 resolution, 24fps, suitable for consumption by the existing `_predecode_video_loop` function.

#### Scenario: Output format compatibility
- **WHEN** a generated video loop file is passed to `_predecode_video_loop`
- **THEN** it is successfully decoded into a numpy frame array with seamless loop crossfading applied

### Requirement: Video loop caching
Generated video loops SHALL be cached. If a loop file already exists for a given artwork, generation SHALL be skipped.

#### Scenario: Cached video loop reused
- **WHEN** a video loop file already exists for a track's artwork
- **THEN** generation is skipped and the existing file is used

### Requirement: Auto-populate video_backgrounds from generated loops
When the system generates video loops from artwork, it SHALL automatically set the `video_backgrounds` list at runtime so the existing video background playback pipeline is used.

#### Scenario: Seamless integration with video background system
- **WHEN** video loops have been generated for all unique artworks in a session
- **THEN** the system populates `video_backgrounds` with paths to the generated loops and uses the existing video loop rendering path in `generate_video`

**Primary files**: `main.py` (new function `_generate_video_loop_from_artwork`, integration with `generate_video` around line 995)
