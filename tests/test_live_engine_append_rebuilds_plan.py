"""Regression tests: ``append_track`` must rebuild the transition plan.

``LiveEngineBrowser._rebuild_transition_plan`` nulls ``_transition_plan``
whenever the queue has no successor to plan for, and only four callers
ever rebuild it — reconnect, ``_emit_next_track``, ``skip_track`` and
``_begin_crossfade``, all of which fire on a cursor MOVE. An endless set
that runs dry therefore parks the plan at None, and the fallback's
``append_track`` (a cursor-STAY event) used to leave it there: every
later crossfade shipped empty ``phase_lock`` anchors and the frontend
silently fell back to a linear fade for the rest of the session.

Observed live 2026-08-13 on a 5h aural set — the last ``[beatmatch]``
diagnostic was transition 42->43 at 12:52, then 2h40m of unplanned
transitions, because the LLM had stopped calling ``extend_set`` (0 calls
across 17 ``playlist_running_low`` pokes) and every append came from the
deterministic fallback.
"""
from __future__ import annotations

from agent.live_engine import LiveEngineBrowser


def _v2_beatgrid(bpm: float, downbeats_sec: list[float]) -> dict:
    return {
        "version": 2,
        "bpm": bpm,
        "first_beat_sec": downbeats_sec[0],
        "downbeats_sec": list(downbeats_sec),
        "beats_per_bar": 4,
        "source": "madmom",
    }


def _track(
    track_id: str,
    *,
    duration_sec: float = 240.0,
    bpm: float = 120.0,
    camelot_key: str = "8A",
    with_grid: bool = True,
) -> dict:
    grid_step = 60.0 / bpm * 4
    t = {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": camelot_key,
        "duration_sec": duration_sec,
        "genre_folder": "lofi - ambient",
        "genre": "lofi - ambient",
        "hot_cues": [],
    }
    if with_grid:
        t["beatgrid"] = _v2_beatgrid(
            bpm, [round(i * grid_step, 3) for i in range(1, 40)]
        )
    return t


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


def _engine(*tracks: dict) -> LiveEngineBrowser:
    """Engine parked on the first track with the given playlist."""
    eng = LiveEngineBrowser(emitter=_Recorder())
    eng.play(list(tracks))
    return eng


def _spy_rebuilds(engine: LiveEngineBrowser) -> list[int]:
    """Record a marker per ``_rebuild_transition_plan`` call."""
    calls: list[int] = []
    original = engine._rebuild_transition_plan

    def _spy() -> None:
        calls.append(1)
        original()

    engine._rebuild_transition_plan = _spy  # type: ignore[method-assign]
    return calls


# --- the fix -----------------------------------------------------------


def test_append_behind_cursor_rebuilds_the_plan():
    """The dry-queue case: appending the successor must rebuild."""
    eng = _engine(_track("a"))
    calls = _spy_rebuilds(eng)

    eng.append_track(_track("b"))

    assert len(calls) == 1


def test_plan_is_restored_after_a_dry_queue_append():
    """State-level assertion — the plan goes None -> not-None.

    This is the actual audible contract: a non-None plan is what makes
    ``_phase_lock_payload`` ship anchors instead of an empty dict.
    """
    eng = _engine(_track("a"))
    assert eng._transition_plan is None  # nothing to plan for yet

    eng.append_track(_track("b"))

    assert eng._transition_plan is not None


def test_repeated_dry_appends_keep_restoring_the_plan():
    """A 24/7 set runs dry many times; every cycle must recover.

    Guards the specific live failure — one recovery is not enough if the
    plan is re-nulled on the next advance.
    """
    eng = _engine(_track("a"))
    for i, tid in enumerate(("b", "c", "d")):
        eng.append_track(_track(tid))
        assert eng._transition_plan is not None, f"append {i} left plan None"
        # Advance onto the freshly appended track: the queue is dry again.
        eng.report_track_ended(eng.playlist[eng._idx]["id"])
        assert eng._transition_plan is None, f"advance {i} should null plan"


# --- precision: don't rebuild when nothing changed ---------------------


def test_append_further_back_does_not_rebuild():
    """An append with a track already queued ahead leaves (cur -> next)
    untouched, so there is nothing to recompute."""
    eng = _engine(_track("a"), _track("b"))
    calls = _spy_rebuilds(eng)

    eng.append_track(_track("c"))  # lands at idx 2, cursor is at 0

    assert calls == []


def test_rejected_duplicate_append_does_not_rebuild():
    """The dedupe guard returns before mutating the playlist."""
    eng = _engine(_track("a"), _track("b"))
    calls = _spy_rebuilds(eng)

    msg = eng.append_track(_track("b"))

    assert "refusing duplicate append" in msg
    assert calls == []


def test_append_without_id_does_not_rebuild():
    eng = _engine(_track("a"))
    calls = _spy_rebuilds(eng)

    msg = eng.append_track({"display_name": "no id"})

    assert "must include an 'id' field" in msg
    assert calls == []


# --- the rebuild must not break the append contract --------------------


def test_append_still_returns_its_position_message():
    eng = _engine(_track("a"))
    msg = eng.append_track(_track("b"))
    assert "Appended" in msg
    assert "position 2" in msg


def test_append_still_rearms_the_low_water_guard():
    """``append_track`` re-arms ``playlist_running_low``; the added
    rebuild must not disturb that."""
    eng = _engine(_track("a"))
    eng._low_water_fired = True
    eng._low_water_at = 123.0

    eng.append_track(_track("b"))

    assert eng._low_water_fired is False
    assert eng._low_water_at is None


def test_rebuild_runs_outside_the_lock():
    """``_lock`` is a plain ``threading.Lock`` — rebuilding while holding
    it would deadlock. Reaching the assertion at all proves we released
    it, and the lock must be free afterwards."""
    eng = _engine(_track("a"))

    eng.append_track(_track("b"))

    assert eng._lock.acquire(blocking=False) is True
    eng._lock.release()


def test_append_without_beatgrids_degrades_to_a_fallback_plan():
    """Gridless tracks still get a plan — ``build_live_transition_plan``
    returns a ``fallback`` phrase tier (linear fade, no downbeat lock)
    rather than None. The append path must surface that instead of
    raising, so a catalog entry with no v2 beatgrid can still be
    appended by the endless fallback."""
    eng = _engine(_track("a", with_grid=False))

    msg = eng.append_track(_track("b", with_grid=False))

    assert "Appended" in msg
    assert eng._transition_plan is not None
    assert eng._transition_plan.phrase_tier == "fallback"
