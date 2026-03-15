# Proposal: Key-Preserving Time-Stretch

## Problem

BPM matching currently uses resampling (`change_speed()`), which shifts pitch proportionally with speed. This causes audible key changes during transitions:

- Small BPM deltas (1-3 BPM, ~130 base): ~13-40 cents shift — noticeable on tonal material
- Large BPM deltas (e.g., Phantom Circuit at 95.3 → 130.8): ~300 cents — destroys the key entirely

The Camelot keys defined in `session.json` become meaningless if pitch drifts during every transition.

## Solution

Replace resampling with **time-stretching** for all BPM adjustments. Time-stretching changes tempo independently of pitch, preserving the original key of every track.

### Approach

- Use **pyrubberband** (Python wrapper for the Rubber Band C library) for time-stretching
- Rubber Band is best-in-class for transient-heavy material (critical for techno kicks)
- Same engine used by Ableton Live, Traktor, and other pro DAWs
- Apply **uniformly** to all transitions regardless of BPM delta size

### Change Surface

The change is surgical. All BPM adjustments flow through a single function:

- **`change_speed(segment, factor)`** at `main.py:176` — replace resampling internals with time-stretch
- **`tempo_ramp(segment, ...)`** at `main.py:189` — calls `change_speed()`, no changes needed
- **`_adjust_outgoing_tail()`** at `main.py:386` — calls `change_speed()`, no changes needed
- **`_prepare_incoming()`** at `main.py:412` — calls `change_speed()`, no changes needed

Only `change_speed()` needs to change. Everything else flows through it.

### Dependencies

- Add `pyrubberband` to `pyproject.toml`
- Requires `rubberband` C library installed on the system (`brew install rubberband` on macOS)

### Tradeoffs

| Aspect | Before (resample) | After (time-stretch) |
|---|---|---|
| Pitch | Shifts with speed | Preserved |
| Transient quality | Perfect | Very good (Rubber Band) |
| Processing speed | Instant | Slower (FFT-based) |
| Audio mix phase | ~seconds | Will increase (acceptable — video render is the bottleneck at 2+ hours) |

### Out of Scope

- Key-aware harmonic mixing (pitch-shifting to match Camelot keys between tracks) — separate future concern
- The video render pipeline is unaffected
