## 1. Session Config & Theme Infrastructure

- [ ] 1.1 Add theme loading to session config parser — read optional `theme` block from session.json and merge with defaults
  <!-- Files: main.py -->
- [ ] 1.2 Define default theme constants dict (font, colors, sizes) and a `_get_session_theme(session_config)` helper that returns merged theme
  <!-- Files: main.py -->
- [ ] 1.3 Create `tracks/session 4/session.json` with LoFi playlist (~20 tracks, ~120 min), theme block with realistic artwork style, warm colors, and Quicksand font
  <!-- Files: tracks/session 4/session.json -->
- [ ] 1.4 Download and add Quicksand font to `fonts/Quicksand-Regular.ttf`
  <!-- Files: fonts/Quicksand-Regular.ttf -->

## 2. Realistic Artwork Generation

- [ ] 2.1 Add artwork prompt templates dict mapping `artwork_style` names to prompt strings (abstract, realistic)
  <!-- Files: main.py -->
- [ ] 2.2 Modify `_generate_artwork()` to accept a `theme` parameter and select prompt template based on `theme["artwork_style"]`
  <!-- Files: main.py -->
- [ ] 2.3 Update callers of `_generate_artwork()` to pass the session theme through
  <!-- Files: main.py -->

## 3. Video Loop Generation from Artwork

- [ ] 3.1 Create `_ken_burns_frame(image, t, duration)` function — applies zoom (1.0→1.05) and subtle pan with ping-pong over time
  <!-- Files: main.py -->
- [ ] 3.2 Create `_ambient_particles_overlay(frame, t)` function — renders soft floating dust/bokeh particles onto a frame
  <!-- Files: main.py -->
- [ ] 3.3 Create `_light_flicker(frame, t)` function — applies subtle ±3% brightness sine modulation
  <!-- Files: main.py -->
- [ ] 3.4 Create `_generate_video_loop_from_artwork(artwork_path, output_path, duration=10, fps=24)` function — composes Ken Burns + particles + flicker into a loopable MP4 clip
  <!-- Files: main.py -->
- [ ] 3.5 Add caching to video loop generation — skip if output MP4 already exists
  <!-- Files: main.py -->

## 4. Video Loop Integration

- [ ] 4.1 Add logic to auto-generate video loops for all unique artworks when `artwork_style` is `"realistic"` and no explicit `video_backgrounds` listed
  <!-- Files: main.py -->
- [ ] 4.2 Auto-populate `video_backgrounds` list at runtime with paths to generated loop files so existing video bg pipeline is used
  <!-- Files: main.py -->
- [ ] 4.3 Store generated video loops in `artwork/session N/loops/` directory alongside artwork PNGs
  <!-- Files: main.py -->

## 5. Visual Theme Application

- [ ] 5.1 Modify title text rendering in `generate_video()` to use theme font, title_color, title_stroke_color, and title_font_size
  <!-- Files: main.py -->
- [ ] 5.2 Modify particle system to use `theme["particle_color"]` instead of hardcoded [180, 200, 240]
  <!-- Files: main.py -->
- [ ] 5.3 Modify waveform visualizer to use `theme["waveform_color"]` instead of hardcoded color values
  <!-- Files: main.py -->
- [ ] 5.4 Modify background color to use `theme["bg_color"]` instead of hardcoded BG_COLOR
  <!-- Files: main.py -->
- [ ] 5.5 Modify video background darken factor to use `theme["bg_darken"]` instead of hardcoded VIDEO_BG_DARKEN
  <!-- Files: main.py -->

## 6. Integration & Testing

- [ ] 6.1 End-to-end test: run `python main.py 4` and verify session loads, artwork generates with realistic prompts, video loops generate, and final video renders
  <!-- Files: main.py, tracks/session 4/session.json -->
- [ ] 6.2 Backward compatibility test: run `python main.py 2` and verify existing sessions still render with default retro theme
  <!-- Files: main.py -->
- [ ] 6.3 Verify video loop seamlessness — check that loop boundary has no visible jump when played continuously
  <!-- Files: main.py -->
