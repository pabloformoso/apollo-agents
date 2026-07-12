# Genre transition profiles — "drift" mode for beatless genres

## Problem (found live 2026-07-12, aural stream)

The `aural` collection (65 tracks: space drones, healing frequencies,
median 172s, NO valid beat structure) gets the full DJ treatment at
every transition: tempo-matching (observed playbackRate 0.91–1.12 —
audible wow/flutter AND pitch shift, fatal for frequency-based
content), grid-warp built on hallucinated beatgrids (madmom "found"
50–95 BPM in beatless pads; interval CVs 0.14–0.33 vs the 0.04
stability gate), and bass-swap filter automation that reads as an
audio dropout on ambient pads. The operator hears "cortes" every ~2.5
minutes.

## Decision

Per-genre **transition profile** metadata living in
`agent/transition_styles.py` (the existing how-does-it-sound layer):

```python
@dataclass(frozen=True)
class TransitionProfile:
    dj_mix: bool            # False → no tempo match, no grid warp, no bass swap
    crossfade_sec: float | None  # override; None → engine default

GENRE_TRANSITION_PROFILES = {
    "aural": TransitionProfile(dj_mix=False, crossfade_sec=24.0),
}

def profile_for_genre(genre: str | None) -> TransitionProfile  # default: dj_mix=True, None
```

A transition runs in **drift mode** when EITHER endpoint track's
genre resolves to a `dj_mix=False` profile. Drift mode =
`TransitionStyle.DRIFT = "drift"`: one long equal-power crossfade at
native playback rate. Nothing else.

## Wire contract (backend → frontend, FROZEN — both agents code to this)

- The phase-lock payload dict (built where `serialise_choice` is
  merged today) carries `"transition_style": "drift"` and NO
  `bass_swap` block. Anchor fields may be absent or present; the
  frontend MUST ignore them when style is `drift`.
- The `engine_command: "crossfade"` payload's existing
  `crossfade_sec` field carries the profile override (24.0 for
  aural) instead of the engine default when drift applies.
- `track_started` / `approaching_crossfade` events keep carrying
  `cf_point_sec`; in drift mode it reflects the LONGER crossfade
  (legacy formula `duration - crossfade_sec_effective - 5`).

## Non-goals

- No changes to `agent/phase_lock.py` internals (W4 beatmatch branch
  territory — the profile gates BEFORE that machinery runs).
- No offline-pipeline (`main.py`) changes.
- No UI for editing profiles — code-level metadata for now.
