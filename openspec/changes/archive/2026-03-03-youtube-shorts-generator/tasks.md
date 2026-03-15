## 1. CLI Integration

- [x] 1.1 Add `--short` argument to the CLI argument parser in `main.py`
- [x] 1.2 Add main entry-point logic: when `--short` is set, validate that `mix_output.wav` and artwork exist for the session, then call the short generator instead of the full pipeline

## 2. Highlight Selection

- [x] 2.1 Implement `find_highlight_segment(audio_path, duration_sec=20)` — slide a window across the mix audio, return the start timestamp with highest average RMS energy
- [x] 2.2 Implement `extract_short_audio(audio_path, start_sec, duration_sec=20)` — extract the segment from the WAV with 0.5s fade-in and 1.0s fade-out, return as AudioSegment

## 3. Vertical Video Rendering

- [x] 3.1 Add short-specific video constants: `SHORT_VIDEO_SIZE = (1080, 1920)`, `SHORT_DURATION_SEC = 20`, layout positions for artwork square, title, waveform, CTA
- [x] 3.2 Implement `_short_ken_burns_frame(image, t, duration)` — adapt existing `_ken_burns_frame` to output 1080×1920 vertical frames
- [x] 3.3 Implement `_render_short_frame(t, ...)` — compose a single vertical frame: darkened artwork background, centered track artwork square, track title, waveform, session title, CTA text
- [x] 3.4 Integrate waveform visualizer into vertical layout — reuse `_compute_waveform_data` and `_apply_waveform` with 1080px width and adjusted vertical position

## 4. Short Video Assembly

- [x] 4.1 Implement `generate_short(session_dir, session_config, output_path)` — orchestrator that calls highlight selection, loads artwork, renders frames, and encodes to MP4
- [x] 4.2 Determine which track is playing at the highlight midpoint (from transitions data) and load its artwork for the background and centered square
- [x] 4.3 Export the final short video with H.264 + AAC to `output/session N/short.mp4`

## 5. Testing

- [x] 5.1 Run `python main.py 4 --short` end-to-end and verify output file exists at correct path with 1080×1920 dimensions and ~20s duration
- [x] 5.2 Verify the short plays correctly in a media player with audio, waveform, titles, and CTA visible
