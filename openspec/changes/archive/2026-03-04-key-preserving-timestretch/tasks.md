## 1. Dependencies

- [x] 1.1 Install rubberband system library (`brew install rubberband`) and verify it's available
  <!-- Files: (system) -->
- [x] 1.2 Add pyrubberband to pyproject.toml dependencies and run `uv sync`
  <!-- Files: pyproject.toml, uv.lock -->

## 2. Core Implementation

- [x] 2.1 Add `import pyrubberband` to main.py imports
  <!-- Files: main.py -->
- [x] 2.2 Create helper function to convert pydub AudioSegment to numpy float32 array (int16 → float32 normalized, stereo-aware reshape)
  <!-- Files: main.py -->
- [x] 2.3 Create helper function to convert numpy float32 array back to pydub AudioSegment (preserving sample rate, channels, sample width)
  <!-- Files: main.py -->
- [x] 2.4 Rewrite `change_speed()` internals to use pyrubberband.time_stretch instead of frame rate resampling. Keep the same function signature (segment, factor). Use crispness=6 for transient preservation.
  <!-- Files: main.py -->
- [x] 2.5 Rename `change_speed()` to `change_tempo()` and add `change_speed = change_tempo` alias for backward compatibility
  <!-- Files: main.py -->

## 3. Verification

- [x] 3.1 Run a short test: time-stretch a single track segment by factor 1.023 (~3 BPM delta) and verify output duration matches expected length and audio is not corrupted
  <!-- Files: main.py -->
- [ ] 3.2 Run full session 6 pipeline (`python main.py 6`) and verify the mix completes without errors
  <!-- Files: main.py -->
- [ ] 3.3 Listen to the Phantom Circuit transition (track 3, ~09:57) — confirm key no longer shifts audibly during the 95.3 → 113.1 BPM crossfade
  <!-- Files: output/session 6/mix_output.wav -->
- [ ] 3.4 Listen to a small-delta transition (e.g., Subzero at ~24:09, 127.8 → 130.8) — confirm no artifacts or quality degradation vs previous resampling approach
  <!-- Files: output/session 6/mix_output.wav -->
