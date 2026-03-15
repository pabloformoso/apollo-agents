## Context

The deep_session_gen project produces automated DJ mixes with 1080p video. Sessions 1-3 use synthwave/cyberpunk aesthetics — retro pixel fonts (Press Start 2P), neon green (#00FF88) titles, abstract DALL-E artwork, and beat-reactive particle visualizers. Session 3 v2 introduced video loop backgrounds loaded from pre-existing MP4 files in `vids/`.

The current pipeline: load tracks from `tracks/session N/` → BPM-match & crossfade audio → generate DALL-E artwork per track → composite video (background + particles + waveform + titles) → export MP4.

We need to add a LoFi study session (~120 min) with a fundamentally different visual identity: realistic cosy room scenes, warm muted colors, loopable video backgrounds generated from artwork, and a calm sans-serif font.

## Goals / Non-Goals

**Goals:**
- Create session 4 with ~120 minutes of LoFi tracks and curated playlist order
- Generate realistic cosy room artwork via DALL-E 3 (photographic/realistic style)
- Convert static artwork into loopable video clips with subtle ambient animation (parallax, particles, light flicker)
- Allow per-session visual theming (font, colors, overlay opacity, waveform style)
- Ensure video loops are seamless for 2-hour continuous playback

**Non-Goals:**
- AI music generation (tracks are sourced externally, as with all sessions)
- Real-time rendering or streaming — this remains a batch offline pipeline
- Changing the existing sessions' aesthetics — sessions 1-3 keep their retro look
- Complex 3D animation or camera movement in video loops
- Multi-resolution output (stays 1080p)

## Decisions

### D1: Per-session theme via session.json `theme` block

**Decision**: Add an optional `theme` object to `session.json` that overrides visual defaults.

```json
{
  "theme": {
    "font": "fonts/Quicksand-Regular.ttf",
    "title_color": "#E8D5B7",
    "title_stroke_color": "#5C4A32",
    "bg_color": [18, 15, 12],
    "waveform_color": [180, 160, 130],
    "particle_color": [200, 180, 150],
    "bg_darken": 0.45,
    "title_font_size": 36,
    "artwork_style": "realistic"
  }
}
```

**Rationale**: Keeps all session configuration in one place. No code branching by session number — the theme object drives visual decisions. Existing sessions without a `theme` block get current defaults (backward compatible).

**Alternative considered**: Separate theme YAML files — rejected because it fragments session config and adds file management overhead for minimal benefit.

### D2: Artwork style prompts driven by `artwork_style` field

**Decision**: The `artwork_style` field in theme config selects a prompt template:
- `"abstract"` (default): Current prompt — "Abstract digital artwork inspired by..."
- `"realistic"`: New prompt — "Photorealistic cosy room scene, warm ambient lighting, {track_name} mood, study desk with books, warm lamp, rain on window, plants, soft shadows. Shot on Canon 5D, 35mm lens. No text, no people."

**Rationale**: Prompt engineering is the primary lever for DALL-E style control. A named style maps to a curated prompt template, keeping the code clean.

### D3: Video loop generation from static artwork using MoviePy transforms

**Decision**: Generate loopable video clips by applying subtle MoviePy/numpy transforms to DALL-E artwork:
1. **Ken Burns effect**: Slow zoom (1.0→1.05 over 10s) + slight pan, reversed to create a ping-pong loop
2. **Ambient particles**: Floating dust motes / bokeh lights overlay (reuse existing particle system with softer params)
3. **Light flicker**: Subtle periodic brightness modulation (sine wave, ±3%)
4. **Composition**: Layer these effects, render to 10-second MP4 clips, then use existing `_predecode_video_loop` for seamless looping

**Rationale**: Avoids new dependencies. MoviePy + numpy can handle these transforms. The existing video loop infrastructure (Session 3 v2) already handles seamless crossfading and pre-decoding. We generate the source clips rather than requiring external video files.

**Alternative considered**: Using an AI video generation API (Runway, Pika) — rejected due to cost, latency, and quality unpredictability for 2-hour sessions needing many clips. Also adds external dependency.

### D4: Warm font for LoFi sessions

**Decision**: Bundle Quicksand (Google Fonts, OFL license) as the LoFi font at `fonts/Quicksand-Regular.ttf`. Warm, rounded, highly legible — fits the cosy study aesthetic.

**Rationale**: Press Start 2P is perfect for retro but wrong for LoFi. Quicksand is free, lightweight, and reads well at video resolution.

### D5: Session 4 track structure

**Decision**: ~20 LoFi tracks at 5-7 minutes each for ~120 minutes total. Session.json with same structure as session 2/3 — display_name, file, camelot_key, genre. WAV format.

**Rationale**: Consistent with existing session format. The BPM-matching and crossfade pipeline works unchanged.

## Risks / Trade-offs

- **[Ken Burns loop seam]** → Mitigation: Use ping-pong (zoom in then out) so start and end frames match. Apply crossfade at loop boundary via existing `_predecode_video_loop`.
- **[DALL-E realistic consistency]** → Mitigation: Use detailed prompt with specific visual anchors (desk, lamp, rain, plants). Generate multiple and curate. Seed parameter for consistency across tracks.
- **[Memory usage for 120-min video]** → Mitigation: Video loops are pre-decoded into numpy arrays (existing pattern). Each 10s loop at 1080p/24fps ≈ 500MB. With 10-15 unique loops in memory simultaneously, this is manageable (~5-7GB peak).
- **[Font licensing]** → Mitigation: Quicksand is OFL-licensed, free for all uses including YouTube.

## Parallelism Considerations

Four naturally isolated workstreams:

1. **Session config + track setup** (`lofi-session-config`): Create `tracks/session 4/session.json`, source/place audio files. No code changes in main.py. Independent.

2. **Artwork generation** (`realistic-artwork-gen`): Modify `_generate_artwork()` to branch on `artwork_style` theme config. Touches artwork prompt logic only. Can be built independently once the theme config structure (D1) is agreed.

3. **Video loop pipeline** (`artwork-to-video-loop`): New function `_generate_video_loop_from_artwork()`. Depends on artwork files existing but not on the generation code — can work with test images. Produces MP4 clips consumed by existing `_predecode_video_loop`.

4. **Visual theming** (`session-visual-theme`): Modify `generate_video()` to read theme config and apply font/color/opacity overrides. Touches the video rendering pipeline. Independent from artwork generation.

**Shared contract**: The `theme` block schema in session.json (D1) must be defined before agents 2, 3, and 4 start. This is a serialization point — define the schema first in the session config task, then parallelize the rest.

**Serialization points**:
- Session config (theme schema) must be defined before artwork/video/theme work begins
- Artwork generation must produce at least one test image before video loop pipeline can be integration-tested

## Open Questions

- What specific LoFi tracks will be used? (User needs to source these — outside of code scope)
- Should the waveform visualizer be toned down for LoFi (smaller, less reactive) or kept the same?
