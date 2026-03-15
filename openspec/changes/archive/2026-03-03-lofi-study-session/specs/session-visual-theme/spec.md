## ADDED Requirements

### Requirement: Theme-driven font selection
The video rendering pipeline SHALL use the font specified in the session's `theme.font` field. When no theme font is specified, it SHALL fall back to the existing Press Start 2P font.

#### Scenario: Custom font from theme
- **WHEN** session theme specifies `"font": "fonts/Quicksand-Regular.ttf"`
- **THEN** video title text renders using Quicksand font

#### Scenario: Default font fallback
- **WHEN** session has no theme or theme has no `font` field
- **THEN** video title text renders using Press Start 2P (existing default)

### Requirement: Theme-driven title colors
The video rendering pipeline SHALL use `theme.title_color` and `theme.title_stroke_color` for title text rendering. Defaults to neon green (#00FF88) and dark green (#004422) when not specified.

#### Scenario: Warm LoFi title colors
- **WHEN** session theme specifies `"title_color": "#E8D5B7"` and `"title_stroke_color": "#5C4A32"`
- **THEN** title text renders in warm beige with brown stroke

#### Scenario: Default neon colors
- **WHEN** session has no theme color overrides
- **THEN** title text renders with existing neon green palette

### Requirement: Theme-driven background color
The video rendering pipeline SHALL use `theme.bg_color` (RGB array) as the base background color. Defaults to [8, 8, 14] when not specified.

#### Scenario: Warm background color
- **WHEN** session theme specifies `"bg_color": [18, 15, 12]`
- **THEN** video background base color is warm dark brown instead of blue-black

### Requirement: Theme-driven particle and waveform colors
The particle system SHALL use `theme.particle_color` and the waveform visualizer SHALL use `theme.waveform_color` from the session theme. Both fall back to existing defaults when not specified.

#### Scenario: Warm particle colors
- **WHEN** session theme specifies `"particle_color": [200, 180, 150]`
- **THEN** particles render in warm amber tones instead of cool blue-white

#### Scenario: Warm waveform colors
- **WHEN** session theme specifies `"waveform_color": [180, 160, 130]`
- **THEN** waveform bars and envelope render in warm muted tones

### Requirement: Theme-driven background darken factor
The video background overlay opacity SHALL use `theme.bg_darken` when specified. Defaults to existing VIDEO_BG_DARKEN (0.35) when not set.

#### Scenario: Custom darken factor
- **WHEN** session theme specifies `"bg_darken": 0.45`
- **THEN** video backgrounds are darkened to 45% brightness for better text readability

### Requirement: Theme-driven title font size
The title font size SHALL use `theme.title_font_size` when specified. Defaults to existing TITLE_FONT_SIZE (32) when not set.

#### Scenario: Custom font size
- **WHEN** session theme specifies `"title_font_size": 36`
- **THEN** title text renders at 36px

### Requirement: All theme fields are optional
Every field in the `theme` object SHALL be individually optional. The system SHALL merge provided theme values with defaults, allowing partial theme overrides.

#### Scenario: Partial theme override
- **WHEN** session theme only specifies `"font"` and `"title_color"` but no other fields
- **THEN** the specified font and title_color are used, all other visual settings use existing defaults

**Primary files**: `main.py` (`generate_video` function ~line 995, title rendering, particle system, waveform visualizer)
