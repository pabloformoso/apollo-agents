"""Tests for the time-stretch cap on track selection.

Measured on healing 2026-08-20: 'Silver Bloom' sits at 52.1 BPM when the
next slowest track in the genre is 58.6 and the median is 65.4. It forced
a 1.17x stretch live, 1.23x on a 60-minute render and 1.29x on a
25-minute one — three independent sets, same lone outlier.

It gets in because ``bpm_cluster`` groups against a median that MOVES as
tracks join, so the cluster's real span drifts well past its nominal
+-10 BPM window ("28 tracks, range 52-69 BPM" in that run).

The damage is doubled by the mix meeting in the middle: both sides move
toward each other, so one bad track pulls its neighbour off pitch too.
"""
from __future__ import annotations

import pytest

from main import MAX_STRETCH_RATIO, enforce_stretch_cap


def _t(name, bpm):
    return {"display_name": name, "bpm": bpm}


def _names(tracks):
    return [t["display_name"] for t in tracks]


class TestTheRealCase:

    def test_drops_the_silver_bloom_outlier(self):
        """The exact shape that produced 1.29x: a lone slow track mid-run."""
        ordered = [
            _t("Quiet Harbor", 59.8), _t("Binaural Drift", 59.8),
            _t("Moon Hollow", 58.6), _t("Slow Bloom", 67.0),
            _t("Silver Bloom", 52.1),          # <- 1.29x against 67.0
            _t("Quiet Tides", 61.1), _t("Velvet Dawn", 63.9),
        ]
        assert "Silver Bloom" not in _names(enforce_stretch_cap(ordered))

    def test_prunes_only_what_the_cap_requires(self):
        """59.8 -> 67.0 is 1.1204x: over the cap, so Slow Bloom goes too.

        Worth pinning rather than treating as collateral. Against the
        REAL catalog this cap drops 2 of 28 tracks and leaves 99 minutes
        of material; the aggressive-looking result here comes from a
        deliberately adversarial ordering, not from the cap being tight.
        """
        ordered = [
            _t("Quiet Harbor", 59.8), _t("Slow Bloom", 67.0),
            _t("Silver Bloom", 52.1), _t("Quiet Tides", 61.1),
        ]
        assert _names(enforce_stretch_cap(ordered)) == ["Quiet Harbor", "Quiet Tides"]

    def test_a_looser_cap_keeps_the_borderline_track(self):
        """Slow Bloom is borderline, not bad — 1.15x lets it through."""
        ordered = [_t("Quiet Harbor", 59.8), _t("Slow Bloom", 67.0)]
        assert len(enforce_stretch_cap(ordered, max_ratio=1.15)) == 2

    def test_every_surviving_pair_is_within_the_cap(self):
        """The invariant, over the real healing BPM spread."""
        bpms = [52.1, 58.6, 58.6, 59.8, 61.1, 63.9, 65.4, 68.6, 93.8, 98.7]
        kept = enforce_stretch_cap([_t(f"t{i}", b) for i, b in enumerate(bpms)])
        for a, b in zip(kept, kept[1:]):
            ratio = max(a["bpm"], b["bpm"]) / min(a["bpm"], b["bpm"])
            assert ratio <= MAX_STRETCH_RATIO, f"{a['bpm']} -> {b['bpm']} = {ratio:.2f}x"


class TestNoCascade:

    def test_compares_against_the_last_kept_not_the_previous(self):
        """Dropping an outlier must not drag down the tracks after it.

        60 -> 100 is out. If the next comparison used 100 (the dropped
        track) instead of 60, the healthy 62 would be dropped too.
        """
        ordered = [_t("a", 60.0), _t("spike", 100.0), _t("b", 62.0)]
        assert _names(enforce_stretch_cap(ordered)) == ["a", "b"]

    def test_consecutive_outliers_all_go(self):
        ordered = [_t("a", 60.0), _t("x", 100.0), _t("y", 105.0), _t("b", 61.0)]
        assert _names(enforce_stretch_cap(ordered)) == ["a", "b"]


class TestEdges:

    def test_first_track_is_always_kept(self):
        """Nothing precedes it, so there is no stretch to judge."""
        assert _names(enforce_stretch_cap([_t("only", 52.1)])) == ["only"]

    def test_empty_list(self):
        assert enforce_stretch_cap([]) == []

    def test_unknown_bpm_is_not_judged(self):
        """A missing BPM is a catalog gap, not a reason to drop the track."""
        ordered = [_t("a", 60.0), _t("no-bpm", None), _t("b", 62.0)]
        assert _names(enforce_stretch_cap(ordered)) == ["a", "no-bpm", "b"]

    def test_zero_bpm_is_not_judged(self):
        ordered = [_t("a", 60.0), _t("zero", 0), _t("b", 62.0)]
        assert "zero" in _names(enforce_stretch_cap(ordered))

    def test_ratio_exactly_at_the_cap_is_allowed(self):
        ordered = [_t("a", 100.0), _t("b", 100.0 * MAX_STRETCH_RATIO)]
        assert len(enforce_stretch_cap(ordered)) == 2

    def test_direction_does_not_matter(self):
        """Speeding up and slowing down are equally audible."""
        assert len(enforce_stretch_cap([_t("a", 100.0), _t("b", 50.0)])) == 1
        assert len(enforce_stretch_cap([_t("a", 50.0), _t("b", 100.0)])) == 1

    def test_cap_is_reported_not_silent(self, capsys):
        """A shorter set needs a reason in the log."""
        enforce_stretch_cap([_t("a", 60.0), _t("Silver Bloom", 52.1)])
        out = capsys.readouterr().out
        assert "[stretch cap]" in out and "Silver Bloom" in out

    def test_custom_ratio_is_honoured(self):
        ordered = [_t("a", 60.0), _t("b", 66.0)]   # 1.10x
        assert len(enforce_stretch_cap(ordered, max_ratio=1.05)) == 1
        assert len(enforce_stretch_cap(ordered, max_ratio=1.20)) == 2


def test_cap_is_a_sane_value():
    """Tight enough to matter, loose enough to leave a usable pool."""
    assert 1.05 <= MAX_STRETCH_RATIO <= 1.20
