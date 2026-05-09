"""v2.5.0.1 — explicit ``report_track_ended`` advances the engine.

The browser fires the HTML5 ``ended`` event when natural playback finishes;
the frontend forwards that as a synthetic ``track_ended`` WS message. The
WS handler invokes ``LiveEngineBrowser.report_track_ended``, which must:

  1. Emit a ``track_ended`` event for the just-finished track.
  2. Advance the cursor to the next track.
  3. Emit a ``stop_deck`` engine command (release the active deck).
  4. Emit a ``load`` engine command for the new track.
  5. Emit ``track_started`` for the new track.

When the just-finished track was the LAST one, only steps (1) + (5'
``session_ended``) fire and the engine flips to ``idle``.
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

    def commands(self) -> list[dict]:
        return [e for e in self.events if e.get("type") == "engine_command"]


def test_report_track_ended_advances_cursor_and_emits_track_started():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()

    engine.report_track_ended("a")

    types = rec.types()
    assert TRACK_ENDED in types, "must emit track_ended for the finished track"
    assert TRACK_STARTED in types, "must emit track_started for the next track"
    # Cursor advanced.
    assert engine._idx == 1
    # The new track_started is for "b".
    started = [e for e in rec.events if e["type"] == TRACK_STARTED]
    assert started[-1]["track"]["id"] == "b"


def test_report_track_ended_emits_stop_deck_then_load_for_next_track():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()

    engine.report_track_ended("a")

    cmd_names = [c.get("command") for c in rec.commands()]
    # stop_deck precedes load so the active deck is released cleanly.
    assert "stop_deck" in cmd_names
    assert "load" in cmd_names
    assert cmd_names.index("stop_deck") < cmd_names.index("load")
    load_cmds = [c for c in rec.commands() if c.get("command") == "load"]
    assert load_cmds[-1]["track"]["id"] == "b"


def test_report_track_ended_on_last_track_emits_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])  # only one track
    rec.events.clear()

    engine.report_track_ended("a")

    types = rec.types()
    assert TRACK_ENDED in types
    assert SESSION_ENDED in types
    # No phantom track_started for a non-existent next track.
    started = [e for e in rec.events if e["type"] == TRACK_STARTED]
    assert started == []


def test_report_track_ended_ignores_stale_track_id():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()

    engine.report_track_ended("not-current")

    # No advance, no events.
    assert engine._idx == 0
    assert rec.events == []


def test_report_track_ended_when_idle_is_a_noop():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    # Engine never had ``play()`` called on it — state is "idle".
    rec.events.clear()
    engine.report_track_ended("a")
    assert rec.events == []


def test_report_track_ended_followed_by_stale_pos_ping_is_ignored():
    """Ordering invariant: a stale ``playback_pos`` arriving after the
    advance must NOT re-fire ``track_ended``. The stale-ping guard already
    catches it because ``self._idx`` has moved on."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=30.0), _track("b", duration_sec=30.0)])
    rec.events.clear()

    engine.report_track_ended("a")  # advance to "b"
    rec.events.clear()
    # Browser's playback_pos interval is still alive for one more tick
    # before it picks up the new track_id — that ping arrives with the
    # OLD id.
    engine.report_playback_pos("a", 29.5)
    assert rec.events == []
