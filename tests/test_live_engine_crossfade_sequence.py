"""v2.5.2 — end-to-end crossfade sequence regression.

These tests drive ``LiveEngineBrowser.report_playback_pos`` from t=0 to the
end of a track and assert the engine emits events in the expected order
with the expected timing. Two regressions are covered:

1. ``approaching_crossfade`` fires reliably at ``duration - CROSSFADE_SEC -
   warn`` and carries the new ``cf_point_sec`` field so the frontend can
   derive a live-ticking countdown.
2. The endgame safeguard (v2.5.1) does NOT pre-empt the normal crossfade
   path — when the crossfade fires first, the safeguard branch is skipped.

These complement the existing
``tests/test_live_engine_browser.py`` and ``tests/test_live_engine_endgame_safeguard.py``,
which exercise individual edges; this file walks the full timeline.
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
# Full-track timeline
# ---------------------------------------------------------------------------


def test_full_timeline_two_tracks_emits_events_in_correct_order() -> None:
    """Drive a 60 s track from 0 → 60, then assert the canonical sequence
    fires in the right order:

        track_started (A) → approaching_crossfade (A→B) →
        crossfade_triggered → crossfade_finished + track_ended (A) →
        track_started (B)

    The safeguard must NOT fire because the regular crossfade already ran.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b", duration_sec=60.0)])
    # cf_point for track A = 60 - 12 - 5 = 43 s. Warn at 43 - 30 = 13 s.
    # Drive ticks at 1 s granularity.
    for t_sec in range(0, 50):
        engine.report_playback_pos("a", float(t_sec))

    types = rec.types()
    # Order check — drop ``engine_command`` events for clarity.
    engine_events = [t for t in types if not t.startswith("engine_command")]
    # Filter out the events that aren't the engine event types.
    canonical = [
        t
        for t in engine_events
        if t
        in {
            TRACK_STARTED,
            APPROACHING_CF,
            CROSSFADE_TRIGGERED,
            CROSSFADE_FINISHED,
            TRACK_ENDED,
            SESSION_ENDED,
        }
    ]
    # Expected sequence:
    #   track_started (A), approaching_crossfade,
    #   crossfade_triggered, crossfade_finished, track_ended (A), track_started (B)
    assert canonical[0] == TRACK_STARTED
    assert canonical[1] == APPROACHING_CF
    # The crossfade tetra: triggered → finished → from-track-ended → next-started
    assert CROSSFADE_TRIGGERED in canonical
    assert CROSSFADE_FINISHED in canonical
    assert canonical.count(TRACK_STARTED) == 2  # A, then B
    # No spurious extra TRACK_ENDED — exactly one per crossfade ramp.
    assert canonical.count(TRACK_ENDED) == 1


def test_approaching_crossfade_carries_cf_point_sec() -> None:
    """The frontend countdown derives from ``cf_point_sec - currentTime``,
    so the engine must include ``cf_point_sec`` in both ``track_started``
    and ``approaching_crossfade`` events.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b", duration_sec=60.0)])

    # First TRACK_STARTED carries cf_point_sec.
    started = next(e for e in rec.events if e["type"] == TRACK_STARTED)
    assert "cf_point_sec" in started, "TRACK_STARTED must carry cf_point_sec"
    # cf_point = 60 - 12 - 5 = 43.
    assert started["cf_point_sec"] == 43.0

    rec.events.clear()
    # Drive into the warn window.
    engine.report_playback_pos("a", 13.0)
    approach = next(e for e in rec.events if e["type"] == APPROACHING_CF)
    assert "cf_point_sec" in approach, "APPROACHING_CF must carry cf_point_sec"
    assert approach["cf_point_sec"] == 43.0
    # seconds_remaining still set for backwards compat with older clients.
    assert approach["seconds_remaining"] == 30.0


def test_safeguard_does_not_fire_when_crossfade_already_ran() -> None:
    """End-to-end regression for the v2.5.1 endgame safeguard.

    The safeguard's job is to advance the engine when the browser's
    ``ended`` event is lost. It must NOT fire when the regular crossfade
    has already advanced the cursor — otherwise we'd emit a second
    ``track_ended`` for the new (already-playing) track.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b", duration_sec=60.0)])
    rec.events.clear()
    # First ping at 50 s — past the cf point of 43 s for track A.
    engine.report_playback_pos("a", 50.0)
    types_after_cf = rec.types()
    # Crossfade fired and we're now on track B (advanced).
    assert engine._idx == 1
    # Track B's TRACK_STARTED was emitted, but TRACK_ENDED only fired once
    # (for track A — part of the crossfade event tetra). The safeguard did
    # NOT add a second TRACK_ENDED.
    assert types_after_cf.count(TRACK_ENDED) == 1


def test_extend_track_pushes_cf_point_in_event_payload() -> None:
    """``extend_track(N)`` should be reflected in the next
    ``approaching_crossfade`` event's ``cf_point_sec``.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b", duration_sec=60.0)])
    rec.events.clear()
    engine.extend_track(10)  # cf_point: 43 → 53.
    engine.report_playback_pos("a", 23.0)  # cf - 30 = 23 → first warn.
    approach = next(
        (e for e in rec.events if e["type"] == APPROACHING_CF), None
    )
    assert approach is not None
    assert approach["cf_point_sec"] == 53.0
    assert approach["seconds_remaining"] == 30.0


def test_skip_track_emits_track_started_with_cf_point_sec() -> None:
    """``skip_track`` is a hard cut by design (see method docstring), but
    the new track's ``TRACK_STARTED`` still needs ``cf_point_sec`` so the
    UI countdown for the new track ticks correctly.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play(
        [
            _track("a", duration_sec=60.0),
            _track("b", duration_sec=80.0),
        ]
    )
    rec.events.clear()
    engine.skip_track()
    # The new TRACK_STARTED must carry cf_point_sec for track B (80-17=63).
    started = next(e for e in rec.events if e["type"] == TRACK_STARTED)
    assert started["track"]["id"] == "b"
    assert started["cf_point_sec"] == 63.0


def test_natural_end_path_fires_crossfade_not_safeguard() -> None:
    """Belt-and-braces: position pings climbing from 0 → past cf_point on a
    track with a successor must trigger the regular crossfade *before* the
    safeguard. This is the exact path that was broken in the user's real
    session — they reported the next track loaded with no preload pattern,
    indicating a hard cut had won the race against the crossfade.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b", duration_sec=60.0)])
    rec.events.clear()
    # Walk 1 s at a time so we cross 43 s with the regular crossfade and
    # never reach the 58 s safeguard window for track A.
    for t_sec in range(0, 50):
        engine.report_playback_pos("a", float(t_sec))
        # Stop driving once we've advanced — track A's pings post-advance
        # are stale and ignored anyway, but we want to exercise the
        # transition.
        if engine._idx == 1:
            break
    # ``crossfade_triggered`` must appear in the event log; the
    # ``track_ended`` count is exactly 1 (no safeguard duplicate).
    types = rec.types()
    assert CROSSFADE_TRIGGERED in types
    assert types.count(TRACK_ENDED) == 1
    # Browser was told to crossfade (not skip) — verifies the audible path
    # is the dual-deck ramp, not a hard cut.
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "crossfade"
    ]
    assert cmds, "crossfade command must be emitted for natural end-of-track"
    # No "skip" command in the natural path.
    skips = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "skip"
    ]
    assert not skips, "natural end must not emit a hard-cut skip command"
