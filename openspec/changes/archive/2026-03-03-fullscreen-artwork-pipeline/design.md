## Context

The Deep Session Generator renders 1080p mix videos with AI-generated artwork backgrounds. Currently, artwork is loaded at `1920×1080`, blurred with radius 12, and darkened to 25% brightness (`ARTWORK_DARKEN_FACTOR = 0.25`). This makes the artwork nearly invisible — just a dark tinted background. The user wants artwork to be the dominant visual element at ~85% brightness with no blur, filling the entire frame edge-to-edge.

Key current flow:
1. DALL-E 3 generates artwork at `1792×1024` (closest 16:9 option)
2. `_generate_artwork` resizes to exactly `1920×1080` via `Image.resize` (may distort slightly)
3. `_load_artwork_images` re-loads, resizes again, blurs, darkens to 25%
4. `_get_artwork_frame` composites the darkened artwork as background
5. Waveform, particles, and titles overlay on top

Session 5 has 20 WAV tracks with no `session.json`, matching Session 4's LoFi aesthetic.

## Goals / Non-Goals

**Goals:**
- Artwork fills 100% of the 1920×1080 frame with zero black/white borders
- Artwork visible at ~85% brightness (configurable per session via `bg_darken`)
- Remove heavy Gaussian blur so artwork detail is visible (keep very light blur or none)
- Overlay elements (waveform, titles, particles) remain readable against bright artwork
- Session 5 fully configured with curated playlist and LoFi theme
- YouTube Short also uses fullscreen artwork with proper cover-crop

**Non-Goals:**
- Changing the DALL-E prompt or art style system
- Modifying the audio pipeline (BPM matching, crossfades, etc.)
- Adding new visual effects or overlays
- Changing the video background loop system (only static artwork path affected)

## Decisions

### 1. Cover-crop scaling for artwork (not stretch-to-fit)

**Decision**: Use cover-crop (scale to fill + center-crop) instead of `Image.resize` which stretches.

**Rationale**: The DALL-E output is 1792×1024 (1.75:1) but the video is 1920×1080 (1.778:1). Direct resize introduces subtle horizontal stretching. Cover-crop preserves aspect ratio and guarantees full coverage.

**Alternative rejected**: Letterbox/pillarbox — explicitly unwanted by user (no borders).

**Implementation**: New `_cover_crop` helper:
```python
def _cover_crop(img, target_w, target_h):
    """Scale image to cover target dimensions, then center-crop."""
    w, h = img.size
    scale = max(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))
```

### 2. Brightness model: 85% default, per-session override

**Decision**: Change `ARTWORK_DARKEN_FACTOR` from 0.25 to 0.85. Sessions can override via `theme.bg_darken`.

**Rationale**: Session 4 already has `"bg_darken": 0.75` in its theme. The constant serves as the default for sessions without a theme. Setting it to 0.85 matches the user's request. Session-specific overrides continue to work.

### 3. Reduce blur to subtle softening

**Decision**: Reduce `ARTWORK_BLUR_RADIUS` from 12 to 2 (very light softening to hide DALL-E compression artifacts, but preserve artwork detail).

**Alternative considered**: Remove blur entirely (radius 0). Kept minimal blur because DALL-E outputs can have minor artifacts that a radius-2 blur hides without losing visible detail.

### 4. Overlay readability against bright backgrounds

**Decision**: Add a semi-transparent dark gradient strip behind the waveform region and use text shadow/stroke for titles.

**Rationale**: At 85% brightness, the existing white/colored overlays may lose contrast. The waveform already has spectral coloring. Adding a localized darkened strip (not full-frame) behind the waveform preserves artwork visibility while keeping the visualizer readable. Titles already have stroke outlines which should suffice.

**Implementation**: In `make_frame`, after artwork background but before waveform, apply a gradient darkening to the waveform region only (bottom ~250px of frame).

### 5. Session 5 configuration

**Decision**: Create `session.json` modeled on Session 4's structure with anime artwork style, warm LoFi theme, and curated track order.

**Rationale**: Session 5 has the same track set as Session 4 plus new tracks. Needs Camelot key assignments and genre tags for the playlist system.

## Risks / Trade-offs

- **[Visual regression on existing sessions]** → Sessions without `bg_darken` in theme will now show artwork at 85% instead of 25%. This is the intended behavior. Sessions with explicit `bg_darken` (Session 4 at 0.75) are unaffected.
- **[Waveform readability]** → Brighter backgrounds may wash out waveform colors. Mitigated by gradient strip behind waveform area.
- **[Ken Burns crop edge visibility]** → With clearer artwork, the Ken Burns pan/zoom boundaries may become more noticeable. The existing 5% zoom range and 5px pan are subtle enough to not cause visible edge issues since artwork is cover-cropped with headroom.

## Parallelism Considerations

Three independent work streams:

1. **Agent A — Artwork pipeline** (`main.py` constants + `_cover_crop` + `_load_artwork_images` + `_generate_artwork`): Core scaling/brightness changes. No dependencies on other agents.

2. **Agent B — Overlay readability** (`main.py` `make_frame` + waveform region gradient + Ken Burns): Depends on Agent A's brightness constant changes being defined (interface: `ARTWORK_DARKEN_FACTOR = 0.85`, `ARTWORK_BLUR_RADIUS = 2`). Can work in parallel once constants are agreed.

3. **Agent C — Session 5 config** (`tracks/session 5/session.json`): Completely independent — no code changes, just a new JSON file.

**Serialization point**: Agent B's waveform gradient work should be tested after Agent A's brightness changes are in, since the gradient intensity depends on how bright the background actually is.

**Shared contract**: The `_cover_crop` function signature and behavior must be defined before Agents A and B start, since both the main video and Short pipelines use it.
