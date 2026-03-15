## Context

The project generates DJ-style mix videos from curated track sessions. Each session defines a playlist, theme, and artwork style in `session.json`. The `ARTWORK_PROMPTS` dict in `main.py` maps style names to DALL-E 3 prompt templates. Adding a new session requires: (1) a new artwork prompt if the style doesn't exist, and (2) a new session directory with `session.json` and audio files.

Current artwork styles: `abstract`, `realistic`, `anime`, `dystopic-calm`, `dark-techno`.

## Goals / Non-Goals

**Goals:**
- Add `organic-zen` artwork style that produces warm, painterly, earth-toned DALL-E images
- Define Session 8 ("Resonance") with a 12-track handpan meditation playlist
- Maintain visual and tonal consistency across all 12 generated artworks

**Non-Goals:**
- No changes to the video rendering pipeline, crossfade logic, or BPM matching
- No new fonts — reuse Quicksand (already used in lo-fi sessions)
- No video background loops for this session (static artwork only)
- No changes to the theme system itself

## Decisions

### 1. Artwork prompt wording

Use "warm painterly landscape" + "oil paint on rough canvas" to push DALL-E toward textured, non-photographic output. Include "no sharp geometry" to avoid DALL-E's tendency toward mandalas/sacred geometry when it sees meditation-adjacent prompts.

**Alternatives considered:**
- Photorealistic style (like `realistic`) — too cold, doesn't match handpan warmth
- Watercolor style — tested poorly with DALL-E 3, tends toward washed-out results
- Sacred geometry / mandala focus — too literal, risks visual monotony across 12 tracks

### 2. Camelot key selection

Use minor keys only (A-column on Camelot wheel) for the meditative quality. Keep adjacent keys (max ±2 steps) for smooth crossfade harmony. Start and end on the same key for circular feel.

### 3. BPM range 75-85

Narrow BPM range avoids aggressive time-stretching during crossfades. The pipeline's BPM matching will only need minor adjustments (~10% max), preserving handpan timbre.

### 4. Genre field values

Use `Handpan`, `Handpan Ambient`, and `Handpan Folk` — descriptive for YouTube metadata without overcomplicating.

## Risks / Trade-offs

- **[DALL-E consistency]** Earth-tone painterly prompts may produce visually similar images across tracks → Mitigation: `{track_name}` interpolation provides per-track variation (desert vs forest vs terracotta)
- **[Suno handpan quality]** AI-generated handpan audio may have artifacts or add unwanted drums → Mitigation: user generates and curates tracks before running the pipeline; not a code concern
- **[Narrow BPM range]** All tracks at ~80 BPM means crossfades are smooth but the mix may feel static → Mitigation: this is intentional (plateau design); variety comes from texture, not tempo
