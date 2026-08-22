"""Tests for the beatgrid bar-length audit.

The bug it detects: a stored beatgrid claims ``beats_per_bar: 4`` while
its own ``downbeats_sec`` sit two beats apart. 150 of 510 catalogued
tracks were in that state on 2026-08-22, concentrated in the ambient
genres (aural 66%, healing 36%) and absent from deep house (0%) — the
rate tracks how much percussive attack the detector had to work with.
"""
from __future__ import annotations

import pytest

from scripts.audit_beatgrid_bars import (
    SUSPECT_BEATS_PER_BAR,
    audit,
    implied_beats_per_bar,
)


def _track(bpm, gap_beats, n=12, **kw):
    """Build a track whose downbeats sit ``gap_beats`` apart."""
    beat = 60.0 / bpm
    step = beat * gap_beats
    grid = {
        "downbeats_sec": [round(i * step, 4) for i in range(n)],
        "beats_per_bar": kw.pop("stored_bpb", 4),
        "source": "madmom",
    }
    grid.update(kw.pop("grid", {}))
    return {"id": kw.pop("id", "t"), "display_name": kw.pop("name", "T"),
            "genre_folder": kw.pop("genre", "Healing"), "bpm": bpm,
            "beatgrid": grid}


class TestImpliedBeatsPerBar:

    def test_detects_a_healthy_four_beat_bar(self):
        assert implied_beats_per_bar(_track(60.0, 4)) == pytest.approx(4.0)

    def test_detects_the_two_beat_bar(self):
        """The real failure: 59.8 BPM with 2.0s gaps."""
        assert implied_beats_per_bar(_track(59.8, 2)) == pytest.approx(2.0, abs=0.01)

    @pytest.mark.parametrize("bpm", [52.1, 58.6, 61.1, 65.4, 80.4])
    def test_is_independent_of_tempo(self, bpm):
        """Normalising by beat length is the point — a slow track is not suspect.

        Tolerance is absolute rather than relative: the fixture rounds
        downbeats to 4 dp, the way a stored grid does, so an exact match
        is not on offer.
        """
        assert implied_beats_per_bar(_track(bpm, 4)) == pytest.approx(4.0, abs=0.01)
        assert implied_beats_per_bar(_track(bpm, 2)) == pytest.approx(2.0, abs=0.01)

    def test_uses_the_median_not_the_mean(self):
        """A dropped downbeat over a quiet passage leaves one long gap.

        The mean would be dragged upward by it and hide a bad grid; the
        median ignores it.
        """
        t = _track(60.0, 2, n=10)
        t["beatgrid"]["downbeats_sec"][-1] += 30.0   # one huge outlier gap
        assert implied_beats_per_bar(t) == pytest.approx(2.0, abs=0.01)


class TestUnjudgeable:

    def test_no_beatgrid(self):
        assert implied_beats_per_bar({"bpm": 60.0}) is None

    def test_too_few_downbeats(self):
        assert implied_beats_per_bar(
            {"bpm": 60.0, "beatgrid": {"downbeats_sec": [0.0, 2.0]}}) is None

    def test_missing_bpm_cannot_be_normalised(self):
        t = _track(60.0, 2)
        t["bpm"] = None
        assert implied_beats_per_bar(t) is None

    def test_zero_bpm(self):
        t = _track(60.0, 2)
        t["bpm"] = 0
        assert implied_beats_per_bar(t) is None


class TestAudit:

    def test_flags_only_the_disagreeing_grids(self):
        rows = audit([
            _track(60.0, 4, name="good"),
            _track(59.8, 2, name="bad"),
            _track(61.1, 4, name="also good"),
        ])
        assert [r["display_name"] for r in rows] == ["bad"]

    def test_row_carries_both_numbers(self):
        """The report has to show the contradiction, not just the verdict."""
        row = audit([_track(59.8, 2, name="bad")])[0]
        assert row["stored_beats_per_bar"] == 4
        assert row["implied_beats_per_bar"] == pytest.approx(2.0, abs=0.01)

    def test_unjudgeable_tracks_are_skipped_not_flagged(self):
        assert audit([{"bpm": 60.0}, {"beatgrid": {}}]) == []

    def test_threshold_leaves_room_for_jitter(self):
        """3.0 sits well clear of both the healthy 4.0 and the real 2.0."""
        assert 2.0 < SUSPECT_BEATS_PER_BAR < 4.0
        assert audit([_track(60.0, 3.6, name="jittery")]) == []

    def test_the_calm_harbor_case_is_flagged(self):
        """The one real outlier that is not exactly 2.0 — it measured 2.67."""
        rows = audit([_track(61.1, 2.67, name="Calm Harbor")])
        assert len(rows) == 1
