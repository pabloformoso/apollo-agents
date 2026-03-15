## Context

The project generates full DJ-mix session videos (1920×1080, 30-60 min) with BPM-matched audio, AI artwork backgrounds, spectral waveform visualizers, and animated titles. Everything runs through a single `main.py` file driven by `session.json` configs. Output lands in `output/session N/mix_video.mp4`.

YouTube Shorts requires vertical 9:16 video (1080×1920), max 60 seconds. We target 20 seconds — punchy enough for discovery, short enough for loop-friendly engagement.

## Goals / Non-Goals

**Goals:**
- Generate a 20-second vertical (1080×1920) teaser clip from an existing session
- Automatically pick the most energetic segment of the mix as the highlight
- Reuse existing artwork, theme, and waveform rendering — adapted to vertical layout
- Add session branding and CTA overlay
- Single CLI flag: `--short`

**Non-Goals:**
- Custom short-specific artwork generation (reuse what exists)
- User-selectable timestamp (auto-detect peak energy; manual override can come later)
- Multi-short generation (one short per session for now)
- Shorts-specific audio processing (no re-mixing, just extract a segment)

## Decisions

### 1. Highlight selection: RMS energy window

**Decision**: Slide a 20-second window across the full mix audio and pick the window with highest average RMS energy.

**Why**: The most energetic 20 seconds will have the best waveform movement and visual appeal. Simple to implement with librosa — no new dependencies.

**Alternatives considered**:
- Random segment — misses the point of a teaser
- First/last 20 seconds — intros and outros are deliberately low-energy
- Beat-density based — similar result to RMS but more complex

### 2. Vertical layout: stacked composition

**Decision**: Top-to-bottom layout on 1080×1920 canvas:
1. **Artwork background** — full-bleed, darkened, Ken Burns (reuse `_ken_burns_frame` adapted to 1080×1920)
2. **Session title** — top area, session name + number
3. **Track artwork** — centered, rounded square (~600×600), the track playing in the highlight
4. **Track name** — below artwork
5. **Waveform** — bottom third, same spectral visualizer adapted to 1080 width
6. **CTA text** — bottom, "▶ Watch full session" with glow

### 3. Audio extraction: segment slice with fade

**Decision**: Extract the 20-second window directly from the final mix WAV (already in `output/session N/mix_output.wav`). Apply 0.5s fade-in and 1s fade-out.

**Why**: The mix WAV already has BPM-matched crossfades applied. No re-processing needed — just slice and fade.

**Prerequisite**: The full mix must already exist. `--short` runs after the main pipeline or reads from cached output.

### 4. Output format

**Decision**: H.264 + AAC in MP4, 1080×1920, 24fps. Output to `output/session N/short.mp4`.

**Why**: Matches YouTube Shorts requirements. Same codec settings as the full video.

### 5. CLI integration

**Decision**: Add `--short` flag to existing `argparse` / CLI. When present, skip full mix generation and only produce the short (assumes mix already exists). Can be combined with full generation in the future.

**Why**: Fast iteration — generating a short from cached audio + artwork takes seconds, not the 30+ minutes of a full pipeline run.

## Risks / Trade-offs

- **[Highlight may fall on a crossfade]** → The RMS peak may land on a transition between tracks. This is actually fine — transitions are musically interesting. The track title shown will be whichever track is dominant at the window midpoint.
- **[Mix must exist first]** → `--short` requires `mix_output.wav` and artwork to already exist. Mitigation: clear error message if files are missing, suggesting to run the full pipeline first.
- **[Vertical waveform narrower]** → 1080px wide vs 1920px in landscape. The waveform window will show less time but the visual density should still look good. Can adjust `WAVEFORM_WINDOW_SEC` for shorts if needed.
