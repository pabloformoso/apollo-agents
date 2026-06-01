"""
Unit tests for agent/live_dj.py live tools.

The LiveEngine is replaced by a MagicMock so no audio hardware is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.live_dj import (
    _format_event,
    _playlist_summary,
    crossfade_now,
    extend_track,
    get_live_state,
    queue_swap,
    set_crossfade_point,
    skip_track,
)
from agent.live_engine import (
    APPROACHING_CF,
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
)


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------

def _make_engine(state="playing", position_sec=45.0, seconds_to_cf=20.0,
                 playlist_remaining=2):
    engine = MagicMock()
    engine.get_state.return_value = {
        "state": state,
        "position_sec": position_sec,
        "current_track": {"display_name": "Deep Waters", "bpm": 124.0, "camelot_key": "8A", "hot_cues": []},
        "next_track": {"display_name": "Neon Drift", "bpm": 128.0, "camelot_key": "9A", "hot_cues": []},
        "seconds_to_crossfade": seconds_to_cf,
        "playlist_remaining": playlist_remaining,
    }
    engine.crossfade_now.return_value = "Crossfade triggered."
    engine.extend_track.return_value = "Extended by 30s."
    engine.skip_track.return_value = "Skipped to 'Neon Drift'."
    engine.queue_swap.return_value = "Queued 'Bridge Track' at position 3."
    engine.set_crossfade_point.return_value = "Crossfade point set to 200.0s."
    return engine


def _ctx(engine=None):
    return {"_engine": engine or _make_engine()}


# ---------------------------------------------------------------------------
# get_live_state
# ---------------------------------------------------------------------------

def test_get_live_state_no_engine():
    result = get_live_state({})
    assert "not running" in result


def test_get_live_state_returns_formatted_info():
    result = get_live_state(_ctx())
    assert "Deep Waters" in result
    assert "Neon Drift" in result
    assert "124.0" in result
    assert "8A" in result
    assert "20.0" in result


def test_get_live_state_includes_hot_cues():
    engine = _make_engine()
    engine.get_state.return_value["current_track"]["hot_cues"] = [
        {"type": "out", "position_sec": 200.0, "label": "OUT"}
    ]
    result = get_live_state({"_engine": engine})
    assert "hot_cues" in result.lower() or "200.0" in result


# ---------------------------------------------------------------------------
# crossfade_now
# ---------------------------------------------------------------------------

def test_crossfade_now_no_engine():
    result = crossfade_now({})
    assert "not running" in result


def test_crossfade_now_calls_engine():
    engine = _make_engine()
    result = crossfade_now(_ctx(engine))
    engine.crossfade_now.assert_called_once()
    assert "Crossfade triggered" in result


# ---------------------------------------------------------------------------
# extend_track
# ---------------------------------------------------------------------------

def test_extend_track_no_engine():
    result = extend_track(30, {})
    assert "not running" in result


def test_extend_track_passes_seconds():
    engine = _make_engine()
    result = extend_track(30, _ctx(engine))
    engine.extend_track.assert_called_once_with(30)
    assert "Extended" in result


# ---------------------------------------------------------------------------
# skip_track
# ---------------------------------------------------------------------------

def test_skip_track_no_engine():
    result = skip_track({})
    assert "not running" in result


def test_skip_track_calls_engine():
    engine = _make_engine()
    result = skip_track(_ctx(engine))
    engine.skip_track.assert_called_once()
    assert "Skipped" in result


# ---------------------------------------------------------------------------
# queue_swap
# ---------------------------------------------------------------------------

def test_queue_swap_no_engine():
    result = queue_swap(3, "some-id", {})
    assert "not running" in result


def test_queue_swap_passes_args():
    engine = _make_engine()
    result = queue_swap(3, "bridge-track-id", _ctx(engine))
    engine.queue_swap.assert_called_once_with(3, "bridge-track-id")
    assert "Queued" in result


# ---------------------------------------------------------------------------
# set_crossfade_point
# ---------------------------------------------------------------------------

def test_set_crossfade_point_no_engine():
    result = set_crossfade_point(200.0, {})
    assert "not running" in result


def test_set_crossfade_point_passes_seconds():
    engine = _make_engine()
    result = set_crossfade_point(200.0, _ctx(engine))
    engine.set_crossfade_point.assert_called_once_with(200.0)
    assert "200.0" in result


# ---------------------------------------------------------------------------
# _format_event helpers
# ---------------------------------------------------------------------------

def test_format_event_track_started():
    ev = {"type": TRACK_STARTED, "track": {"display_name": "T1", "bpm": 120.0, "camelot_key": "8A"}}
    out = _format_event(ev)
    assert "TRACK_STARTED" in out
    assert "T1" in out


def test_format_event_approaching_cf():
    ev = {
        "type": APPROACHING_CF,
        "track": {"display_name": "A", "bpm": 120.0, "camelot_key": "8A"},
        "next_track": {"display_name": "B", "bpm": 128.0, "camelot_key": "9A"},
        "seconds_remaining": 25.0,
    }
    out = _format_event(ev)
    assert "APPROACHING_CF" in out
    assert "25.0" in out
    assert "A" in out
    assert "B" in out


def test_format_event_approaching_cf_smooth_blend_does_not_mention_move():
    """v3.3 — smooth_blend is the default on every transition; if we
    surfaced it the LLM would be told to consider narrating every
    crossfade, polluting the dj_chat feed with noise."""
    ev = {
        "type": APPROACHING_CF,
        "track": {"display_name": "A", "bpm": 122.0, "camelot_key": "8A"},
        "next_track": {"display_name": "B", "bpm": 122.0, "camelot_key": "8A"},
        "seconds_remaining": 25.0,
        "phase_lock": {"transition_style": "smooth_blend"},
    }
    out = _format_event(ev)
    assert "MOVE" not in out


def test_format_event_approaching_cf_bass_swap_surfaces_move_hint():
    """v3.3 — non-smooth transition styles show up as a "MOVE: '<name>'"
    line in the formatted event so the live_dj LLM has a deterministic
    cue to call emit_chat with personality-rich narration BEFORE the
    crossfade hits."""
    ev = {
        "type": APPROACHING_CF,
        "track": {"display_name": "A", "bpm": 122.0, "camelot_key": "8A"},
        "next_track": {"display_name": "B", "bpm": 122.0, "camelot_key": "8A"},
        "seconds_remaining": 25.0,
        "phase_lock": {
            "transition_style": "bass_swap",
            "bass_swap": {
                "hpf_cutoff_during_hz": 120,
                "hpf_cutoff_after_hz": 20,
                "drop_at_incoming_sec": 5.902,
            },
        },
    }
    out = _format_event(ev)
    assert "MOVE" in out
    assert "bass_swap" in out
    assert "drop @ 5.9s in" in out
    # And the prompt-side instruction "consider narrating" is there too
    # so the LLM has a hint about what to do with the move metadata.
    assert "narrat" in out.lower()


def test_format_event_approaching_cf_missing_phase_lock_does_not_crash():
    """Defensive: legacy backends or fallback-tier transitions ship no
    phase_lock dict at all. Formatter should degrade silently to the
    pre-v3.3 line, not throw on key access."""
    ev = {
        "type": APPROACHING_CF,
        "track": {"display_name": "A", "bpm": 120.0, "camelot_key": "8A"},
        "next_track": {"display_name": "B", "bpm": 128.0, "camelot_key": "9A"},
        "seconds_remaining": 25.0,
        # no phase_lock key at all
    }
    out = _format_event(ev)
    assert "APPROACHING_CF" in out
    assert "MOVE" not in out


def test_format_event_crossfade_triggered():
    ev = {
        "type": CROSSFADE_TRIGGERED,
        "from_track": {"display_name": "Out"},
        "to_track": {"display_name": "In"},
    }
    out = _format_event(ev)
    assert "CROSSFADE_TRIGGERED" in out
    assert "Out" in out
    assert "In" in out


def test_format_event_crossfade_finished():
    ev = {
        "type": CROSSFADE_FINISHED,
        "from_track": {"display_name": "Old"},
        "to_track": {"display_name": "New"},
    }
    out = _format_event(ev)
    assert "CROSSFADE_FINISHED" in out
    assert "New" in out


def test_format_event_track_ended():
    ev = {"type": TRACK_ENDED, "track": {"display_name": "Done"}}
    out = _format_event(ev)
    assert "TRACK_ENDED" in out
    assert "Done" in out


def test_format_event_session_ended():
    out = _format_event({"type": SESSION_ENDED})
    assert "SESSION_ENDED" in out


# ---------------------------------------------------------------------------
# _playlist_summary
# ---------------------------------------------------------------------------

def test_playlist_summary():
    playlist = [
        {"display_name": "A", "bpm": 120.0, "camelot_key": "8A"},
        {"display_name": "B", "bpm": 125.0, "camelot_key": "9A"},
    ]
    out = _playlist_summary(playlist)
    assert "2 tracks" in out
    assert "A" in out
    assert "B" in out
    assert "120.0" in out


# ---------------------------------------------------------------------------
# extend_set  (v2.6.0 endless mode)
# ---------------------------------------------------------------------------
from agent.tools import extend_set  # noqa: E402  — colocated with other live tools


def test_extend_set_no_engine():
    result = extend_set("any-id", {})
    assert "not running" in result.lower()


def test_extend_set_invalid_id(monkeypatch):
    """Unknown ids never touch the engine — they return a clear error
    so the LLM can re-pick instead of silently no-op'ing the queue."""
    engine = _make_engine()
    monkeypatch.setattr(
        "web.backend.pipeline.load_catalog",
        lambda _genre=None: ([{"id": "real-track", "display_name": "Real"}], []),
    )
    result = extend_set("does-not-exist", _ctx(engine))
    assert "not in the catalog" in result.lower()
    assert "pick_next_track" in result, (
        "Error message must coach the LLM to re-run pick_next_track "
        "(see 1a212dc: track-id discipline)."
    )
    engine.append_track.assert_not_called()


def test_extend_set_valid_id_calls_engine_append(monkeypatch):
    """Happy path: tool resolves the id from the catalog and forwards
    the full track dict to ``engine.append_track``."""
    engine = _make_engine()
    engine.append_track.return_value = "Appended 'Real' at position 5."
    track = {
        "id": "real-track",
        "display_name": "Real",
        "bpm": 78.0,
        "camelot_key": "8A",
        "genre_folder": "lofi - ambient",
    }
    monkeypatch.setattr(
        "web.backend.pipeline.load_catalog",
        lambda _genre=None: ([track], []),
    )
    result = extend_set("real-track", _ctx(engine))
    engine.append_track.assert_called_once_with(track)
    assert "position 5" in result
