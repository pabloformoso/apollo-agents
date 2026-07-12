# Design + acceptance criteria — genre transition profiles

## Work split (two agents, disjoint files)

### Agent A — backend
Files: `agent/transition_styles.py`, `agent/live_engine.py`,
`tests/test_transition_profiles.py` (new), and ONLY IF strictly needed
the picker call sites. DO NOT touch `agent/phase_lock.py`,
`web/frontend/**`, `main.py`.

1. `transition_styles.py`: add `TransitionStyle.DRIFT`,
   `TransitionProfile` dataclass, `GENRE_TRANSITION_PROFILES` (aural →
   dj_mix=False, crossfade_sec=24.0), `profile_for_genre(genre)`
   (case-insensitive on `genre_folder` strings; unknown/None → default
   profile dj_mix=True, crossfade_sec=None). `serialise_choice` must
   serialize a DRIFT choice as `{"transition_style": "drift"}` with no
   bass_swap block.
2. `LiveEngineBrowser` (v3.x browser engine ONLY; LiveEngineLocal out
   of scope): resolve the profile per transition (drift when EITHER the
   current or next track's `genre_folder` — falling back to `genre` —
   maps to dj_mix=False).
   - In drift transitions the phase-lock plan must NOT drive anchors:
     the emitted payload carries `transition_style: "drift"`; the
     engine's `_cf_point_seconds` for the outgoing track uses the
     legacy formula with the profile's crossfade_sec (24s) instead of
     `self.crossfade_sec`.
   - The `crossfade` engine_command emits `crossfade_sec` = effective
     (24.0) for drift transitions.
   - Non-drift transitions: bit-for-bit unchanged behavior.
3. Tests (`tests/test_transition_profiles.py` + extend existing suites
   only where they break): profile lookup matrix; serialisation of
   DRIFT; engine-level: aural→aural transition emits drift style +
   24s crossfade_sec + earlier cf_point_sec; aural→lofi and
   lofi→aural also drift; lofi→lofi keeps current behavior (style
   smooth_blend/bass_swap path untouched, default crossfade_sec);
   endless fallback appends still work for aural (gate/extend paths
   unaffected by profile).

### Agent B — frontend
Files: `web/frontend/lib/live.ts`, `web/frontend/lib/audio_buffer_decks.ts`
(only if needed), `web/frontend/__tests__/live.test.ts`. DO NOT touch
backend files or `crossfade_timing.ts`.

1. `crossfadeToNext` (and any phase-lock consumption path): when the
   incoming payload/style says `transition_style === "drift"`:
   - ignore phase-lock anchors entirely (no downbeat repositioning),
   - schedule the incoming deck at playbackRate 1.0 (no rate ramps),
   - apply plain equal-power gain curves over the received
     `crossfade_sec`,
   - no BiquadFilter automation of any kind.
2. Defensive: absence of `transition_style` or unknown values behave
   exactly as today (backward compatible with older backends).
3. Tests (vitest, existing FakeWebSocket/FakeAudioContext harness):
   drift crossfade → source playbackRate stays 1.0, no
   filter.frequency automation calls, gain uses equal-power curves
   over the wire crossfade_sec; non-drift regression: existing
   bass_swap/smooth tests keep passing untouched.

## Acceptance criteria (verified by the orchestrator at the end)

- AC1: `profile_for_genre("aural").dj_mix is False`; unknown genres
  default to dj_mix=True. Case-insensitive.
- AC2: engine test proves an aural→aural transition emits
  `transition_style: "drift"`, `crossfade_sec == 24.0`, and NO
  bass_swap block in the payload.
- AC3: engine test proves mixed transitions (aural on either side)
  are drift; lofi→lofi transitions are byte-identical to pre-change
  behavior (existing tests untouched and green).
- AC4: frontend test proves a drift crossfade never touches
  playbackRate (stays 1.0) nor filter automation, and ramps gains
  over the received crossfade_sec.
- AC5: no changes to `agent/phase_lock.py`, `main.py`,
  `web/frontend/lib/crossfade_timing.ts`.
- AC6: full suites green: `uv run pytest tests/ --ignore=tests/web/test_youtube_chat.py`,
  `npx vitest run`, `npx tsc --noEmit`.

## Definition of done

- Every new function has unit tests (happy path + edge cases).
- ACs 1–6 verified by the orchestrator (not self-reported by agents).
- Single PR, CI fully green, squash-merged; deploy after merge with
  a real aural session smoke (operator listens to one transition).
