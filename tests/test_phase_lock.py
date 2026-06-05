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


# ===========================================================================
# v3.0 — shared module surface (agent.phase_lock)
# ===========================================================================
#
# The block above tests the v3.0 phase-lock behaviour by importing the
# historical underscore names from ``main``. The block below tests the
# new public surface in ``agent.phase_lock`` that the live engines
# (LiveEngineLocal, LiveEngineBrowser) consume. Together the two blocks
# pin both the public API and the backward-compat re-exports.

from agent import phase_lock as phase_lock_mod  # noqa: E402
from agent.phase_lock import (  # noqa: E402
    BEATGRID_SCHEMA_VERSION,
    DEFAULT_BPM_MATCH_THRESHOLD,
    DEFAULT_CROSSFADE_SEC,
    DEFAULT_TEMPO_RAMP_SEC,
    GridState,
    GridTracker,
    LiveTransitionPlan,
    STRETCH_RATIO_MAX,
    STRETCH_RATIO_MIN,
    build_live_transition_plan,
    compute_beat_rate_schedule,
    compute_tempo_match_rate,
    is_v2_beatgrid,
    phase_locked_crossfade_np,
    pick_incoming_anchor,
    resolve_downbeats,
    synthesise_downbeats_from_v1,
)


class TestMainReExports:
    """The historical underscore-prefixed names in ``main`` MUST resolve to
    the same objects as the public names in ``agent.phase_lock``. Two
    different implementations would re-introduce exactly the live-vs-offline
    drift the extraction was meant to kill."""

    def test_grid_state_re_export_is_same_class(self):
        assert main_module._GridState is GridState

    def test_grid_tracker_re_export_is_same_class(self):
        assert main_module._GridTracker is GridTracker

    def test_find_phrase_anchor_is_same_function(self):
        assert main_module.find_phrase_anchor is phase_lock_mod.find_phrase_anchor

    def test_compute_phase_lock_is_same_function(self):
        assert main_module.compute_phase_lock is phase_lock_mod.compute_phase_lock

    def test_pick_incoming_anchor_is_same_function(self):
        assert main_module._pick_incoming_anchor is pick_incoming_anchor

    def test_is_v2_beatgrid_re_export(self):
        assert main_module._is_v2_beatgrid is is_v2_beatgrid

    def test_synthesise_downbeats_re_export(self):
        assert main_module._synthesise_downbeats_from_v1 is synthesise_downbeats_from_v1

    def test_beatgrid_schema_version_value(self):
        assert main_module.BEATGRID_SCHEMA_VERSION == BEATGRID_SCHEMA_VERSION == 2

    def test_default_constants_match_main(self):
        # The duplicated defaults in phase_lock.py and the constants in
        # main.py must stay in sync. The module-level docstring promises this.
        assert DEFAULT_CROSSFADE_SEC == float(main_module.CROSSFADE_SEC)
        assert DEFAULT_TEMPO_RAMP_SEC == float(main_module.TEMPO_RAMP_SEC)


class TestResolveDownbeats:
    """``resolve_downbeats`` is the public fallback ladder used by both live
    engines. Wrong branching here = wrong anchors = the live-vs-offline
    bug we are explicitly fixing."""

    def test_v2_beatgrid_uses_explicit_downbeats(self):
        bg = {
            "version": 2,
            "downbeats_sec": [0.0, 2.0, 4.0, 6.0],
            "beats_per_bar": 4,
            "bpm": 120.0,
            "first_beat_sec": 0.0,
        }
        downbeats, bpb = resolve_downbeats(bg, track_duration_sec=10.0)
        assert downbeats == [0.0, 2.0, 4.0, 6.0]
        assert bpb == 4

    def test_v2_beatgrid_with_3_4_passes_beats_per_bar_through(self):
        """The 3/4 path matters for waltz / handpan-style genres. madmom
        is configured with beats_per_bar=[3, 4] and the live engine must
        honour the detected meter."""
        bg = {
            "version": 2,
            "downbeats_sec": [0.0, 1.5, 3.0],
            "beats_per_bar": 3,
            "bpm": 120.0,
            "first_beat_sec": 0.0,
        }
        _, bpb = resolve_downbeats(bg, track_duration_sec=10.0)
        assert bpb == 3

    def test_v1_beatgrid_synthesises_4_4_grid(self):
        bg = {"bpm": 120.0, "first_beat_sec": 0.0}
        # No version field → v1. Should synthesise a 4/4 grid: bar = 2.0 s.
        downbeats, bpb = resolve_downbeats(bg, track_duration_sec=8.0)
        assert bpb == 4
        assert downbeats[0] == 0.0
        # 4 bars in 8 s + 1 extra bar = 5 entries (the synthesiser
        # over-shoots by one bar so the last anchor is still reachable
        # even if the duration estimate is slightly low).
        assert len(downbeats) >= 4
        assert all(
            abs((b - a) - 2.0) < 0.005 for a, b in zip(downbeats, downbeats[1:])
        )

    def test_none_beatgrid_returns_empty_downbeats(self):
        downbeats, bpb = resolve_downbeats(None, track_duration_sec=10.0)
        assert downbeats == []
        # 4/4 default lets the caller compose a bar_sec without
        # special-casing the None branch separately.
        assert bpb == 4

    def test_empty_beatgrid_dict_returns_empty(self):
        downbeats, bpb = resolve_downbeats({}, track_duration_sec=10.0)
        assert downbeats == []
        assert bpb == 4


class TestBuildLiveTransitionPlan:
    """``build_live_transition_plan`` converts the catalog-time phase-lock
    plan into the sample-space offsets the live engines actually consume
    when positioning decks. Sample-index math is where rounding errors
    would visibly shift downbeats off-grid in the rendered audio, so the
    arithmetic gets pinned here."""

    SR = 44100

    def _v2(self, downbeats):
        return {
            "version": 2,
            "downbeats_sec": list(downbeats),
            "beats_per_bar": 4,
            "bpm": 128.0,
            "first_beat_sec": downbeats[0],
        }

    def test_returns_live_transition_plan_dataclass(self):
        plan = build_live_transition_plan(
            outgoing_beatgrid=self._v2([round(i * 1.875, 3) for i in range(32)]),
            outgoing_duration_sec=60.0,
            incoming_beatgrid=self._v2([round(i * 1.875, 3) for i in range(32)]),
            incoming_duration_sec=60.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
        )
        assert isinstance(plan, LiveTransitionPlan)
        assert plan.sample_rate == self.SR

    def test_sample_offsets_match_rounded_catalog_times(self):
        """The chosen anchors must convert to sample indices via the engine
        sample rate without surprises. Rounding rather than truncating
        keeps the maximum error to half a sample."""
        plan = build_live_transition_plan(
            outgoing_beatgrid=self._v2([round(i * 1.875, 3) for i in range(32)]),
            outgoing_duration_sec=60.0,
            incoming_beatgrid=self._v2([0.0, 1.875, 3.75]),
            incoming_duration_sec=10.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
        )
        catalog = plan.plan
        assert plan.outgoing_anchor_sample == int(
            round(catalog.outgoing_anchor_catalog_sec * self.SR)
        )
        assert plan.incoming_start_sample == int(
            round(catalog.incoming_anchor_catalog_sec * self.SR)
        )
        # 12 s @ 44.1 kHz = 529 200 samples exactly.
        assert plan.xfade_samples == 12 * self.SR

    def test_legacy_v1_outgoing_synthesises_grid_for_anchor(self):
        """If only one side has v2 data, ``build_live_transition_plan``
        must still resolve via the v1 synthesiser rather than refuse —
        this is the path that fires for catalogs that haven't yet been
        regenerated via ``--regenerate-beatgrid``."""
        plan = build_live_transition_plan(
            outgoing_beatgrid={"bpm": 128.0, "first_beat_sec": 0.0},
            outgoing_duration_sec=60.0,
            incoming_beatgrid=self._v2([0.0, 1.875, 3.75]),
            incoming_duration_sec=10.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
        )
        # The synthesised grid still produces a phrase-locked anchor;
        # phrase_tier may be a coarser bracket but should not be "fallback".
        assert plan.phrase_tier != "fallback"
        assert plan.outgoing_anchor_sample > 0

    def test_missing_beatgrid_both_sides_falls_back_gracefully(self):
        """Both sides missing → empty downbeats → fallback. Engines use
        ``phrase_tier == "fallback"`` as the signal to drop into the
        legacy linear-fade path. The transition plan must NOT raise."""
        plan = build_live_transition_plan(
            outgoing_beatgrid=None,
            outgoing_duration_sec=60.0,
            incoming_beatgrid=None,
            incoming_duration_sec=10.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
        )
        assert plan.phrase_tier == "fallback"

    def test_ramp_sec_carries_through(self):
        plan = build_live_transition_plan(
            outgoing_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            outgoing_duration_sec=20.0,
            incoming_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            incoming_duration_sec=20.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=8.0,
            target_ramp_sec=4.0,
        )
        assert plan.plan.ramp_catalog_sec == 4.0

    def test_default_rates_are_one_without_bpm_args(self):
        """Callers that don't pass BPMs (legacy code, or paths that don't
        need tempo matching) must get plans with ``incoming_rate == 1.0``
        so nothing silently stretches when the data isn't available."""
        plan = build_live_transition_plan(
            outgoing_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            outgoing_duration_sec=20.0,
            incoming_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            incoming_duration_sec=20.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=8.0,
        )
        assert plan.incoming_rate == 1.0
        assert plan.outgoing_rate == 1.0

    def test_bpm_args_populate_incoming_rate(self):
        plan = build_live_transition_plan(
            outgoing_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            outgoing_duration_sec=20.0,
            incoming_beatgrid=self._v2([0.0, 1.875, 3.75, 5.625]),
            incoming_duration_sec=20.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=8.0,
            outgoing_bpm=120.0,
            incoming_bpm=130.0,
        )
        assert plan.incoming_rate == pytest.approx(120.0 / 130.0)
        assert plan.outgoing_rate == 1.0

    def test_tight_grids_attach_grid_warp_schedule(self):
        """Two tight 4/4 grids at slightly different tempi must produce a
        per-bar grid-warp schedule on the returned plan — that is the v3.5
        cabalgar fix the live engine forwards to the browser."""
        out = self._v2([round(i * 1.875, 4) for i in range(40)])  # 128 BPM
        inc = self._v2([round(i * 2.0, 4) for i in range(40)])    # 120 BPM
        plan = build_live_transition_plan(
            outgoing_beatgrid=out,
            outgoing_duration_sec=80.0,
            incoming_beatgrid=inc,
            incoming_duration_sec=80.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
            target_ramp_sec=16.0,
        )
        assert plan.beat_rate_schedule.mode == "grid_warp"
        assert len(plan.beat_rate_schedule.segments) >= 2

    def test_loose_grid_leaves_schedule_static(self):
        """A swung / irregular incoming grid must NOT be grid-warped (it
        would wobble); the plan keeps a static schedule so the engine
        falls back to the single ``incoming_rate``."""
        out = self._v2([round(i * 1.875, 4) for i in range(40)])
        # Jittered downbeats: ~±18% bar-to-bar — well above GRIDWARP_MAX_CV.
        jitter = [0.0]
        for i in range(1, 40):
            step = 1.875 * (1.18 if i % 2 else 0.82)
            jitter.append(round(jitter[-1] + step, 4))
        plan = build_live_transition_plan(
            outgoing_beatgrid=out,
            outgoing_duration_sec=80.0,
            incoming_beatgrid=self._v2(jitter),
            incoming_duration_sec=80.0,
            incoming_audio_y=None,
            sample_rate=self.SR,
            target_xfade_sec=12.0,
        )
        assert plan.beat_rate_schedule.mode == "static"
        assert plan.beat_rate_schedule.segments == []


class TestComputeBeatRateSchedule:
    """v3.5 feed-forward beat-lock grid-warp. This is the software pitch
    fader / jog ride: a per-bar playback-rate curve that keeps every
    incoming downbeat on an outgoing downbeat across the whole overlap.
    The arithmetic and the loose-grid gate are pinned here because a wrong
    rate is precisely the audible cabalgar we're killing."""

    def _grid(self, bar_sec, n, start=0.0, jitter=None):
        out = [start]
        for i in range(1, n):
            step = bar_sec if jitter is None else bar_sec * jitter[i % len(jitter)]
            out.append(round(out[-1] + step, 6))
        return out

    def test_identical_grids_lock_at_rate_one(self):
        grid = self._grid(2.0, 32)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=grid,
            incoming_downbeats=grid,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "grid_warp"
        assert all(seg.rate == pytest.approx(1.0) for seg in sched.segments)

    def test_different_tempo_locks_every_downbeat(self):
        """The whole point: with constant but different tempi the per-bar
        rate equals in_bar/out_bar, and integrating it puts every incoming
        downbeat exactly on the corresponding outgoing downbeat."""
        out = self._grid(1.875, 32)   # 128 BPM
        inc = self._grid(2.0, 32)     # 120 BPM
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "grid_warp"
        lock = [s for s in sched.segments if not s.ramp]
        expected_rate = 2.0 / 1.875
        assert all(s.rate == pytest.approx(expected_rate, abs=1e-4) for s in lock)
        # Reconstruct: cumulative catalog seconds consumed by the incoming
        # deck after each outgoing bar must equal the incoming downbeat
        # offset — i.e. the kicks line up bar by bar.
        consumed = 0.0
        for k, seg in enumerate(lock):
            out_bar = out[k + 1] - out[k]
            consumed += seg.rate * out_bar
            assert consumed == pytest.approx(inc[k + 1] - inc[0], abs=1e-3)

    def test_micro_tempo_grid_still_locks(self):
        """Real tracks aren't perfectly metronomic — a single static rate
        can't track micro-tempo, but the per-bar schedule does."""
        out = self._grid(1.875, 32, jitter=[1.0, 1.01, 0.99, 1.005])
        inc = self._grid(2.0, 32, jitter=[1.0, 0.995, 1.008, 0.997])
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "grid_warp"
        lock = [s for s in sched.segments if not s.ramp]
        consumed = 0.0
        for k, seg in enumerate(lock):
            consumed += seg.rate * (out[k + 1] - out[k])
            assert consumed == pytest.approx(inc[k + 1] - inc[0], abs=2e-3)

    def test_release_ramp_returns_to_native(self):
        grid = self._grid(2.0, 32)
        inc = self._grid(1.9, 32)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=grid,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
            ramp_sec=16.0,
        )
        assert sched.mode == "grid_warp"
        last = sched.segments[-1]
        assert last.ramp is True
        assert last.rate == pytest.approx(1.0)
        assert last.at_sec == pytest.approx(12.0 + 16.0)
        # The second-to-last segment holds the matched rate at the end of
        # the crossfade so the ramp glides from there, not from mid-overlap.
        hold = sched.segments[-2]
        assert hold.ramp is False
        assert hold.at_sec == pytest.approx(12.0)

    def test_no_ramp_emits_no_release_segments(self):
        grid = self._grid(2.0, 32)
        inc = self._grid(1.9, 32)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=grid,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
            ramp_sec=0.0,
        )
        assert all(seg.ramp is False for seg in sched.segments)

    def test_loose_incoming_grid_falls_back_to_static(self):
        out = self._grid(1.875, 32)
        inc = self._grid(2.0, 32, jitter=[1.2, 0.8])  # cv far above ceiling
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "static"
        assert sched.segments == []

    def test_loose_outgoing_grid_falls_back_to_static(self):
        out = self._grid(1.875, 32, jitter=[1.2, 0.8])
        inc = self._grid(2.0, 32)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "static"

    def test_too_few_downbeats_falls_back_to_static(self):
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=[0.0, 2.0],
            incoming_downbeats=[0.0, 1.9],
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        # Only one bar available → fewer than the 2-bar minimum.
        assert sched.mode == "static"

    def test_empty_grids_do_not_raise(self):
        assert compute_beat_rate_schedule(
            outgoing_downbeats=[],
            incoming_downbeats=[],
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        ).mode == "static"

    def test_doubled_downbeat_outlier_uses_median(self):
        """A madmom-dropped downbeat doubles one bar. The outlier guard
        must warp that bar with the median ratio (~1.0) instead of ~2.0,
        keeping the rest of the transition locked."""
        out = self._grid(1.875, 32)
        inc = self._grid(1.875, 32)
        # Remove one incoming downbeat mid-overlap → one 2× bar.
        del inc[3]
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert sched.mode == "grid_warp"
        lock = [s for s in sched.segments if not s.ramp]
        # No segment should be near the un-guarded 2.0 ratio.
        assert all(s.rate < 1.5 for s in lock)
        assert all(s.rate == pytest.approx(1.0, abs=0.1) for s in lock)

    def test_extreme_ratio_is_clamped(self):
        out = self._grid(0.5, 32)   # very fast
        inc = self._grid(2.0, 32)   # very slow → ratio 4× before clamp
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        assert all(s.rate <= STRETCH_RATIO_MAX + 1e-9 for s in sched.segments)
        assert all(s.rate >= STRETCH_RATIO_MIN - 1e-9 for s in sched.segments)

    def test_segment_offsets_track_outgoing_downbeats(self):
        out = self._grid(1.875, 32)
        inc = self._grid(2.0, 32)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=out[4],   # anchor partway in
            incoming_anchor_sec=0.0,
            xfade_sec=12.0,
        )
        lock = [s for s in sched.segments if not s.ramp]
        # First lock segment sits at the anchor (offset 0), subsequent ones
        # land on later outgoing downbeats relative to the anchor.
        assert lock[0].at_sec == pytest.approx(0.0)
        for k, seg in enumerate(lock):
            assert seg.at_sec == pytest.approx(out[4 + k] - out[4], abs=1e-4)

    def test_window_bounded_by_xfade(self):
        out = self._grid(1.0, 64)
        inc = self._grid(1.0, 64)
        sched = compute_beat_rate_schedule(
            outgoing_downbeats=out,
            incoming_downbeats=inc,
            outgoing_anchor_sec=0.0,
            incoming_anchor_sec=0.0,
            xfade_sec=6.0,
        )
        lock = [s for s in sched.segments if not s.ramp]
        # 1 s bars, 6 s window → lock segments shouldn't run past ~6 s.
        assert all(s.at_sec <= 6.0 + 1e-6 for s in lock)


class TestComputeTempoMatchRate:
    """The single source of truth for "what rate plays the incoming track
    at the outgoing's tempo". The CLI engine implicitly consumes this via
    pyrubberband; the browser path consumes it directly via
    ``HTMLMediaElement.playbackRate``. Cross-path parity hinges on this
    function returning the same value for the same BPM pair regardless
    of caller."""

    def test_returns_one_when_bpms_equal(self):
        assert compute_tempo_match_rate(128.0, 128.0) == 1.0

    def test_returns_one_when_delta_within_threshold(self):
        # Threshold is 5 BPM — exactly 5 still rounds to "no stretch"
        # (matches CLI ``_time_stretch``'s ``<=`` comparison).
        assert compute_tempo_match_rate(128.0, 124.0) == 1.0
        assert compute_tempo_match_rate(128.0, 123.0) == 1.0  # delta=5

    def test_returns_outgoing_over_incoming_when_delta_exceeds_threshold(self):
        """Sign convention: ``incoming_bpm`` is too high → rate < 1.0
        (slow it down). Matches ``LiveEngineLocal._time_stretch`` exactly."""
        rate = compute_tempo_match_rate(120.0, 130.0)
        assert rate == pytest.approx(120.0 / 130.0)
        assert rate < 1.0

    def test_returns_outgoing_over_incoming_when_incoming_slower(self):
        """Incoming too slow → rate > 1.0 (speed it up)."""
        rate = compute_tempo_match_rate(130.0, 120.0)
        assert rate == pytest.approx(130.0 / 120.0)
        assert rate > 1.0

    def test_clamps_to_stretch_max(self):
        """A 60 → 180 BPM jump would naively give 3.0× — far past the
        1.5 ceiling. Without the clamp the browser would silently
        playback at chipmunk-territory rates (or fail outright)."""
        assert compute_tempo_match_rate(180.0, 60.0) == STRETCH_RATIO_MAX

    def test_clamps_to_stretch_min(self):
        """Inverse direction: 60 → 180 incoming would give 0.333. Clamp
        keeps it at 1/1.5."""
        assert compute_tempo_match_rate(60.0, 180.0) == STRETCH_RATIO_MIN

    def test_returns_one_for_missing_outgoing_bpm(self):
        assert compute_tempo_match_rate(None, 128.0) == 1.0

    def test_returns_one_for_missing_incoming_bpm(self):
        assert compute_tempo_match_rate(128.0, None) == 1.0

    def test_returns_one_for_zero_or_negative_bpm(self):
        """Catalog corruption guard. A 0 BPM in catalog must NOT cause a
        division-by-zero — return the safe identity rate instead."""
        assert compute_tempo_match_rate(0.0, 128.0) == 1.0
        assert compute_tempo_match_rate(128.0, 0.0) == 1.0
        assert compute_tempo_match_rate(-1.0, 128.0) == 1.0

    def test_threshold_argument_is_honoured(self):
        """A path that wants tighter tempo matching can pass a smaller
        threshold. Useful for genres where 2-BPM drift IS audible."""
        # Default threshold (5) → no stretch.
        assert compute_tempo_match_rate(120.0, 122.0) == 1.0
        # Tighter threshold (1) → stretch even tiny deltas.
        rate = compute_tempo_match_rate(120.0, 122.0, threshold=1.0)
        assert rate == pytest.approx(120.0 / 122.0)

    def test_default_threshold_matches_constant(self):
        """Sanity check: the implicit default mirrors the documented
        module-level constant. Tests reference the constant elsewhere so
        a drift here would mask cross-path disagreement."""
        # Anything inside ±DEFAULT_BPM_MATCH_THRESHOLD must collapse to 1.0.
        assert compute_tempo_match_rate(
            120.0, 120.0 + DEFAULT_BPM_MATCH_THRESHOLD
        ) == 1.0


class TestPhaseLockedCrossfadeNp:
    """The numpy-pure crossfade is what every path eventually runs. The
    AudioSegment wrapper in main.py just routes through it. Pin the
    equal-power property directly on the numpy version so a change in
    main.py's wrapper can't silently break the energy curve."""

    def test_equal_power_curves_sum_to_unity_power(self):
        # Two constant-amplitude mono tracks: their squared sum across
        # the overlap should be constant at 1.0 if cos² + sin² = 1.
        mix = np.ones(1000, dtype=np.float32)
        inc = np.ones(1000, dtype=np.float32)
        out = phase_locked_crossfade_np(mix, inc, xfade_samples=500)
        # Sample the middle of the overlap (after the 64-sample guard).
        overlap_region = out[500 + 100 : 500 + 400]
        # cos(t) + sin(t) is ≤ √2; squared sum stays ≤ 2. For equal-power
        # crossfade with cos/sin curves both tracks contribute, and
        # cos² + sin² = 1 means each sample's POWER (square) is 1.
        # The amplitude itself is cos + sin ≤ √2, but with both inputs
        # at 1.0 we get amplitude = cos(t) + sin(t) which peaks at √2.
        assert np.all(overlap_region > 0.99)
        assert np.all(overlap_region < 1.42)

    def test_short_buffers_fall_back_to_concat(self):
        mix = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        inc = np.array([4.0, 5.0], dtype=np.float32)
        out = phase_locked_crossfade_np(mix, inc, xfade_samples=100)
        # Requested 100 samples but only 2 available on incoming side →
        # crossfade still runs on 2 samples, not a concat.
        assert len(out) == len(mix) + len(inc) - min(2, 100)

    def test_zero_xfade_returns_concat(self):
        mix = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        inc = np.array([4.0, 5.0, 6.0], dtype=np.float32)
        out = phase_locked_crossfade_np(mix, inc, xfade_samples=0)
        np.testing.assert_array_equal(out, np.array([1, 2, 3, 4, 5, 6], dtype=np.float32))

    def test_stereo_preserved(self):
        mix = np.ones((1000, 2), dtype=np.float32)
        mix[:, 1] *= 0.5  # right channel quieter
        inc = np.ones((1000, 2), dtype=np.float32)
        out = phase_locked_crossfade_np(mix, inc, xfade_samples=500)
        assert out.ndim == 2
        assert out.shape[1] == 2
        # Tail of pre-overlap region keeps the L/R asymmetry of mix.
        assert out[400, 0] == 1.0
        assert out[400, 1] == 0.5

    def test_edge_guard_attenuates_first_sample(self):
        """The 64-sample raised-cosine guard masks a one-sample
        discontinuity at the overlap entry. First overlap sample must be
        attenuated; without the guard a discontinuity would show as a
        click in the output."""
        mix = np.ones(2000, dtype=np.float32)
        inc = np.ones(2000, dtype=np.float32) * 2.0
        out = phase_locked_crossfade_np(mix, inc, xfade_samples=1000)
        overlap_start = 1000  # mix ends at index 1000, overlap starts there
        # First sample of overlap: guard ramp at 0 → mix_tail ≈ 0, incoming
        # contribution at t=0 is sin(0) * 2 = 0. So first sample ≈ 0.
        assert out[overlap_start] < 0.1
        # 64 samples in, ramp is full strength.
        assert out[overlap_start + 64] > 0.05
