# Design: Key-Preserving Time-Stretch

## Context

All BPM adjustments in the mix pipeline flow through `change_speed()` (`main.py:176`), which resamples audio by changing the frame rate. This is a zero-cost operation (just pointer math on pydub's raw PCM data), but it couples speed and pitch — speeding up a track also raises its pitch.

The pipeline uses pydub `AudioSegment` objects throughout. pyrubberband operates on numpy float arrays. This means the implementation needs a conversion bridge: pydub → numpy → rubberband → pydub.

## Goals / Non-Goals

**Goals:**
- Preserve the original musical key of every track during BPM adjustments
- Apply uniformly to all transitions (no threshold gating)
- Drop-in replacement — no changes needed to callers (`tempo_ramp`, `_adjust_outgoing_tail`, `_prepare_incoming`)

**Non-Goals:**
- Key-aware harmonic mixing (pitch-shifting between tracks to match Camelot keys)
- Optimizing the audio mix phase for speed
- Changing the video render pipeline

## Decisions

### 1. Use pyrubberband over librosa.effects.time_stretch

**Choice:** pyrubberband (Rubber Band library wrapper)

**Why not librosa:** librosa's `time_stretch` uses a basic phase vocoder that smears transients. Dark techno is dominated by sharp kicks, hi-hats, and percussive synths — phase vocoder artifacts would be audible. Rubber Band uses a sophisticated transient detector that preserves attack characteristics.

**Why not soundtouch:** Lower quality than Rubber Band on tonal material. Rubber Band is the industry standard (Ableton, Traktor, Reaper).

### 2. Convert pydub ↔ numpy at the `change_speed` boundary

**Choice:** Handle all format conversion inside `change_speed()` so callers are unaffected.

The conversion path:
```
AudioSegment → numpy float32 array → pyrubberband.time_stretch() → AudioSegment
```

pydub stores raw PCM as bytes (int16 or int32). The conversion:
- `np.frombuffer(segment.raw_data, dtype=np.int16)` to get samples
- Reshape to `(n_samples, n_channels)` for stereo
- Normalize to float32 `[-1.0, 1.0]` for rubberband
- After stretching, convert back: scale to int16, pack to bytes, create new AudioSegment

This adds overhead per call but keeps the interface identical.

### 3. Rename function to `change_tempo` and keep `change_speed` as alias

**Choice:** Rename to `change_tempo()` to reflect new semantics (tempo changes without pitch change). Keep `change_speed` as a thin alias for backward compatibility within the file.

### 4. Use RubberBand's "crisp" transient mode

**Choice:** Pass `rbargs={'-c': '6'}` (crispness=6, the maximum) to pyrubberband to prioritize transient preservation. This is ideal for percussive electronic music. The default (crispness=5) is already good, but 6 gives the sharpest kicks at the cost of slightly more processing time.

## Risks / Trade-offs

**[Performance] Audio mix phase will be slower → Acceptable**
Current resampling is near-instant (pointer math). Time-stretching requires FFT processing on every segment. However, the audio mix phase currently takes seconds while the video render takes 2+ hours. Even a 10-50x slowdown on audio mixing is negligible in the total pipeline.

**[Quality] Time-stretching artifacts on extreme BPM changes → Monitor**
Large stretch ratios (e.g., Phantom Circuit 95.3 → 113.1 = 18.7% stretch) can introduce subtle artifacts even with Rubber Band. Quality will still be far better than the current 3-semitone pitch shift. If artifacts appear, the fix is better playlist curation (avoid huge BPM jumps), not a code change.

**[Dependency] System-level rubberband library required → Document**
pyrubberband is a thin Python wrapper; the actual DSP is done by the `rubberband` C library which must be installed separately (`brew install rubberband`). This is the only system dependency beyond Python packages. Needs clear documentation in README or setup instructions.

**[Edge case] Very short segments in tempo_ramp → Test**
`tempo_ramp()` splits audio into small chunks (default 20 steps). Very short chunks (<50ms) fall back to a single `change_speed()` call. Rubber Band handles short segments fine, but worth verifying there's no minimum length issue.

## Parallelism Considerations

This is a single-function change with no parallelism needed. The entire implementation is:
1. Add pyrubberband dependency
2. Rewrite `change_speed()` internals (~15 lines)
3. Test with an existing session

No shared interfaces, no serialization points. One task.
