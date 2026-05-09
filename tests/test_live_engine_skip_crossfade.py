"""v2.5.2 — skip vs. crossfade behavior contract.

Skip is intentionally a HARD CUT in v2.5.2 (see ``LiveEngineBrowser.skip_track``
docstring). Users who want a ramped transition use ``crossfade_now`` instead.
This test pins the contract so a future refactor doesn't accidentally turn
skip into a crossfade.
"""
from __future__ import annotations

from agent.live_engine import (
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    TRACK_STARTED,
    LiveEngineBrowser,
)


def _track(track_id: str, *, duration_sec: float = 60.0) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": 120.0,
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


def test_skip_track_does_not_emit_crossfade_events() -> None:
    """Hard cut: skip emits TRACK_STARTED for the new track and a ``skip``
    engine command, but NO ``crossfade_triggered`` / ``crossfade_finished``.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    engine.skip_track()
    types = rec.types()
    assert CROSSFADE_TRIGGERED not in types
    assert CROSSFADE_FINISHED not in types
    assert TRACK_STARTED in types
    # Engine command is the hard-cut ``skip``, not ``crossfade``.
    cmds = [
        e.get("command")
        for e in rec.events
        if e.get("type") == "engine_command"
    ]
    assert "skip" in cmds
    assert "crossfade" not in cmds


def test_crossfade_now_emits_full_crossfade_sequence() -> None:
    """The opt-in ramped variant — ``crossfade_now`` — emits the full
    ``crossfade_triggered`` + ``crossfade_finished`` tetra so the audible
    transition is a 12 s blend on the browser side.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    msg = engine.crossfade_now()
    assert "triggered" in msg.lower()
    types = rec.types()
    assert CROSSFADE_TRIGGERED in types
    assert CROSSFADE_FINISHED in types
    cmds = [
        e.get("command")
        for e in rec.events
        if e.get("type") == "engine_command"
    ]
    assert "crossfade" in cmds


def test_skip_advances_idx_and_arms_new_track_watchdog() -> None:
    """After skip, the new track's watchdog (approach + crossfade flags)
    must be re-armed so the engine can fire its own ``approaching_crossfade``
    when track B nears its own out-point.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play(
        [
            _track("a", duration_sec=60.0),
            _track("b", duration_sec=60.0),
            _track("c", duration_sec=60.0),
        ]
    )
    engine.skip_track()
    assert engine._idx == 1
    assert engine._approached is False
    assert engine._cf_triggered is False
    rec.events.clear()
    # Drive track B to its warn window; the engine should fire approach
    # for the B→C transition.
    engine.report_playback_pos("b", 13.0)
    from agent.live_engine import APPROACHING_CF
    assert APPROACHING_CF in rec.types()
