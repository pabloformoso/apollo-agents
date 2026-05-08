"""Unit tests for the v2.5.1 ``LiveEngineBrowser`` implementation.

The browser engine doesn't touch sounddevice, librosa, or pyrubberband — it
only manages playlist state and emits engine events that the WS handler
forwards to the browser. These tests collect emitted events into a Python
list and inspect transitions explicitly.
"""
from __future__ import annotations

from agent.live_engine import (
    APPROACHING_CF,
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
)


def _track(track_id: str, *, duration_sec: float = 60.0, bpm: float = 120.0) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "hot_cues": [],
    }


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


# ---------------------------------------------------------------------------
# play()
# ---------------------------------------------------------------------------

def test_play_emits_track_started_for_first_track():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    started = [e for e in rec.events if e["type"] == TRACK_STARTED]
    assert len(started) == 1
    assert started[0]["track"]["id"] == "a"


def test_play_with_empty_playlist_emits_session_ended_only():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([])
    assert rec.types() == [SESSION_ENDED]


def test_play_emits_load_command_so_browser_starts_audio():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "load"
    ]
    assert cmds and cmds[0]["track"]["id"] == "a"


# ---------------------------------------------------------------------------
# report_playback_pos()
# ---------------------------------------------------------------------------

def test_report_playback_pos_triggers_approaching_crossfade_at_threshold():
    rec = _Recorder()
    # 30s warn window, 20s track. Crossfade point defaults to
    # duration - crossfade_sec - 5 = 20 - 12 - 5 = 3s. So at currentTime
    # 0.0 we're already inside the warn window for the first track.
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=20.0), _track("b", duration_sec=20.0)])
    rec.events.clear()
    engine.report_playback_pos("a", 0.0)
    assert APPROACHING_CF in rec.types()


def test_report_playback_pos_only_fires_warn_once_per_track():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play(
        [_track("a", duration_sec=120.0), _track("b", duration_sec=120.0)]
    )
    rec.events.clear()
    # Crossfade point ~ 120 - 12 - 5 = 103s. Warn at <=30s remaining => 73s.
    engine.report_playback_pos("a", 80.0)
    engine.report_playback_pos("a", 81.0)
    engine.report_playback_pos("a", 82.0)
    warns = [e for e in rec.events if e["type"] == APPROACHING_CF]
    assert len(warns) == 1


def test_report_playback_pos_triggers_crossfade_past_threshold():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=5)
    engine.play(
        [_track("a", duration_sec=20.0), _track("b", duration_sec=20.0)]
    )
    rec.events.clear()
    engine.report_playback_pos("a", 19.0)  # well past cf point (3s)
    types = rec.types()
    assert CROSSFADE_TRIGGERED in types
    assert TRACK_STARTED in types  # next track started


def test_report_playback_pos_for_last_track_emits_track_ended_and_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=2, approach_warn_sec=2)
    engine.play([_track("a", duration_sec=10.0)])
    rec.events.clear()
    engine.report_playback_pos("a", 11.0)  # past duration
    types = rec.types()
    assert TRACK_ENDED in types
    assert SESSION_ENDED in types


def test_report_playback_pos_ignores_stale_track_pings():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    engine.report_playback_pos("not-the-current-track", 1.0)
    assert rec.events == []


# ---------------------------------------------------------------------------
# skip_track()
# ---------------------------------------------------------------------------

def test_skip_track_advances_cursor_and_emits_events():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    msg = engine.skip_track()
    assert "Track b" in msg
    assert engine._idx == 1
    types = rec.types()
    assert TRACK_STARTED in types
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "skip"
    ]
    assert cmds


def test_skip_track_on_last_track_returns_message():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    msg = engine.skip_track()
    assert "No next track" in msg


# ---------------------------------------------------------------------------
# queue_swap()
# ---------------------------------------------------------------------------

def test_queue_swap_replaces_track_at_position():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b"), _track("c")])
    new_track = _track("z")
    msg = engine.queue_swap_with_track(3, new_track)
    assert "Queued" in msg
    assert engine.playlist[2]["id"] == "z"
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "queue_swap"
    ]
    assert cmds and cmds[-1]["track"]["id"] == "z"


def test_queue_swap_rejects_past_position():
    engine = LiveEngineBrowser()
    engine.play([_track("a"), _track("b")])
    msg = engine.queue_swap_with_track(1, _track("z"))
    assert "not a future slot" in msg


# ---------------------------------------------------------------------------
# extend_track()
# ---------------------------------------------------------------------------

def test_extend_track_pushes_crossfade_point_back():
    engine = LiveEngineBrowser(crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b")])
    state_before = engine.get_state()
    engine.extend_track(20)
    state_after = engine.get_state()
    assert state_after["seconds_to_crossfade"] >= state_before["seconds_to_crossfade"] + 19


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_emits_session_ended_when_playing():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    rec.events.clear()
    engine.stop()
    types = rec.types()
    assert SESSION_ENDED in types
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "stop"
    ]
    assert cmds


def test_stop_when_idle_does_not_re_emit_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([])
    rec.events.clear()  # discard the SESSION_ENDED that ``play([])`` emitted
    engine.stop()
    assert SESSION_ENDED not in rec.types()


# ---------------------------------------------------------------------------
# get_state()
# ---------------------------------------------------------------------------

def test_get_state_after_play():
    engine = LiveEngineBrowser()
    engine.play([_track("a"), _track("b")])
    s = engine.get_state()
    assert s["state"] == "playing"
    assert s["current_track"]["display_name"] == "Track a"
    assert s["next_track"]["display_name"] == "Track b"
    assert s["playlist_remaining"] == 1
