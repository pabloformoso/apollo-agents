## ADDED Requirements

### Requirement: organic-zen artwork prompt template
The system SHALL include an `organic-zen` key in `ARTWORK_PROMPTS` that generates warm, painterly, earth-toned landscape artwork via DALL-E 3. The prompt MUST include `{track_name}` for per-track variation. The prompt MUST request no text and no people. The prompt MUST emphasize oil-paint texture, earth tones (amber, sienna, sage green, sandstone), and golden-hour lighting.

#### Scenario: Artwork generated with organic-zen style
- **WHEN** a session with `artwork_style: "organic-zen"` is processed
- **THEN** the system uses the `organic-zen` prompt template from `ARTWORK_PROMPTS` to generate artwork via DALL-E 3 with `{track_name}` interpolated

#### Scenario: Fallback for unknown style
- **WHEN** a session references an `artwork_style` not present in `ARTWORK_PROMPTS`
- **THEN** the system falls back to the `abstract` prompt template (existing behavior, unchanged)
