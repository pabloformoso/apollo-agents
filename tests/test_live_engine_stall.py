"""Unit tests for the v3.6.3 server-side stall watchdog.

The browser engine is ping-driven: a frozen operator tab (Chrome Energy
Saver) or a deck that never decoded stops the ping stream and the whole
session wedges in silence — observed live 2026-07-11 (3.5 h endless set
died mid-'Slow Oxide' with a healthy backend and a valid MP3).
``check_stall`` is the backend's self-clock: called periodically by the
live WS, it force-advances once the wall clock is past the current
track's expected end + margin AND the reported position stopped moving.
"""
from __future__ import annotations

import time

from agent.live_engine import (
    ENDLESS_WARNING,
    LIVE_STALL_CHECK_SEC,
    LIVE_STALL_MARGIN_SEC,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
)


def _track(
    track_id: str,
    *,
    duration_sec: float = 60.0,
    bpm: float = 120.0,
    camelot_key: str = "8A",
    genre_folder: str = "lofi - ambient",
) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": camelot_key,
        "duration_sec": duration_sec,
        "genre_folder": genre_folder,
        "genre": genre_folder,
        "hot_cues": [],
    }


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


def _stall(engine: LiveEngineBrowser, seconds_past_start: float) -> None:
    """Rewind the track-start anchor so the engine looks stalled."""
    engine._track_started_mono = time.monotonic() - seconds_past_start


def test_defaults_are_sane():
    assert LIVE_STALL_CHECK_SEC > 0
    assert LIVE_STALL_MARGIN_SEC > 0
    # The margin must comfortably exceed decode latency on slow hardware
    # (~2 s) but stay well under a typical track length.
    assert 10 <= LIVE_STALL_MARGIN_SEC <= 120


def test_check_stall_none_while_track_still_running():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    # Just started — nowhere near expected end.
    assert engine.check_stall() is None
    assert TRACK_ENDED not in rec.types()


def test_check_stall_none_when_position_keeps_moving():
    """extend_track / manual cf-point moves can push playback past the
    catalog duration — a MOVING position must never trip the watchdog."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    # Fresh pings with a moving position — the deck is clearly alive.
    engine.report_playback_pos(track_id="a", current_time=10.0)
    engine.report_playback_pos(track_id="a", current_time=11.0)
    assert engine.check_stall() is None


def test_check_stall_forces_advance_when_position_frozen():
    """The live failure: pings stopped (frozen tab) — wall clock passes
    the expected end + margin and the watchdog synthesises the
    track_ended the browser never sent."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    forced = engine.check_stall()
    assert forced == "a"
    types = rec.types()
    assert TRACK_ENDED in types
    assert TRACK_STARTED in types
    started = next(e for e in rec.events if e.get("type") == TRACK_STARTED)
    assert started["track"]["id"] == "b"


def test_check_stall_frozen_ping_with_static_position_also_fires():
    """A deck that failed to decode keeps pinging position ~0 forever.
    Arrival of pings alone must not count as progress."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    engine.report_playback_pos(track_id="a", current_time=0.1)
    # Pings keep coming but the position never moves.
    engine.report_playback_pos(track_id="a", current_time=0.1)
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    engine._last_pos_change_mono = (
        time.monotonic() - (LIVE_STALL_MARGIN_SEC + 10)
    )
    assert engine.check_stall() == "a"


def test_check_stall_extends_endless_set_on_last_track(monkeypatch):
    """Stalled on the LAST track with endless ON: the forced track_ended
    flows through the endless gate, appends a continuation, and keeps
    the set alive — this is what keeps an OBS viewer audible while the
    operator tab is frozen."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    engine._endless_mode = True
    monkeypatch.setattr(
        "agent.live_engine._load_catalog",
        lambda: [_track("rescue", bpm=122)],
    )
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    assert engine.check_stall() == "a"
    assert SESSION_ENDED not in rec.types()
    assert engine.playlist[engine._idx]["id"] == "rescue"


def test_check_stall_ends_session_when_endless_off_and_no_next(monkeypatch):
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    assert engine.check_stall() == "a"
    assert SESSION_ENDED in rec.types()


def test_check_stall_none_when_idle():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    engine.stop()
    _stall(engine, seconds_past_start=1000)
    assert engine.check_stall() is None


def test_check_stall_zero_duration_uses_fallback_ceiling():
    """A malformed catalog row (duration 0) must not wedge the watchdog
    open forever — a generous fixed ceiling still applies."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=0), _track("b")])
    # Well under the 600 s ceiling → quiet.
    _stall(engine, seconds_past_start=120)
    assert engine.check_stall() is None
    # Past ceiling + margin → fires.
    _stall(engine, seconds_past_start=600 + LIVE_STALL_MARGIN_SEC + 30)
    assert engine.check_stall() == "a"


def test_check_stall_one_advance_per_call_resets_the_clock():
    """After a forced advance the new track gets a fresh clock — the
    watchdog paces a fully-frozen client at roughly track-duration
    cadence instead of machine-gunning through the playlist."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b", duration_sec=60), _track("c")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    assert engine.check_stall() == "a"
    # Immediately after: 'b' just (synthetically) started — quiet.
    assert engine.check_stall() is None
    assert engine.playlist[engine._idx]["id"] == "b"
