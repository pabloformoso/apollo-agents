## Purpose

Fullscreen artwork pipeline for video generation: cover-crop scaling to eliminate borders, configurable brightness, minimal blur, waveform contrast gradient, and Ken Burns animation on cover-cropped source.

## Requirements

### Requirement: Cover-crop scaling for artwork
The system SHALL scale artwork images using a cover-crop algorithm that fills the entire target frame (1920x1080) with zero black or white borders, preserving the image's original aspect ratio.

#### Scenario: DALL-E artwork at 1792x1024
- **WHEN** artwork generated at 1792x1024 is loaded for video background
- **THEN** the image is scaled up to cover 1920x1080 and center-cropped, with no letterboxing or pillarboxing

#### Scenario: Square artwork input
- **WHEN** artwork with a 1:1 aspect ratio is loaded
- **THEN** the image is scaled to cover the full 1920x1080 frame (cropping top/bottom excess) with no borders

#### Scenario: Artwork wider than 16:9
- **WHEN** artwork with aspect ratio wider than 16:9 is loaded
- **THEN** the image is scaled to match frame height and horizontally center-cropped

### Requirement: Artwork brightness at 85%
The system SHALL display artwork backgrounds at 85% brightness by default, making the artwork the dominant visual element.

#### Scenario: Default brightness
- **WHEN** a session has no `bg_darken` theme override
- **THEN** artwork background is displayed at 85% of original brightness (`ARTWORK_DARKEN_FACTOR = 0.85`)

#### Scenario: Per-session override
- **WHEN** a session's `session.json` specifies `theme.bg_darken` (e.g., 0.75)
- **THEN** that session's artwork uses the specified brightness value instead of the default

### Requirement: Minimal artwork blur
The system SHALL apply minimal or no Gaussian blur to artwork backgrounds so that artwork detail remains clearly visible.

#### Scenario: Reduced blur
- **WHEN** artwork is loaded for background compositing
- **THEN** Gaussian blur radius is 2 or less (down from 12)

### Requirement: Waveform region contrast
The system SHALL apply a localized semi-transparent dark gradient behind the waveform visualizer area to maintain readability against bright artwork backgrounds.

#### Scenario: Gradient behind waveform
- **WHEN** a video frame is composed with bright artwork background
- **THEN** a dark gradient overlay is applied to the bottom portion of the frame (waveform region) before drawing the waveform

#### Scenario: Gradient does not obscure artwork
- **WHEN** the gradient is applied
- **THEN** the gradient only affects the bottom ~250px of the frame, leaving the upper artwork fully visible at configured brightness

### Requirement: Ken Burns uses cover-cropped source
The Ken Burns animation SHALL operate on artwork that has been cover-cropped with 10% headroom, ensuring no frame edges are visible during pan/zoom.

#### Scenario: Ken Burns headroom
- **WHEN** artwork is prepared for Ken Burns animation
- **THEN** the source image is cover-cropped to 110% of target dimensions before the animation begins

**Primary files**: `main.py` — functions `_cover_crop` (new), `_load_artwork_images`, `_generate_artwork`, `_ken_burns_frame`, `generate_video` (make_frame), constants `ARTWORK_DARKEN_FACTOR`, `ARTWORK_BLUR_RADIUS`
