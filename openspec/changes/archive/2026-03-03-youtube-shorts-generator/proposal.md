## Why

YouTube Shorts (vertical 9:16, ≤60s) are the primary discovery channel on YouTube. Each full session mix is 30-60 minutes long but has no short-form teaser to drive views. A 20-second clip with visuals, waveform, and a "full session" call-to-action would let us promote each session on Shorts/Reels/TikTok with zero manual editing.

## What Changes

- New CLI command: `python main.py <session_number> --short` generates a 20-second vertical (1080×1920) clip from the session
- Automatically selects a highlight segment from the mix (peak energy window)
- Renders vertical-format video with artwork background, waveform visualizer, track title, and session branding
- Adds a "Watch full session" text overlay as a call-to-action
- Outputs to `output/session N/short.mp4`

## Capabilities

### New Capabilities
- `youtube-short`: Generation of a 20-second vertical-format teaser video from a session, including highlight selection, vertical layout rendering, and CTA overlay

### Modified Capabilities
_None — the existing full-mix pipeline is unchanged. The short generator reads the same session config and reuses existing artwork/audio but renders independently._

## Impact

- **Code**: New functions in `main.py` for highlight detection, vertical frame rendering, and short export. New CLI flag `--short`.
- **Dependencies**: No new dependencies — uses existing moviepy, librosa, PIL, numpy stack.
- **Output**: New file `output/session N/short.mp4` (9:16, ~20s, H.264+AAC).
- **Artwork**: Reuses existing per-track artwork from `artwork/session N/` — no new generation needed.
