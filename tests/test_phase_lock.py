"""
Tests for v3.0 precision beat matching.

Covers:
  - find_phrase_anchor() — 16/8/4-bar phrase ladder, fallback behaviour
  - _pick_incoming_anchor() — pickup-skip RMS heuristic
  - compute_phase_lock() — anchor selection wiring
  - _GridTracker — catalog↔mix-time mapping across transitions
  - _phase_locked_crossfade() — equal-power overlay-add, edge-guard, mono+stereo
  - Integration on synthesised click tracks: render via build_mix() and assert
    that the two click trains stay phase-locked to <20 ms through the overlap.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from pydub import AudioSegment

import main as main_module
from main import (
    CROSSFADE_SEC,
    TEMPO_RAMP_SEC,
    _GridState,
    _GridTracker,
    _phase_locked_crossfade,
    _pick_incoming_anchor,
    build_mix,
    compute_phase_lock,
    find_phrase_anchor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SR = 22050


def _click_track(bpm: float, duration_sec: float, first_db_sec: float = 0.0,
                 sr: int = SR) -> tuple[np.ndarray, list[float]]:
    """Build a mono click train at the given BPM. Returns (audio, downbeats)."""
    n = int(duration_sec * sr)
    y = np.zeros(n, dtype=np.float32)
    beat_period = 60.0 / bpm
    bar_period = beat_period * 4.0  # 4/4
    downbeats: list[float] = []
    t = first_db_sec
    while t < duration_sec:
        idx = int(round(t * sr))
        if 0 <= idx < n:
            # Stamp a 5-sample impulse train so RMS is comfortably above the
            # pickup-skip threshold across an entire bar.
            for k in range(5):
                if idx + k < n:
                    y[idx + k] = 0.9
            downbeats.append(round(t, 3))
        t += bar_period
    return y, downbeats


def _click_segment(bpm: float, duration_sec: float,
                   sr: int = SR) -> AudioSegment:
    """A pydub AudioSegment carrying the click train (for integration tests)."""
    y, _ = _click_track(bpm, duration_sec, sr=sr)
    int_y = np.clip(y, -1.0, 1.0)
    int_y = (int_y * 32000.0).astype(np.int16)
    return AudioSegment(
        data=int_y.tobytes(), sample_width=2, frame_rate=sr, channels=1,
    )


def _silent_segment(duration_sec: float, sr: int = SR) -> AudioSegment:
    return AudioSegment.silent(duration=int(duration_sec * 1000), frame_rate=sr)


# ---------------------------------------------------------------------------
# find_phrase_anchor()
# ---------------------------------------------------------------------------

class TestFindPhraseAnchor:
    """Bar grid: 128 BPM 4/4 → 1 bar = 1.875 s. 16 bars = 30 s."""

    DOWNBEATS = [round(i * 1.875, 3) for i in range(32)]  # 0 … 58.125 s
    DURATION = 60.0

    def test_returns_phrase_boundary_when_target_lines_up(self):
        # downbeats[16] = 30.0 s, on a 16-bar boundary
        anchor, tier = find_phrase_anchor(self.DOWNBEATS, target_sec=30.0,
                                          track_duration_sec=self.DURATION)
        assert anchor == 30.0
        assert tier == "16-bar"

    def test_falls_back_to_8_bar_when_no_16_bar_candidate(self):
        # Force 16-bar fail: tight max_offset and target far from boundary
        anchor, tier = find_phrase_anchor(self.DOWNBEATS, target_sec=15.0,
                                          track_duration_sec=self.DURATION,
                                          max_offset_sec=2.0)
        # 16-bar candidates within 2 s of 15.0: none (0.0 and 30.0 both too far)
        # 8-bar candidates: downbeats[0::8] = [0, 15.0, 30.0, 45.0]
        # closest to 15.0 within 2 s = 15.0
        assert anchor == 15.0
        assert tier == "8-bar"

    def test_min_tail_constraint_used_when_satisfiable(self):
        """When the target is reachable AND has a candidate past it that
        also satisfies min_tail, the function picks one. 8-bar 45.0 is the
        right answer for target=45 on this grid."""
        anchor, tier = find_phrase_anchor(self.DOWNBEATS,
                                          target_sec=45.0,
                                          track_duration_sec=self.DURATION,
                                          min_tail_sec=CROSSFADE_SEC + 0.5)
        assert anchor == 45.0
        assert tier == "8-bar"
        assert self.DURATION - anchor >= CROSSFADE_SEC + 0.5

    def test_falls_back_to_closest_beat_when_no_constraint_fits(self):
        """When no candidate satisfies the tail constraint, the function
        falls back to the closest plain beat — better than crashing the
        mix. The 'fallback' tier label is the diagnostic signal."""
        # Target near track end where no beat can satisfy min_tail.
        _anchor, tier = find_phrase_anchor(self.DOWNBEATS,
                                           target_sec=58.0,
                                           track_duration_sec=self.DURATION,
                                           min_tail_sec=CROSSFADE_SEC + 0.5)
        assert tier == "fallback"

    def test_empty_downbeats_returns_fallback(self):
        anchor, tier = find_phrase_anchor([], target_sec=10.0,
                                          track_duration_sec=20.0)
        assert anchor == 10.0
        assert tier == "fallback"

    def test_picks_closest_among_phrase_boundaries(self):
        # Two 16-bar candidates within range: 0.0 and 30.0; target 25.0 →
        # 30.0 is closer than 0.0.
        anchor, tier = find_phrase_anchor(self.DOWNBEATS, target_sec=25.0,
                                          track_duration_sec=self.DURATION,
                                          max_offset_sec=10.0)
        assert anchor == 30.0
        assert tier == "16-bar"


# ---------------------------------------------------------------------------
# _pick_incoming_anchor()
# ---------------------------------------------------------------------------

class TestPickIncomingAnchor:

    def test_default_is_first_downbeat(self):
        downbeats = [0.0, 1.875, 3.75]
        y = np.ones(int(SR * 4), dtype=np.float32) * 0.5
        anchor, skipped = _pick_incoming_anchor(downbeats, y, SR)
        assert anchor == 0.0
        assert skipped is False

    def test_skips_quiet_pickup_bar(self):
        downbeats = [0.0, 1.875, 3.75]
        # First bar (0 → 1.875s) is mostly silent; rest of track is loud.
        bar0_end = int(SR * 1.875)
        y = np.ones(int(SR * 10), dtype=np.float32) * 0.5
        y[:bar0_end] *= 0.05  # < 40% of track mean
        anchor, skipped = _pick_incoming_anchor(downbeats, y, SR)
        assert anchor == 1.875
        assert skipped is True

    def test_empty_audio_returns_first_downbeat(self):
        anchor, skipped = _pick_incoming_anchor([0.0, 1.0], None, SR)
        assert anchor == 0.0
        assert skipped is False

    def test_empty_downbeats_returns_zero(self):
        anchor, skipped = _pick_incoming_anchor([], np.zeros(SR, dtype=np.float32), SR)
        assert anchor == 0.0
        assert skipped is False


# ---------------------------------------------------------------------------
# compute_phase_lock()
# ---------------------------------------------------------------------------

class TestComputePhaseLock:

    def test_anchors_picked_from_grids(self):
        out_downbeats = [round(i * 1.875, 3) for i in range(32)]  # 60 s of 128 BPM
        in_downbeats = [round(i * 1.875, 3) for i in range(32)]
        plan = compute_phase_lock(
            outgoing_downbeats=out_downbeats,
            outgoing_duration_catalog_sec=60.0,
            incoming_downbeats=in_downbeats,
            incoming_audio_y=None,
            incoming_sr=SR,
        )
        # Target = 60 - 12 = 48 s. Closest 16-bar boundary ∈ {30.0, 60.0};
        # but 60.0 violates min_tail → 30.0 wins (offset 18 s, beyond
        # default 4-s max → falls through to 8-bar → 4-bar → downbeat).
        assert plan.outgoing_anchor_catalog_sec <= 60.0 - CROSSFADE_SEC
        assert plan.incoming_anchor_catalog_sec == 0.0
        assert plan.xfade_catalog_sec == CROSSFADE_SEC
        assert plan.ramp_catalog_sec == TEMPO_RAMP_SEC

    def test_pickup_skipped_flag_propagates(self):
        in_downbeats = [0.0, 1.875]
        bar0_end = int(SR * 1.875)
        y = np.ones(int(SR * 5), dtype=np.float32) * 0.5
        y[:bar0_end] *= 0.05
        plan = compute_phase_lock(
            outgoing_downbeats=[0.0, 1.875, 3.75],
            outgoing_duration_catalog_sec=10.0,
            incoming_downbeats=in_downbeats,
            incoming_audio_y=y,
            incoming_sr=SR,
        )
        assert plan.incoming_pickup_skipped is True
        assert plan.incoming_anchor_catalog_sec == 1.875


# ---------------------------------------------------------------------------
# _GridTracker
# ---------------------------------------------------------------------------

class TestGridTracker:

    def test_first_track_identity_mapping(self):
        tracker = _GridTracker()
        tracker.set_first(
            track_id="t1",
            duration_catalog_sec=60.0,
            downbeats_sec=[0.0, 1.875, 3.75],
            beats_per_bar=4,
        )
        assert tracker.state.catalog_to_mix(0.0) == 0.0
        assert tracker.state.catalog_to_mix(30.0) == 30.0

    def test_after_transition_offset_is_correct(self):
        tracker = _GridTracker()
        tracker.set_after_transition(
            track_id="t2",
            duration_catalog_sec=120.0,
            downbeats_sec=[0.0, 1.875, 3.75],
            beats_per_bar=4,
            incoming_anchor_catalog_sec=0.0,
            xfade_catalog_sec=CROSSFADE_SEC,
            ramp_catalog_sec=TEMPO_RAMP_SEC,
            body_mix_start_sec=100.0,
        )
        # Body in catalog time starts at 0 + 12 + 16 = 28.0 s
        # Body in mix time starts at 100.0 s
        # So a catalog downbeat at 30.0 should be at mix time 102.0 s.
        body_catalog_start = CROSSFADE_SEC + TEMPO_RAMP_SEC  # = 28.0
        assert tracker.state.body_catalog_start_sec == pytest.approx(body_catalog_start)
        assert tracker.state.catalog_to_mix(body_catalog_start) == 100.0
        assert tracker.state.catalog_to_mix(body_catalog_start + 5.0) == 105.0


# ---------------------------------------------------------------------------
# _phase_locked_crossfade()
# ---------------------------------------------------------------------------

class TestPhaseLockedCrossfade:

    def test_mono_overlay_preserves_total_length(self):
        a = _silent_segment(3.0)
        b = _silent_segment(3.0)
        xfade = int(SR * 1.0)
        out = _phase_locked_crossfade(a, b, xfade)
        # Expected len = len(a) + len(b) - xfade_ms ≈ 5 s
        expected_ms = len(a) + len(b) - 1000
        assert abs(len(out) - expected_ms) <= 5  # allow rounding slack

    def test_equal_power_curves_sum_to_unity_in_power(self):
        # Two constant DC segments at 0.5 each — after equal-power xfade
        # the overlap region sums to sqrt(0.25 + 0.25) ≈ 0.707 RMS.
        sr = SR
        a_y = np.full(int(sr * 2), 0.5, dtype=np.float32)
        b_y = np.full(int(sr * 2), 0.5, dtype=np.float32)
        a = AudioSegment(
            data=(a_y * 32000).astype(np.int16).tobytes(),
            sample_width=2, frame_rate=sr, channels=1,
        )
        b = AudioSegment(
            data=(b_y * 32000).astype(np.int16).tobytes(),
            sample_width=2, frame_rate=sr, channels=1,
        )
        xfade = sr
        out = _phase_locked_crossfade(a, b, xfade)
        out_y = main_module._segment_to_numpy(out)
        # Sample the middle of the overlap (avoid the 64-sample guard zones)
        mid = len(a_y) - xfade // 2
        sample = out_y[mid]
        # cos(π/4) + sin(π/4) = √2 ≈ 1.414, times 0.5 = 0.707
        assert sample == pytest.approx(0.707, abs=0.02)

    def test_xfade_samples_capped_at_segment_lengths(self):
        a = _silent_segment(0.5)
        b = _silent_segment(0.5)
        # Asking for 5 s overlap on 0.5-s segments must not crash; the
        # function clamps to min length.
        out = _phase_locked_crossfade(a, b, int(SR * 5.0))
        # Lengths shouldn't grow beyond sum of inputs
        assert len(out) <= len(a) + len(b)


# ---------------------------------------------------------------------------
# Integration — synthesised clicks rendered through build_mix
# ---------------------------------------------------------------------------

def _track_entry(path: str, bpm: float, duration_sec: float,
                 first_db_sec: float = 0.0, sr: int = SR) -> dict:
    """Build a v2-style track dict for build_mix()."""
    _, downbeats = _click_track(bpm, duration_sec, first_db_sec, sr=sr)
    beats = np.array(downbeats, dtype=float)
    return {
        "path": path,
        "display_name": f"click-{bpm}",
        "bpm": bpm,
        "beats": beats,
        "downbeats_sec": downbeats,
        "beats_per_bar": 4,
        "duration_sec": duration_sec,
        "beatgrid_source": "synthetic",
        "camelot_key": "8A",
        "genre": "techno",
        "_internal_segment": _click_segment(bpm, duration_sec, sr=sr),
    }


class TestBuildMixIntegration:

    def test_two_click_tracks_render_without_error(self, capsys):
        """Two-track mix through the full build_mix path. Asserts the mix
        actually renders, the phrase-tier log fires, and the transition
        records a sensible start_sec."""
        tracks = [
            _track_entry("a.wav", bpm=128.0, duration_sec=60.0),
            _track_entry("b.wav", bpm=128.0, duration_sec=60.0),
        ]
        seg_by_path = {t["path"]: t["_internal_segment"] for t in tracks}

        with patch("main.AudioSegment.from_file",
                   side_effect=lambda p, *a, **k: seg_by_path[p]), \
             patch("main._normalize_loudness",
                   side_effect=lambda seg, _t=None: (seg, 0.0)), \
             patch("main._apply_bus_limiter", side_effect=lambda seg: seg), \
             patch("main.change_speed", side_effect=lambda seg, *a, **k: seg), \
             patch("main.change_tempo", side_effect=lambda seg, *a, **k: seg):
            mix, transitions = build_mix(tracks, target_duration_sec=None)

        out = capsys.readouterr().out
        # Phase-lock anchor line printed
        assert "Anchor:" in out
        # Each track has a transition entry
        assert len(transitions) == 2
        # Second track must start before the end of the rendered mix
        assert 0.0 < transitions[1]["start_sec"] < len(mix) / 1000.0
        assert transitions[1]["phrase_tier"] in {"16-bar", "8-bar", "4-bar",
                                                  "downbeat", "fallback"}

    def test_post_render_click_alignment_within_tolerance(self):
        """Render two click trains, then verify the kicks in the rendered
        overlap region stay within 20 ms of each other. We use identical
        128 BPM so no tempo stretch is required; the test isolates phase
        lock from time-stretch artefacts."""
        tracks = [
            _track_entry("a.wav", bpm=128.0, duration_sec=60.0),
            _track_entry("b.wav", bpm=128.0, duration_sec=60.0),
        ]
        seg_by_path = {t["path"]: t["_internal_segment"] for t in tracks}

        with patch("main.AudioSegment.from_file",
                   side_effect=lambda p, *a, **k: seg_by_path[p]), \
             patch("main._normalize_loudness",
                   side_effect=lambda seg, _t=None: (seg, 0.0)), \
             patch("main._apply_bus_limiter", side_effect=lambda seg: seg), \
             patch("main.change_speed", side_effect=lambda seg, *a, **k: seg), \
             patch("main.change_tempo", side_effect=lambda seg, *a, **k: seg):
            mix, transitions = build_mix(tracks, target_duration_sec=None)

        # Extract the rendered mix as numpy
        mix_y = main_module._segment_to_numpy(mix).astype(np.float32)
        sr = mix.frame_rate

        # Detect impulses (clicks) by simple peak picking
        thresh = 0.2 * float(np.max(np.abs(mix_y)) or 1.0)
        peaks = np.where(np.abs(mix_y) > thresh)[0]
        if peaks.size == 0:
            pytest.skip("rendered mix has no detectable clicks")

        # Find peaks near the overlap region
        xfade_start_sample = int(transitions[1]["start_sec"] * sr)
        xfade_end_sample = xfade_start_sample + CROSSFADE_SEC * sr
        in_overlap = peaks[(peaks >= xfade_start_sample) & (peaks <= xfade_end_sample)]
        if in_overlap.size == 0:
            pytest.skip("no peaks in overlap region (mix too short)")

        # In a phase-locked overlap of two identical 128 BPM click trains,
        # the clicks from both tracks should land at the same sample. We
        # cluster consecutive peaks (within ~3 ms = same hit) and check
        # that inter-cluster spacing is a clean multiple of the bar period.
        bar_period_samples = int(round((60.0 / 128.0) * 4.0 * sr))
        # Cluster peaks within 0.005 s of each other
        cluster_window = int(0.005 * sr)
        clusters: list[int] = []
        for p in in_overlap:
            if not clusters or p - clusters[-1] > cluster_window:
                clusters.append(int(p))
        # Differences between consecutive clusters should be ≈ bar_period
        # within ±20 ms (our phase-lock tolerance).
        tolerance_samples = int(0.020 * sr)
        for prev, nxt in zip(clusters, clusters[1:]):
            diff = nxt - prev
            # diff should be near k * bar_period for small k
            k = max(1, round(diff / bar_period_samples))
            assert abs(diff - k * bar_period_samples) <= tolerance_samples, (
                f"click spacing {diff} samples deviates from k={k} bars "
                f"({k * bar_period_samples}) by more than 20 ms"
            )
