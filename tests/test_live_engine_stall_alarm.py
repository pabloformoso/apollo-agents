"""The stall ALARM on top of the v3.6.3 watchdog (2026-11-19).

``check_stall`` keeps a wedged browser set moving, and on its own it never
stops: on 2026-08-01 it walked 21 tracks that were announced and never
heard. After ``LIVE_STALL_ALARM_AFTER`` forced advances in a row — no
reported position MOVING in between — the engine raises one ``stall_alarm``
and, when the caller says nobody can be hearing it (``can_hold``: no OBS
viewer attached), stops forcing advances until playback moves again.
"""
from __future__ import annotations

import pytest

from agent import live_engine
from agent.live_engine import (
    LIVE_STALL_MARGIN_SEC,
    STALL_ALARM,
    LiveEngineBrowser,
)

DURATION = 60.0


def _track(track_id: str) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": 120.0,
        "camelot_key": "8A",
        "duration_sec": DURATION,
        "genre_folder": "lofi - ambient",
        "genre": "lofi - ambient",
        "hot_cues": [],
    }


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def alarms(self) -> list[dict]:
        return [e for e in self.events if e.get("type") == STALL_ALARM]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    fake = _FakeClock()
    monkeypatch.setattr(live_engine.time, "monotonic", fake.monotonic)
    return fake


@pytest.fixture(autouse=True)
def alarm_after_three(monkeypatch):
    monkeypatch.setattr(live_engine, "LIVE_STALL_ALARM_AFTER", 3)


def _engine(n_tracks: int = 10) -> tuple[LiveEngineBrowser, _Recorder]:
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track(f"t{i}") for i in range(n_tracks)])
    return engine, rec


def _frozen_tab_stall(engine, clock, *, can_hold: bool = False):
    """A fully frozen tab: no pings at all, wall clock past end + margin."""
    clock.advance(DURATION + LIVE_STALL_MARGIN_SEC + 1)
    return engine.check_stall(can_hold=can_hold)


def _current(engine) -> str:
    return engine.playlist[engine._idx]["id"]


def _play(engine, clock, seconds: float = 5.0) -> None:
    """Real playback on the current track: pings whose position MOVES."""
    tid = _current(engine)
    pos = 0.0
    for _ in range(int(seconds / 0.25) + 1):
        engine.report_playback_pos(track_id=tid, current_time=pos)
        clock.advance(0.25)
        pos += 0.25


def test_alarm_raised_once_on_the_nth_consecutive_forced_advance(clock):
    engine, rec = _engine()
    assert _frozen_tab_stall(engine, clock) == "t0"
    assert _frozen_tab_stall(engine, clock) == "t1"
    assert rec.alarms() == []

    assert _frozen_tab_stall(engine, clock) == "t2"
    [alarm] = rec.alarms()
    assert alarm["state"] == "raised"
    assert alarm["consecutive"] == 3
    assert alarm["track"]["id"] == "t2"
    assert alarm["holding"] is False

    # Without can_hold it keeps advancing — a viewer may be the stream —
    # and does not re-raise on every further stall.
    assert _frozen_tab_stall(engine, clock) == "t3"
    assert len(rec.alarms()) == 1


def test_no_viewer_holds_instead_of_burning_the_catalog(clock):
    """The 2026-08-01 failure: nobody hearing it, track after track announced."""
    engine, rec = _engine()
    for _ in range(3):
        _frozen_tab_stall(engine, clock, can_hold=True)
    assert rec.alarms()[-1]["holding"] is True
    held_on = _current(engine)

    for _ in range(5):
        assert _frozen_tab_stall(engine, clock, can_hold=True) is None
    assert _current(engine) == held_on


def test_a_viewer_attaching_mid_hold_resumes_the_advances(clock):
    engine, _ = _engine()
    for _ in range(3):
        _frozen_tab_stall(engine, clock, can_hold=True)
    held_on = _current(engine)
    assert _frozen_tab_stall(engine, clock, can_hold=True) is None
    # Now an OBS viewer is following engine commands: advancing is audible.
    assert _frozen_tab_stall(engine, clock, can_hold=False) == held_on


def test_moving_position_clears_the_alarm_and_the_hold(clock):
    engine, rec = _engine()
    for _ in range(3):
        _frozen_tab_stall(engine, clock, can_hold=True)

    _play(engine, clock)  # the operator reloaded the tab; the deck plays

    cleared = rec.alarms()[-1]
    assert cleared["state"] == "cleared"
    assert cleared["consecutive"] == 3
    assert engine._consecutive_stalls == 0

    # The next stall counts from one again and is NOT held.
    tid = _current(engine)
    clock.advance(LIVE_STALL_MARGIN_SEC + 1)  # frozen mid-track
    assert engine.check_stall(can_hold=True) == tid
    assert engine._consecutive_stalls == 1
    assert [a["state"] for a in rec.alarms()] == ["raised", "cleared"]


def test_a_deck_frozen_at_zero_is_not_progress(clock):
    """A decode failure pings a frozen ~0 forever: arriving is not moving."""
    engine, rec = _engine()
    for _ in range(3):
        tid = _current(engine)
        engine.report_playback_pos(track_id=tid, current_time=0.0)
        engine.report_playback_pos(track_id=tid, current_time=0.1)
        clock.advance(LIVE_STALL_MARGIN_SEC + 1)
        assert engine.check_stall() == tid
    assert [a["state"] for a in rec.alarms()] == ["raised"]


def test_progress_between_stalls_keeps_the_count_low(clock):
    """Isolated stalls on a healthy set are the watchdog doing its job."""
    engine, rec = _engine()
    for _ in range(6):
        _play(engine, clock)
        clock.advance(LIVE_STALL_MARGIN_SEC + 1)
        assert engine.check_stall(can_hold=True) is not None
        assert engine._consecutive_stalls == 1
    assert rec.alarms() == []


def test_zero_disables_the_alarm(clock, monkeypatch):
    monkeypatch.setattr(live_engine, "LIVE_STALL_ALARM_AFTER", 0)
    engine, rec = _engine()
    for i in range(6):
        assert _frozen_tab_stall(engine, clock, can_hold=True) == f"t{i}"
    assert rec.alarms() == []


def test_default_never_holds(clock):
    """Callers that predate the alarm (no ``can_hold``) keep the old behaviour."""
    engine, _ = _engine()
    for i in range(6):
        clock.advance(DURATION + LIVE_STALL_MARGIN_SEC + 1)
        assert engine.check_stall() == f"t{i}"
