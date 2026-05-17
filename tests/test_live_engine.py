"""
Unit tests for agent/live_engine.py.

sounddevice and audio I/O are mocked throughout — no hardware required.
Audio buffers are tiny numpy arrays (1–2 seconds of silence) for speed.
"""
from __future__ import annotations

import threading
import time
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agent.live_engine import (
    APPROACHING_CF,
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngine,
    _SAMPLE_RATE,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TINY_SR = _SAMPLE_RATE  # use real SR so time math works
TRACK_DUR = 3  # very short test tracks (3 s)


def _silent_audio(duration_sec: float = TRACK_DUR) -> np.ndarray:
    """Return a silent stereo float32 array of the given duration."""
    n = int(duration_sec * TINY_SR)
    return np.zeros((n, 2), dtype=np.float32)


def _make_playlist(n: int = 2, bpm: float = 120.0) -> list[dict]:
    return [
        {
            "id": f"track-{i}",
            "display_name": f"Track {i}",
            "file": f"tracks/test/track{i}.wav",
            "bpm": bpm,
            "camelot_key": "8A",
            "duration_sec": float(TRACK_DUR),
        }
        for i in range(1, n + 1)
    ]


@pytest.fixture
def mock_sd():
    """Patch sounddevice so no audio hardware is needed."""
    class _FakeStream:
        def __init__(self, *a, **kw):
            self._cb = kw.get("callback")

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    fake_sd = MagicMock()
    fake_sd.OutputStream.side_effect = _FakeStream

    with patch("agent.live_engine.sd", fake_sd), \
         patch("agent.live_engine._SD_AVAILABLE", True):
        yield fake_sd


@pytest.fixture
def mock_load_audio():
    """Patch LiveEngine._load_audio to return silent numpy arrays."""
    with patch.object(
        LiveEngine, "_load_audio", return_value=_silent_audio()
    ) as m:
        yield m


@pytest.fixture
def mock_prestretch():
    """Patch LiveEngine._time_stretch to be a no-op."""
    with patch.object(
        LiveEngine, "_time_stretch", side_effect=lambda audio, *a, **kw: audio
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------

def test_engine_initialises_idle(mock_sd, mock_load_audio):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    assert engine.get_state()["state"] == "idle"
    assert engine._audio is None  # no audio loaded until play() is called


# ---------------------------------------------------------------------------
# play() — TRACK_STARTED event
# ---------------------------------------------------------------------------

def test_play_emits_track_started(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()

    ev = q.get(timeout=1)
    assert ev["type"] == TRACK_STARTED
    assert ev["track"]["display_name"] == "Track 1"

    engine.stop()


def test_play_empty_playlist_emits_session_ended(mock_sd, mock_load_audio):
    q = Queue()
    engine = LiveEngine([], q)
    engine.play()

    ev = q.get(timeout=1)
    assert ev["type"] == SESSION_ENDED


# ---------------------------------------------------------------------------
# get_state()
# ---------------------------------------------------------------------------

def test_get_state_after_play(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)  # consume TRACK_STARTED

    state = engine.get_state()
    assert state["state"] == "playing"
    assert state["current_track"]["display_name"] == "Track 1"
    assert state["next_track"]["display_name"] == "Track 2"
    assert state["playlist_remaining"] == 1

    engine.stop()


# ---------------------------------------------------------------------------
# extend_track()
# ---------------------------------------------------------------------------

def test_extend_track_increments_extend_samples(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)  # TRACK_STARTED

    result = engine.extend_track(10)
    assert "10s" in result
    assert engine._extend_samples == 10 * _SAMPLE_RATE

    engine.stop()


def test_extend_track_accumulates(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    engine.extend_track(5)
    engine.extend_track(3)
    assert engine._extend_samples == 8 * _SAMPLE_RATE

    engine.stop()


# ---------------------------------------------------------------------------
# skip_track()
# ---------------------------------------------------------------------------

def test_skip_track_advances_idx(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(3), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    # drain TRACK_STARTED
    q.get(timeout=1)

    result = engine.skip_track()
    assert "Track 2" in result
    assert engine._idx == 1

    engine.stop()


def test_skip_track_on_last_returns_message(mock_sd, mock_load_audio, mock_prestretch):
    playlist = _make_playlist(1)
    q = Queue()
    engine = LiveEngine(playlist, q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    result = engine.skip_track()
    assert "No next track" in result

    engine.stop()


# ---------------------------------------------------------------------------
# queue_swap()
# ---------------------------------------------------------------------------

def test_queue_swap_rejects_past_position(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(3), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    result = engine.queue_swap(1, "some-id")  # position 1 is current
    assert "not a future slot" in result

    engine.stop()


def test_queue_swap_rejects_unknown_track(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(3), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    with patch("agent.live_engine._load_catalog", return_value=[]):
        result = engine.queue_swap(3, "nonexistent-id")
    assert "not found" in result

    engine.stop()


def test_queue_swap_replaces_slot(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(3), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    new_track = {"id": "bridge", "display_name": "Bridge", "file": "t.wav", "bpm": 125.0}
    with patch("agent.live_engine._load_catalog", return_value=[new_track]):
        result = engine.queue_swap(3, "bridge")
    assert "Bridge" in result
    assert engine.playlist[2]["display_name"] == "Bridge"

    engine.stop()


# ---------------------------------------------------------------------------
# crossfade_now() — state guard
# ---------------------------------------------------------------------------

def test_crossfade_now_requires_playing_state(mock_sd, mock_load_audio):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    # engine is idle
    result = engine.crossfade_now()
    assert "Cannot crossfade" in result


def test_crossfade_now_returns_error_on_last_track(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(1), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)

    result = engine.crossfade_now()
    assert "No next track" in result

    engine.stop()


# ---------------------------------------------------------------------------
# _cf_point_samples() — hot cue OUT integration
# ---------------------------------------------------------------------------

def test_cf_point_uses_hot_cue_out():
    q = Queue()
    track = {
        "display_name": "T",
        "file": "t.wav",
        "bpm": 120.0,
        "duration_sec": 60.0,
        "hot_cues": [{"type": "out", "position_sec": 45.0, "label": "OUT"}],
    }
    engine = LiveEngine([track], q)
    engine._audio = _silent_audio(60)
    engine._extend_samples = 0
    samples = engine._cf_point_samples(track)
    assert samples == int(45.0 * _SAMPLE_RATE)


def test_cf_point_defaults_without_hot_cue():
    q = Queue()
    track = {
        "display_name": "T",
        "file": "t.wav",
        "bpm": 120.0,
        "duration_sec": 60.0,
    }
    engine = LiveEngine([track], q, crossfade_sec=12)
    engine._audio = _silent_audio(60)
    engine._extend_samples = 0
    samples = engine._cf_point_samples(track)
    expected = int((60.0 - 12 - 5) * _SAMPLE_RATE)
    assert samples == expected


# ---------------------------------------------------------------------------
# _in_point_of() — hot cue IN
# ---------------------------------------------------------------------------

def test_in_point_uses_hot_cue_in():
    track = {
        "hot_cues": [{"type": "in", "position_sec": 4.2, "label": "IN"}],
    }
    result = LiveEngine._in_point_of(track)
    assert result == int(4.2 * _SAMPLE_RATE)


def test_in_point_defaults_to_zero():
    result = LiveEngine._in_point_of({"hot_cues": []})
    assert result == 0


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_sets_idle(mock_sd, mock_load_audio, mock_prestretch):
    q = Queue()
    engine = LiveEngine(_make_playlist(2), q, crossfade_sec=1, approach_warn_sec=1)
    engine.play()
    q.get(timeout=1)
    engine.stop()
    assert engine._state == "idle"


# ===========================================================================
# v3.0 — phase-lock integration
# ===========================================================================
#
# These tests pin the live engine's wiring of agent.phase_lock. They are
# how we will know — going forward — that the live engine and the offline
# render keep producing beat-aligned transitions for the same input. The
# original bug was structural: two different crossfade implementations.
# These tests pin the call sites so a future contributor can't silently
# fork them again.

from agent.live_engine import LiveEngineLocal, XFADE_EDGE_GUARD_SAMPLES  # noqa: E402
from agent.phase_lock import LiveTransitionPlan, PhaseLockPlan  # noqa: E402


def _v2_beatgrid(bpm: float, downbeats_sec: list[float]) -> dict:
    return {
        "version": 2,
        "bpm": bpm,
        "first_beat_sec": downbeats_sec[0],
        "downbeats_sec": list(downbeats_sec),
        "beats_per_bar": 4,
        "source": "madmom",
    }


def _fake_plan(
    *,
    outgoing_anchor_sec: float = 48.0,
    incoming_anchor_sec: float = 0.0,
    xfade_sec: float = 12.0,
    tier: str = "16-bar",
    pickup_skipped: bool = False,
    sample_rate: int = _SAMPLE_RATE,
) -> LiveTransitionPlan:
    cp = PhaseLockPlan(
        outgoing_anchor_catalog_sec=outgoing_anchor_sec,
        incoming_anchor_catalog_sec=incoming_anchor_sec,
        xfade_catalog_sec=xfade_sec,
        ramp_catalog_sec=0.0,
        phrase_tier=tier,
        incoming_pickup_skipped=pickup_skipped,
    )
    return LiveTransitionPlan(
        outgoing_anchor_sample=int(round(outgoing_anchor_sec * sample_rate)),
        incoming_start_sample=int(round(incoming_anchor_sec * sample_rate)),
        xfade_samples=int(round(xfade_sec * sample_rate)),
        sample_rate=sample_rate,
        phrase_tier=tier,
        incoming_pickup_skipped=pickup_skipped,
        plan=cp,
    )


# ---------------------------------------------------------------------------
# _cf_point_samples — anchor ladder (plan → hot cue → duration formula)
# ---------------------------------------------------------------------------

class TestCfPointSamplesAnchorLadder:
    """v3.0 introduced a priority ladder. Confirm each tier wins when it
    should AND that ``_extend_samples`` is honoured at every tier."""

    def _make_engine(self):
        q = Queue()
        engine = LiveEngineLocal(_make_playlist(2), q, crossfade_sec=12)
        engine._audio = _silent_audio(60.0)
        return engine

    def test_plan_outgoing_anchor_wins_over_hot_cue(self):
        engine = self._make_engine()
        engine._transition_plan = _fake_plan(outgoing_anchor_sec=48.0)
        track = {
            "duration_sec": 60.0,
            "hot_cues": [{"type": "out", "position_sec": 55.0}],
        }
        assert engine._cf_point_samples(track) == int(48.0 * _SAMPLE_RATE)

    def test_fallback_tier_drops_to_legacy_path(self):
        """``phrase_tier == "fallback"`` means the phase-lock attempt
        didn't find a real phrase boundary (likely missing v2 data on
        both sides). The legacy hot-cue / duration formula MUST take
        over — silently using a 'fallback' anchor would put us back in
        the off-grid behaviour the user reported."""
        engine = self._make_engine()
        engine._transition_plan = _fake_plan(
            outgoing_anchor_sec=10.0, tier="fallback"
        )
        track = {
            "duration_sec": 60.0,
            "hot_cues": [{"type": "out", "position_sec": 55.0}],
        }
        # Should resolve to the hot cue, not the fallback plan anchor.
        assert engine._cf_point_samples(track) == int(55.0 * _SAMPLE_RATE)

    def test_no_plan_uses_hot_cue(self):
        engine = self._make_engine()
        engine._transition_plan = None
        track = {
            "duration_sec": 60.0,
            "hot_cues": [{"type": "out", "position_sec": 55.0}],
        }
        assert engine._cf_point_samples(track) == int(55.0 * _SAMPLE_RATE)

    def test_no_plan_no_hot_cue_uses_duration_formula(self):
        engine = self._make_engine()
        engine._transition_plan = None
        track = {"duration_sec": 60.0}
        # 60.0 - 12 - 5 = 43.0 seconds (legacy v1 formula).
        assert engine._cf_point_samples(track) == int(43.0 * _SAMPLE_RATE)

    def test_extend_samples_adds_to_plan_anchor(self):
        """The agent's ``extend_track`` tool shifts the cut point. The
        addition must work whether the base anchor came from the plan
        or from a hot cue, otherwise extend_track silently no-ops for
        catalogs that have migrated to v2 beatgrids."""
        engine = self._make_engine()
        engine._transition_plan = _fake_plan(outgoing_anchor_sec=48.0)
        engine._extend_samples = 2 * _SAMPLE_RATE
        track = {"duration_sec": 60.0}
        assert engine._cf_point_samples(track) == int(50.0 * _SAMPLE_RATE)


# ---------------------------------------------------------------------------
# _build_transition_plan_for_next
# ---------------------------------------------------------------------------

class TestBuildTransitionPlan:
    """Pin the wiring from playlist dicts → ``build_live_transition_plan``
    args. The hardest live-vs-offline bugs come from one side passing
    catalog-time fields to a function expecting post-stretch time."""

    def _engine_with_current(self, current_track):
        q = Queue()
        engine = LiveEngineLocal([current_track], q, crossfade_sec=12)
        engine._audio = _silent_audio(60.0)
        return engine

    def test_plan_built_from_v2_beatgrids_returns_real_tier(self):
        # 32 downbeats @ 1.875 s spacing (128 BPM, 4/4) — long enough
        # for a 16-bar phrase to fit before the tail constraint.
        downbeats = [round(i * 1.875, 3) for i in range(32)]
        current = {
            "id": "out", "duration_sec": 60.0, "bpm": 128.0,
            "beatgrid": _v2_beatgrid(128.0, downbeats),
        }
        next_track = {
            "id": "in", "duration_sec": 60.0, "bpm": 128.0,
            "beatgrid": _v2_beatgrid(128.0, downbeats),
        }
        engine = self._engine_with_current(current)
        next_audio = _silent_audio(60.0)
        plan = engine._build_transition_plan_for_next(current, next_track, next_audio)
        assert plan is not None
        assert plan.phrase_tier in ("16-bar", "8-bar", "4-bar", "downbeat")
        assert plan.phrase_tier != "fallback"

    def test_plan_falls_back_when_both_sides_lack_beatgrid(self):
        current = {"id": "out", "duration_sec": 60.0, "bpm": 128.0}
        next_track = {"id": "in", "duration_sec": 60.0, "bpm": 128.0}
        engine = self._engine_with_current(current)
        next_audio = _silent_audio(60.0)
        plan = engine._build_transition_plan_for_next(current, next_track, next_audio)
        assert plan is not None
        assert plan.phrase_tier == "fallback"

    def test_returns_none_for_zero_duration_outgoing(self):
        """Defensive: a malformed catalog entry with duration_sec=0 used
        to crash ``find_phrase_anchor`` with a divide-by-zero / negative
        tail. Returning ``None`` lets the engine fall back to legacy
        cleanly instead of taking down the live session."""
        current = {"id": "out", "duration_sec": 0.0}
        next_track = {"id": "in", "duration_sec": 60.0, "bpm": 128.0}
        engine = self._engine_with_current(current)
        engine._audio = None
        next_audio = _silent_audio(60.0)
        plan = engine._build_transition_plan_for_next(current, next_track, next_audio)
        assert plan is None

    def test_incoming_audio_mono_summed_for_rms_heuristic(self):
        """The pickup-skip RMS heuristic should treat stereo input the
        same way it treats mono — averaging channels. Pass a stereo
        buffer with a quiet bar 0 and confirm the plan flags
        ``incoming_pickup_skipped``."""
        downbeats = [0.0, 2.0, 4.0, 6.0]
        next_audio = np.ones((int(8.0 * _SAMPLE_RATE), 2), dtype=np.float32) * 0.5
        next_audio[: int(2.0 * _SAMPLE_RATE)] *= 0.05  # quiet bar 0
        current = {
            "id": "out", "duration_sec": 8.0, "bpm": 120.0,
            "beatgrid": _v2_beatgrid(120.0, downbeats),
        }
        next_track = {
            "id": "in", "duration_sec": 8.0, "bpm": 120.0,
            "beatgrid": _v2_beatgrid(120.0, downbeats),
        }
        engine = self._engine_with_current(current)
        plan = engine._build_transition_plan_for_next(current, next_track, next_audio)
        assert plan is not None
        assert plan.incoming_pickup_skipped is True

    def test_outgoing_duration_falls_back_to_audio_length_when_missing(self):
        """If the catalog dict is missing ``duration_sec`` on the
        outgoing side, fall back to the loaded buffer's length. Real
        catalogs always have ``duration_sec``, but the safety bound
        matters for hand-built test fixtures and pathological catalog
        rows."""
        downbeats = [round(i * 1.875, 3) for i in range(32)]
        current = {"id": "out", "bpm": 128.0, "beatgrid": _v2_beatgrid(128.0, downbeats)}
        next_track = {
            "id": "in", "duration_sec": 10.0, "bpm": 128.0,
            "beatgrid": _v2_beatgrid(128.0, downbeats),
        }
        engine = self._engine_with_current(current)
        # 60-second outgoing buffer feeds the duration fallback.
        plan = engine._build_transition_plan_for_next(
            current, next_track, _silent_audio(10.0)
        )
        assert plan is not None


# ---------------------------------------------------------------------------
# _audio_callback equal-power crossfade
# ---------------------------------------------------------------------------

class TestAudioCallbackEqualPower:
    """The audio callback runs in sounddevice's low-latency thread, so
    these tests call it directly with pre-staged buffers and assert the
    output. The two invariants under test:

      1. cos² + sin² = 1 — squared-power across the overlap is constant.
      2. The first ``XFADE_EDGE_GUARD_SAMPLES`` of the outgoing tail are
         attenuated by the raised-cosine guard.
    """

    def _staged_engine(self, *, cf_len_sec: float = 1.0):
        q = Queue()
        engine = LiveEngineLocal(_make_playlist(2), q, crossfade_sec=cf_len_sec)
        # Constant-amplitude buffers so the curves are directly readable
        # in the output. Mono summed to stereo identical L/R.
        cf_samples = int(cf_len_sec * _SAMPLE_RATE)
        out_buf = np.ones((cf_samples + 1000, 2), dtype=np.float32)
        in_buf = np.ones((cf_samples + 1000, 2), dtype=np.float32)
        engine._audio = out_buf
        engine._next_audio = in_buf
        engine._pos = 0
        engine._cf_start = 0
        engine._next_pos = 0
        engine._state = "crossfading"
        return engine, cf_samples

    def test_equal_power_curves_at_25_percent_into_overlap(self):
        """At 25 % through the overlap (angle = π/8), the outgoing
        amplitude factor should be cos(π/8) ≈ 0.924 and incoming
        sin(π/8) ≈ 0.383. Their squared sum ≈ 0.854 + 0.146 = 1.0,
        which is the equal-power invariant."""
        engine, cf_samples = self._staged_engine(cf_len_sec=1.0)
        # Position the callback at 25 % of the way in.
        engine._pos = cf_samples // 4
        engine._cf_start = 0
        engine._next_pos = cf_samples // 4
        chunk = 64
        outdata = np.zeros((chunk, 2), dtype=np.float32)
        engine._audio_callback(outdata, chunk, time_info=None, status=None)
        # Outgoing contribution to each sample is cos(angle) * 1.0,
        # incoming is sin(angle) * 1.0, summed. With both buffers = 1,
        # samples are cos + sin (NOT 1) — but the POWER stays at 1.
        amplitude = float(outdata[0, 0])
        # cos(π/8) + sin(π/8) ≈ 0.924 + 0.383 = 1.307
        assert abs(amplitude - (np.cos(np.pi / 8) + np.sin(np.pi / 8))) < 0.01

    def test_outgoing_tail_attenuated_by_edge_guard_at_overlap_start(self):
        """At the very first overlap sample (cf_elapsed=0), the outgoing
        contribution should be ≈ 0 thanks to the raised-cosine guard,
        which masks any one-sample rounding click at the cut point.
        Incoming is also ≈ 0 here (sin(0)=0), so the very first sample
        is dominated by silence rather than a hard step."""
        engine, cf_samples = self._staged_engine(cf_len_sec=1.0)
        chunk = 4
        outdata = np.zeros((chunk, 2), dtype=np.float32)
        engine._audio_callback(outdata, chunk, time_info=None, status=None)
        assert float(outdata[0, 0]) < 0.1, (
            f"First overlap sample = {outdata[0, 0]} — guard should "
            f"attenuate it close to zero (was a click pre-v3.0)."
        )

    def test_overlap_completes_and_state_returns_to_playing(self):
        engine, cf_samples = self._staged_engine(cf_len_sec=0.01)  # 441 samples
        chunk = cf_samples + 100
        outdata = np.zeros((chunk, 2), dtype=np.float32)
        engine._audio_callback(outdata, chunk, time_info=None, status=None)
        assert engine._state == "playing"
        assert engine._transition_plan is None, (
            "transition_plan must be cleared after crossfade so the next "
            "transition builds its own plan rather than reusing stale state."
        )

    def test_guard_window_capped_at_half_xfade(self):
        """For very short crossfades (smaller than 2*XFADE_EDGE_GUARD),
        the guard window collapses to half the xfade length so the
        attenuation curve never blocks more than the first half. Without
        the cap, a 64-sample xfade would have a 64-sample full-attenuation
        prefix and play silently."""
        # 100-sample xfade → guard caps at 50 samples instead of 64.
        engine, cf_samples = self._staged_engine(cf_len_sec=100 / _SAMPLE_RATE)
        chunk = 64
        outdata = np.zeros((chunk, 2), dtype=np.float32)
        engine._audio_callback(outdata, chunk, time_info=None, status=None)
        # Sample 50 should be past the guard → outgoing fade_out = cos at
        # 50 % → 0.707; incoming fade_in = sin at 50 % → 0.707;
        # sum = 1.414. With guard active here, value would be much lower.
        assert float(outdata[50, 0]) > 0.5
