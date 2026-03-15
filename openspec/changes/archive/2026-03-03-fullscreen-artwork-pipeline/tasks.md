## 1. Cover-Crop Scaling Foundation

- [ ] 1.1 Add `_cover_crop(img, target_w, target_h)` helper function that scales a PIL Image to cover the target dimensions and center-crops to exact size
  <!-- Files: main.py -->
- [ ] 1.2 Update `_generate_artwork` to use `_cover_crop` instead of `img.resize` when saving DALL-E output to disk
  <!-- Files: main.py -->
- [ ] 1.3 Update `_load_artwork_images` to use `_cover_crop` instead of `img.resize` when loading artwork for video backgrounds
  <!-- Files: main.py -->

## 2. Artwork Brightness and Blur

- [ ] 2.1 Change `ARTWORK_DARKEN_FACTOR` constant from 0.25 to 0.85
  <!-- Files: main.py -->
- [ ] 2.2 Change `ARTWORK_BLUR_RADIUS` constant from 12 to 2
  <!-- Files: main.py -->
- [ ] 2.3 Update Session 4's `bg_darken` theme value to 0.85 to match the new artwork-prominent style
  <!-- Files: tracks/session 4/session.json -->

## 3. Waveform Region Contrast

- [ ] 3.1 Add a `_apply_waveform_gradient` helper that darkens the bottom ~250px of a frame with a vertical gradient (transparent at top, ~50% dark at bottom)
  <!-- Files: main.py -->
- [ ] 3.2 Call `_apply_waveform_gradient` in `generate_video`'s `make_frame` function after artwork background but before waveform rendering
  <!-- Files: main.py -->
- [ ] 3.3 Call `_apply_waveform_gradient` in `_render_short_frame` for YouTube Shorts before waveform rendering
  <!-- Files: main.py -->

## 4. Ken Burns Cover-Crop Integration

- [ ] 4.1 Update `_ken_burns_frame` to accept pre-cover-cropped source images at 110% of target size (already the case via `1.1 * VIDEO_SIZE` in `_generate_video_loop_from_artwork`)
  <!-- Files: main.py -->
- [ ] 4.2 Update `_load_artwork_images` to prepare Ken Burns source at 110% target dimensions using `_cover_crop` (currently uses exact size)
  <!-- Files: main.py -->

## 5. YouTube Short Fullscreen Artwork

- [ ] 5.1 Update `generate_short` background artwork loading to use `_cover_crop` for the 1080×1920 vertical background (replacing manual resize)
  <!-- Files: main.py -->
- [ ] 5.2 Update `_short_ken_burns_frame` to work correctly with cover-cropped vertical source images
  <!-- Files: main.py -->
- [ ] 5.3 Update Short background darkening to use session's `bg_darken` theme value instead of hardcoded `ARTWORK_DARKEN_FACTOR`
  <!-- Files: main.py -->

## 6. Session 5 Configuration

- [ ] 6.1 Create `tracks/session 5/session.json` with session name, description, and anime/LoFi theme matching Session 4's aesthetic
  <!-- Files: tracks/session 5/session.json -->
- [ ] 6.2 Define curated playlist order for all 20 tracks with flow progression (ambient → build → energy → wind-down → ambient close)
  <!-- Files: tracks/session 5/session.json -->
- [ ] 6.3 Assign Camelot keys and genre tags to all 20 tracks in the playlist
  <!-- Files: tracks/session 5/session.json -->
- [ ] 6.4 Set Session 5 theme `bg_darken` to 0.85 for artwork-prominent display
  <!-- Files: tracks/session 5/session.json -->

## 7. Validation

- [ ] 7.1 Verify Session 5 loads correctly: `python main.py 5` parses session.json and lists all 20 tracks
  <!-- Files: main.py, tracks/session 5/session.json -->
- [ ] 7.2 Verify artwork cover-crop produces full-frame images with no borders (visual check on a test artwork)
  <!-- Files: main.py -->
- [ ] 7.3 Verify waveform gradient provides readable contrast against bright artwork
  <!-- Files: main.py -->
