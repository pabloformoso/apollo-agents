"""Unit tests for the v3.5 beatmatch diagnostic helper (_bar_cv).

This covers the temporary instrumentation added for the deep-house
"mordida" tuning pass — the per-transition ``[beatmatch]`` log line that
distinguishes "gate too strict → static fallback" from "grid_warp ran
but still bites". Pure function, no audio / no engine state required.
"""
from __future__ import annotations

from agent.live_engine import _bar_cv


class TestBarCv:
    def test_perfect_grid_is_zero(self):
        # Evenly spaced downbeats → no variation → cv 0.
        downbeats = [0.0, 0.5, 1.0, 1.5, 2.0]
        assert _bar_cv(downbeats) == "0.0000"

    def test_tight_electronic_grid_below_gate(self):
        # ~0.5 s bars with sub-ms jitter — a tight 4/4 grid should land
        # well under the GRIDWARP_MAX_CV gate (0.04).
        downbeats = [0.0, 0.500, 1.002, 1.499, 2.001, 2.498]
        cv = float(_bar_cv(downbeats))
        assert 0.0 < cv < 0.04

    def test_loose_swung_grid_above_gate(self):
        # Wildly uneven bars (swing / bad detection) → cv well above gate.
        downbeats = [0.0, 0.5, 1.3, 1.6, 2.7, 3.0]
        cv = float(_bar_cv(downbeats))
        assert cv > 0.04

    def test_empty_returns_na(self):
        assert _bar_cv([]) == "n/a"

    def test_too_few_downbeats_returns_na(self):
        # Need at least 3 downbeats (2 bars) to measure variation.
        assert _bar_cv([0.0, 0.5]) == "n/a"

    def test_nonincreasing_grid_returns_na(self):
        # Degenerate / corrupt grid (zero mean interval) → n/a, never a crash.
        assert _bar_cv([0.0, 0.0, 0.0]) == "n/a"
