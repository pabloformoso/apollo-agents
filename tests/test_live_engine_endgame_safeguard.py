"""v2.5.0.1 — endgame safeguard inside ``report_playback_pos``.

The browser's ``<audio>`` element pauses + freezes ``currentTime`` when
natural playback ends; the dedicated ``ended`` listener forwards a
``track_ended`` WS message but it can be lost (network blip, listener
race, browser quirk). The safeguard inside ``report_playback_pos`` is the
belt-and-braces fallback: if the last reported position is within the
last 2 s of the track AND no crossfade has fired, force a
``track_ended``-style advance.
"""
from __future__ import annotations

from agent.live_engine import (
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
)


def _track(track_id: str, *, duration_sec: float = 30.0, bpm: float = 120.0) -> dict:
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


def test_endgame_safeguard_forces_track_ended_in_last_two_seconds():
    """Track A is 30 s long. Default crossfade_sec=12 + 5 buffer ⇒ cf
    point is at 13 s. With approach_warn_sec=2, the only way the
    ``approaching_crossfade`` watchdog can have fired without a
    crossfade is if a manual extend pushed the cf point beyond the
    track's duration. Simulate that, then ping a ``current_time``
    inside the last 2 s — the safeguard must synthesise a
    ``track_ended`` advance.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=2)
    engine.play([_track("a", duration_sec=30.0), _track("b", duration_sec=30.0)])
    # Push the crossfade point past the duration so the normal trigger
    # never fires — only the endgame safeguard should win the race.
    engine.extend_track(60)
    rec.events.clear()

    # current_time = 28.5s on a 30s track → inside the last-2s window.
    engine.report_playback_pos("a", 28.5)

    types = rec.types()
    assert TRACK_ENDED in types, "endgame safeguard must synthesise track_ended"
    # Advanced to the next track.
    assert engine._idx == 1
    # Browser also got a ``load`` engine_command for "b".
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "load"
    ]
    assert cmds and cmds[-1]["track"]["id"] == "b"


def test_endgame_safeguard_does_not_double_fire_with_crossfade():
    """If the regular crossfade trigger has already fired we must NOT
    re-fire ``track_ended`` from the safeguard. The cf-triggered guard
    inside ``report_playback_pos`` skips the safeguard branch entirely.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=2, approach_warn_sec=1)
    engine.play([_track("a", duration_sec=10.0), _track("b", duration_sec=10.0)])
    rec.events.clear()

    # First ping crosses the cf point (cf = 10 - 2 - 5 = 3 s) → triggers
    # crossfade. The safeguard branch must be skipped.
    engine.report_playback_pos("a", 9.5)
    track_ended_count = rec.types().count(TRACK_ENDED)
    # Crossfade emits exactly one TRACK_ENDED for the from-track.
    assert track_ended_count == 1


def test_endgame_safeguard_on_last_track_emits_session_ended():
    """Track has no successor — safeguard must end the session, not
    crash trying to load a non-existent next track."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=2)
    engine.play([_track("a", duration_sec=30.0)])
    # Push cf point past the duration so normal trigger doesn't fire.
    engine.extend_track(60)
    rec.events.clear()

    engine.report_playback_pos("a", 28.5)

    types = rec.types()
    assert TRACK_ENDED in types
    assert SESSION_ENDED in types
    assert TRACK_STARTED not in types  # no phantom advance


def test_endgame_safeguard_does_not_fire_outside_last_two_seconds():
    """Position at duration - 5 s (well outside the 2 s window) and a
    cf point pushed beyond the duration must NOT trigger the safeguard.
    Belt-and-braces: the safeguard window is intentionally tight to
    avoid premature advances when the track is mid-play.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=2)
    engine.play([_track("a", duration_sec=30.0), _track("b", duration_sec=30.0)])
    engine.extend_track(60)  # push cf point past the duration
    rec.events.clear()

    # 25 s on a 30 s track = 5 s remaining, OUTSIDE the 2 s safeguard window.
    engine.report_playback_pos("a", 25.0)
    assert TRACK_ENDED not in rec.types()
    assert engine._idx == 0  # cursor must not advance
