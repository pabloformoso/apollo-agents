"""v3.6 beatmatch regression tests — reproduce the deep-house contrabombo
found live on 2026-06-26 (see memory project_v36_beatmatch_endbar_bug).

These are written RED-FIRST: they encode the *desired* v3.6 behaviour and
are expected to FAIL against current main until the fix lands. Each test
uses the real downbeat geometry captured from the live set so the repro is
faithful, not synthetic.

Three demonstrated failures:
  1. A truncated final downbeat in the crossfade window (madmom places the
     last downbeat ~25% early against the track end) trips _is_grid_warpable
     → grid-warp self-disables EXACTLY on the transition.
  2. The 5-BPM dead zone leaves the static fallback uncorrected, so when (1)
     fires there is no tempo correction at all → contrabombo within seconds.
  3. (forward-looking) whole-track cv looks fine while the crossfade WINDOW
     is the bad part — the gate must judge the window, after end-bar repair.
"""
from __future__ import annotations

import pytest

from agent.phase_lock import (
    compute_beat_rate_schedule,
    compute_tempo_match_rate,
    _is_grid_warpable,
    GRIDWARP_MAX_CV,
)


def _grid(bpm: float, n: int, start: float = 0.0) -> list[float]:
    """Perfectly even 4/4 downbeat list at ``bpm`` (bar = 4 beats)."""
    bar = (60.0 / bpm) * 4.0
    return [round(start + i * bar, 4) for i in range(n)]


# ---------------------------------------------------------------------------
# Bug 1 — truncated end-bar disables grid-warp
# ---------------------------------------------------------------------------

class TestTruncatedEndBar:
    """Real repro: Twilight Glow's crossfade window had bar lengths
    2.02, 2.01, 2.02, 2.02, 2.02, 1.51 — the final 1.51s bar is a madmom
    truncation against the track end. One outlier in a 6-bar window must
    NOT disable the whole grid-warp.
    """

    def _twilight_glow_tail(self) -> list[float]:
        # Downbeats reconstructed from the live capture (db[107..113]).
        starts = [215.79, 217.81, 219.82, 221.84, 223.86, 225.88, 227.39]
        return starts

    def test_window_bar_lengths_match_live_capture(self):
        db = self._twilight_glow_tail()
        bars = [round(db[i + 1] - db[i], 2) for i in range(len(db) - 1)]
        assert bars == [2.02, 2.01, 2.02, 2.02, 2.02, 1.51]

    def test_current_gate_rejects_due_to_truncated_bar(self):
        """Documents the BUG as it exists today: the raw window fails the
        gate because of the single 1.51s bar. This test asserts the buggy
        status quo so the fix flips it (and this test gets updated)."""
        bars = [2.02, 2.01, 2.02, 2.02, 2.02, 1.51]
        # CURRENT behaviour: the truncated bar makes the window non-warpable.
        assert _is_grid_warpable(bars, GRIDWARP_MAX_CV) is False

    def test_v36_truncated_endbar_still_warps(self):
        """DESIRED v3.6: a tight tail with a single truncated final bar
        must still produce a grid_warp schedule (the outlier is repaired
        to the median bar, not used to reject the whole window)."""
        outgoing = self._twilight_glow_tail()          # tight + 1 truncated bar
        incoming = _grid(120.0, 12)                     # pristine (in_cv≈0)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=outgoing,
            incoming_downbeats=incoming,
            outgoing_anchor_sec=outgoing[0],
            incoming_anchor_sec=incoming[0],
            xfade_sec=12.0,
            ramp_sec=16.0,
        )
        assert sched.mode == "grid_warp"
        assert len(sched.segments) >= 2


# ---------------------------------------------------------------------------
# Bug 2 — 5-BPM dead zone leaves the static fallback uncorrected
# ---------------------------------------------------------------------------

class TestBpmDeadZone:
    """All 4 live transitions had static_rate=1.0000 despite Δ up to 3.0
    BPM (118.81 vs 120.0, etc.). When grid-warp falls back to static, the
    static rate must still tempo-match or the decks free-run → contrabombo.
    """

    def test_v36_dead_zone_now_corrects_small_delta(self):
        # Δ1.19 BPM (Twilight Glow→Transparent Dawn) — pre-v3.6 this returned
        # 1.0 (the 5-BPM dead zone) and the decks free-ran into contrabombo.
        # Post-v3.6 the crossfade default threshold is 0.3, so it corrects.
        rate = compute_tempo_match_rate(118.81, 120.0)
        assert rate != 1.0
        assert abs(rate - (118.81 / 120.0)) < 1e-6

    def test_v36_small_bpm_delta_gets_corrected(self):
        # Δ1.19 BPM should produce a real correction (rate ≈ 118.81/120).
        rate = compute_tempo_match_rate(118.81, 120.0)
        assert rate != 1.0
        assert abs(rate - (118.81 / 120.0)) < 1e-6

    def test_v36_within_micro_threshold_still_noop(self):
        # Truly negligible deltas (<~0.5 BPM, detection noise) should stay
        # a no-op even after the threshold shrinks. Δ0.6 is borderline; use
        # Δ0.2 here as the clearly-still-noop case so this holds post-fix.
        assert compute_tempo_match_rate(120.0, 120.2) == 1.0
