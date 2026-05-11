"""Unit tests for the v2.6.0 endless / improvisation mode plumbing.

Covers the engine API surface (``append_track``, ``_maybe_end_or_extend``
gate, ``playlist_running_low`` emission, ``_autoplay_pick`` ranking).
Uses ``LiveEngineBrowser`` for the integration tests because it has the
simpler state machine (no audio device, no pre-stretch) and exercises
exactly the same code paths that the web/YouTube use case hits.
"""
from __future__ import annotations

import time

import pytest

from agent.live_engine import (
    ENDLESS_APPEND_CAP,
    ENDLESS_GRACE_SEC,
    ENDLESS_WARNING,
    PLAYLIST_RUNNING_LOW,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
    _autoplay_pick,
    _camelot_distance,
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


# ---------------------------------------------------------------------------
# _camelot_distance — pure function unit tests
# ---------------------------------------------------------------------------

def test_camelot_distance_identical_keys_is_zero():
    assert _camelot_distance("8A", "8A") == 0.0


def test_camelot_distance_adjacent_number_same_letter_is_one():
    assert _camelot_distance("8A", "9A") == 1.0
    assert _camelot_distance("8A", "7A") == 1.0


def test_camelot_distance_wheel_wraps_around():
    # 1A and 12A are adjacent on the wheel.
    assert _camelot_distance("1A", "12A") == 1.0


def test_camelot_distance_letter_flip_adds_half():
    # Same number, A vs B = the "energy boost" move.
    assert _camelot_distance("8A", "8B") == 0.5
    assert _camelot_distance("8A", "9B") == 1.5


def test_camelot_distance_unknown_or_malformed_returns_max():
    assert _camelot_distance(None, "8A") == 6.0
    assert _camelot_distance("8A", None) == 6.0
    assert _camelot_distance("garbage", "8A") == 6.0
    assert _camelot_distance("13A", "8A") == 6.0  # out of range
    assert _camelot_distance("8C", "8A") == 6.0   # bad letter


# ---------------------------------------------------------------------------
# _autoplay_pick — pure function unit tests
# ---------------------------------------------------------------------------

def test_autoplay_pick_filters_by_genre_folder():
    catalog = [
        _track("a", genre_folder="techno"),
        _track("b", genre_folder="lofi - ambient", bpm=76),
        _track("c", genre_folder="lofi - ambient", bpm=80),
    ]
    current = _track("playing", bpm=76, genre_folder="lofi - ambient")
    pick = _autoplay_pick(current, catalog, "lofi - ambient", set())
    assert pick is not None
    assert pick["genre_folder"] == "lofi - ambient"


def test_autoplay_pick_drops_already_played_ids():
    catalog = [
        _track("a", genre_folder="lofi - ambient", bpm=76),
        _track("b", genre_folder="lofi - ambient", bpm=80),
    ]
    current = _track("playing", bpm=78, genre_folder="lofi - ambient")
    pick = _autoplay_pick(current, catalog, "lofi - ambient", {"a"})
    assert pick is not None and pick["id"] == "b"


def test_autoplay_pick_returns_none_when_no_in_genre_candidates():
    catalog = [_track("a", genre_folder="techno", bpm=130)]
    current = _track("playing", bpm=76, genre_folder="lofi - ambient")
    assert _autoplay_pick(current, catalog, "lofi - ambient", set()) is None


def test_autoplay_pick_ranks_closest_bpm_first():
    catalog = [
        _track("far", genre_folder="lofi - ambient", bpm=120),
        _track("near", genre_folder="lofi - ambient", bpm=78),
        _track("medium", genre_folder="lofi - ambient", bpm=90),
    ]
    current = _track("playing", bpm=76, genre_folder="lofi - ambient")
    pick = _autoplay_pick(current, catalog, "lofi - ambient", set())
    assert pick is not None and pick["id"] == "near"


def test_autoplay_pick_breaks_bpm_ties_with_camelot_distance():
    # Two candidates equidistant in BPM — pick the closer Camelot.
    catalog = [
        _track("a", genre_folder="lofi - ambient", bpm=80, camelot_key="3A"),
        _track("b", genre_folder="lofi - ambient", bpm=80, camelot_key="8A"),
    ]
    current = _track("playing", bpm=82, genre_folder="lofi - ambient", camelot_key="8A")
    pick = _autoplay_pick(current, catalog, "lofi - ambient", set())
    assert pick is not None and pick["id"] == "b"


def test_autoplay_pick_returns_none_on_empty_catalog():
    current = _track("playing")
    assert _autoplay_pick(current, [], "lofi - ambient", set()) is None


# ---------------------------------------------------------------------------
# append_track — Browser engine
# ---------------------------------------------------------------------------

def test_append_track_adds_to_playlist_and_returns_position():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    rec.events.clear()

    msg = engine.append_track(_track("b"))
    assert "Appended" in msg and "position 2" in msg
    assert [t["id"] for t in engine.playlist] == ["a", "b"]


def test_append_track_rejects_track_without_id():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    msg = engine.append_track({"display_name": "no-id"})
    assert "id" in msg.lower()
    assert len(engine.playlist) == 1


def test_append_track_enforces_session_cap():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    # Burn through the cap.
    engine._endless_appended = ENDLESS_APPEND_CAP
    rec.events.clear()
    msg = engine.append_track(_track("b"))
    assert "cap reached" in msg.lower()
    # No new tracks landed.
    assert [t["id"] for t in engine.playlist] == ["a"]
    # Warning event surfaced.
    assert any(
        e.get("type") == ENDLESS_WARNING and e.get("reason") == "cap_reached"
        for e in rec.events
    )


def test_append_track_resets_low_water_guard():
    """A fresh append re-arms the playlist_running_low edge so the
    engine can fire it again once the new tail becomes the last
    track."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    engine._low_water_fired = True
    engine._low_water_at = time.monotonic()
    engine.append_track(_track("b"))
    assert engine._low_water_fired is False
    assert engine._low_water_at is None


# ---------------------------------------------------------------------------
# _maybe_end_or_extend — gating semantics on the Browser engine
# ---------------------------------------------------------------------------

def test_endless_off_emits_session_ended_immediately():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    # endless mode default is False — _maybe_end_or_extend should
    # behave exactly like the legacy engine.
    assert engine._maybe_end_or_extend(_track("a")) is True
    assert SESSION_ENDED in rec.types()


def test_endless_on_with_successor_returns_false_and_no_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    engine._endless_mode = True
    rec.events.clear()
    assert engine._maybe_end_or_extend(_track("a")) is False
    assert SESSION_ENDED not in rec.types()


def test_endless_on_grace_window_blocks_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    engine._endless_mode = True
    rec.events.clear()
    # First entry starts the grace clock; no SESSION_ENDED yet.
    assert engine._maybe_end_or_extend(_track("a")) is False
    assert SESSION_ENDED not in rec.types()
    # Re-poll inside the grace window still defers.
    assert engine._maybe_end_or_extend(_track("a")) is False
    assert SESSION_ENDED not in rec.types()


def test_endless_on_grace_elapsed_with_no_candidates_ends_session(monkeypatch):
    """Browser engine reads catalog fresh in _maybe_end_or_extend — when
    that returns no in-genre candidates, an endless_warning event is
    emitted and the session ends normally (no infinite loop)."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", genre_folder="lofi - ambient")])
    engine._endless_mode = True
    engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
    # Empty catalog → no candidates.
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [])
    rec.events.clear()
    assert engine._maybe_end_or_extend(_track("a")) is True
    types = rec.types()
    assert ENDLESS_WARNING in types
    assert SESSION_ENDED in types
    # Warning carries the no_candidates reason for the frontend banner.
    warn = next(e for e in rec.events if e.get("type") == ENDLESS_WARNING)
    assert warn.get("reason") == "no_candidates"


def test_endless_on_grace_elapsed_with_candidate_appends_and_continues(monkeypatch):
    """When the grace window expires with no LLM append, the engine
    auto-picks an in-genre track from the catalog and appends it
    itself — no SESSION_ENDED, no warning."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", genre_folder="lofi - ambient", bpm=76)])
    engine._endless_mode = True
    engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
    monkeypatch.setattr(
        "agent.live_engine._load_catalog",
        lambda: [_track("auto-pick", genre_folder="lofi - ambient", bpm=78)],
    )
    rec.events.clear()
    assert engine._maybe_end_or_extend(
        _track("a", genre_folder="lofi - ambient", bpm=76)
    ) is False
    # The new track is now the tail.
    assert engine.playlist[-1]["id"] == "auto-pick"
    # No SESSION_ENDED, no warning.
    types = rec.types()
    assert SESSION_ENDED not in types
    assert ENDLESS_WARNING not in types


# ---------------------------------------------------------------------------
# playlist_running_low edge — Browser engine
# ---------------------------------------------------------------------------

def test_playlist_running_low_fires_once_when_remaining_one_and_endless():
    """Drive the engine through APPROACHING_CF when remaining == 1
    and endless is ON. The edge should fire exactly once per
    'approaching-the-last-track' window."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60), _track("b", duration_sec=60)])
    engine._endless_mode = True
    rec.events.clear()

    # 35 s in, cf at ~48 s (60 - 12) so secs_to_cf = 13 — well under
    # approach_warn_sec. APPROACHING_CF + PLAYLIST_RUNNING_LOW should
    # both fire.
    engine.report_playback_pos(track_id="a", current_time=35.0)
    types = rec.types()
    assert PLAYLIST_RUNNING_LOW in types
    # Pinging again shouldn't re-fire the edge.
    n_first = types.count(PLAYLIST_RUNNING_LOW)
    engine.report_playback_pos(track_id="a", current_time=37.0)
    n_second = rec.types().count(PLAYLIST_RUNNING_LOW)
    assert n_second == n_first


def test_playlist_running_low_does_not_fire_when_endless_off():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60), _track("b", duration_sec=60)])
    # endless OFF — even with remaining == 1, no PLAYLIST_RUNNING_LOW.
    rec.events.clear()
    engine.report_playback_pos(track_id="a", current_time=35.0)
    assert PLAYLIST_RUNNING_LOW not in rec.types()


def test_playlist_running_low_does_not_fire_when_more_than_one_track_left():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, approach_warn_sec=30)
    engine.play(
        [_track("a", duration_sec=60), _track("b", duration_sec=60), _track("c", duration_sec=60)]
    )
    engine._endless_mode = True
    rec.events.clear()
    engine.report_playback_pos(track_id="a", current_time=35.0)
    # remaining = 2 → no running-low signal even with endless ON.
    assert PLAYLIST_RUNNING_LOW not in rec.types()


# ---------------------------------------------------------------------------
# End-to-end TRACK_ENDED path with endless mode
# ---------------------------------------------------------------------------

def test_track_ended_with_endless_and_auto_pick_advances_naturally(monkeypatch):
    """The deterministic-fallback path inside report_track_ended:
    last track ends, no append from LLM, grace expired → engine
    picks an in-genre continuation, appends it, then advances to it
    instead of emitting SESSION_ENDED."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=10, genre_folder="lofi - ambient", bpm=76)])
    engine._endless_mode = True
    # Pretend the grace window already elapsed.
    engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
    monkeypatch.setattr(
        "agent.live_engine._load_catalog",
        lambda: [_track("next", genre_folder="lofi - ambient", bpm=78)],
    )
    rec.events.clear()
    engine.report_track_ended("a")
    types = rec.types()
    # TRACK_ENDED for the last track, then TRACK_STARTED for the
    # auto-picked successor — no SESSION_ENDED in between.
    assert TRACK_ENDED in types
    assert TRACK_STARTED in types
    assert SESSION_ENDED not in types
    # New track is loaded as the current one.
    assert engine.playlist[engine._idx]["id"] == "next"
