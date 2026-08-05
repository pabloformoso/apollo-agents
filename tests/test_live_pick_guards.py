"""Tests for v3.9.2 — live-pick guards: dedupe + session-genre fence.

Two live incidents drive these:

- 2026-08-01 ('Golden Groove'×2) and 2026-08-04 ('Oceanic Flow'×2): the
  same track id landed in consecutive playlist slots and the set
  crossfaded a track into itself. Guard (a): ``append_track`` rejects
  any id that is currently playing or queued ahead, and the endless
  pickers hard-exclude the upcoming queue in EVERY tier (incl. the
  allow_repeats recycle tiers) via ``never_ids``.

- 2026-08-04 (aural→lofi flip via 'Glockenspiel Dream'): one
  out-of-genre LLM pick permanently flips the endless engine's genre
  (it inherits genre from the current track). Guard (b):
  ``pick_next_track`` and ``extend_set`` fence candidates to the
  session's ctx genre, with an explicit ``include_other_genres`` /
  ``allow_other_genre`` escape hatch reserved for audience requests.
"""
from __future__ import annotations

from queue import Queue
from unittest.mock import patch

import pytest

from agent.live_engine import LiveEngineBrowser, LiveEngineLocal, _autoplay_pick
from agent.tools import extend_set, pick_next_track


def _track(
    track_id: str,
    *,
    duration_sec: float = 240.0,
    bpm: float = 75.0,
    camelot_key: str = "8A",
    genre_folder: str = "lofi - ambient",
    display_name: str | None = None,
) -> dict:
    return {
        "id": track_id,
        "display_name": display_name or f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": camelot_key,
        "duration_sec": duration_sec,
        "genre_folder": genre_folder,
        "genre": genre_folder,
        "hot_cues": [],
    }


def _browser_engine(playlist: list[dict]) -> LiveEngineBrowser:
    engine = LiveEngineBrowser(emitter=lambda e: None, approach_warn_sec=30)
    engine.play(playlist)
    return engine


# ---------------------------------------------------------------------------
# (a) append_track dedupe guard
# ---------------------------------------------------------------------------

class TestAppendDedupeBrowser:
    def test_rejects_currently_playing_track(self):
        engine = _browser_engine([_track("a"), _track("b")])
        out = engine.append_track(_track("a"))
        assert "refusing duplicate append" in out
        assert [t["id"] for t in engine.playlist] == ["a", "b"]

    def test_rejects_track_queued_ahead(self):
        engine = _browser_engine([_track("a"), _track("b")])
        out = engine.append_track(_track("b"))
        assert "refusing duplicate append" in out
        assert [t["id"] for t in engine.playlist] == ["a", "b"]

    def test_allows_replaying_an_already_played_track(self):
        # Recycling PLAYED tracks is what keeps a 24/7 endless set
        # alive — only current + upcoming are fenced.
        engine = _browser_engine([_track("a"), _track("b")])
        engine._idx = 1  # 'a' is behind the cursor now
        out = engine.append_track(_track("a"))
        assert "refusing" not in out
        assert [t["id"] for t in engine.playlist] == ["a", "b", "a"]

    def test_allows_fresh_track(self):
        engine = _browser_engine([_track("a")])
        out = engine.append_track(_track("c"))
        assert "Appended" in out
        assert engine.playlist[-1]["id"] == "c"

    def test_duplicate_rejection_does_not_consume_append_cap(self):
        engine = _browser_engine([_track("a")])
        before = engine._endless_appended
        engine.append_track(_track("a"))
        assert engine._endless_appended == before


class TestAppendDedupeLocal:
    def test_rejects_upcoming_and_allows_played(self):
        engine = LiveEngineLocal([_track("a"), _track("b")], Queue())
        assert "refusing duplicate append" in engine.append_track(_track("b"))
        engine._idx = 1
        out = engine.append_track(_track("a"))
        assert "refusing" not in out
        assert engine.playlist[-1]["id"] == "a"


# ---------------------------------------------------------------------------
# (a) _autoplay_pick never_ids — hard exclusion across ALL tiers
# ---------------------------------------------------------------------------

class TestAutoplayPickNeverIds:
    def test_never_ids_excluded_in_recycle_tier(self):
        # The 'Oceanic Flow' shape: catalog exhausted → recycle, and the
        # best-ranked candidate is ALREADY QUEUED. It must be skipped
        # even though the recycle tier drops exclude_ids.
        current = _track("playing", bpm=75)
        catalog = [
            _track("queued-next", bpm=75),   # perfect match, but queued
            _track("old", bpm=90),
        ]
        pick = _autoplay_pick(
            current, catalog, "lofi - ambient",
            {"queued-next", "old", "playing"},
            allow_repeats=True, recent_ids=["playing"],
            never_ids={"playing", "queued-next"},
        )
        assert pick is not None and pick["id"] == "old"

    def test_returns_none_when_everything_is_upcoming(self):
        current = _track("playing")
        catalog = [_track("queued-next")]
        pick = _autoplay_pick(
            current, catalog, "lofi - ambient", set(),
            allow_repeats=True, never_ids={"playing", "queued-next"},
        )
        assert pick is None

    def test_no_never_ids_keeps_legacy_behaviour(self):
        current = _track("playing", bpm=75)
        catalog = [_track("x", bpm=76)]
        pick = _autoplay_pick(current, catalog, "lofi - ambient", set())
        assert pick is not None and pick["id"] == "x"


class TestEngineFallbackSkipsQueued:
    def test_inflight_recycle_never_picks_upcoming_queue(self, monkeypatch):
        """Engine-level 'Oceanic Flow' regression: playlist tail already
        contains the recycle tier's best match — the fallback must reach
        for a different track, never double-queue the tail."""
        import time
        from agent.live_engine import ENDLESS_GRACE_SEC

        engine = _browser_engine([
            _track("a", duration_sec=60, bpm=75),
            _track("b", duration_sec=60, bpm=75),
        ])
        engine._endless_mode = True
        engine._idx = 1  # 'b' playing, nothing queued after it
        monkeypatch.setattr(
            "agent.live_engine._load_catalog",
            lambda: [_track("a", bpm=75), _track("b", bpm=75)],
        )
        engine.report_playback_pos(track_id="b", current_time=35.0)
        engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
        engine.report_playback_pos(track_id="b", current_time=50.0)
        # 'b' (current) must never be re-queued; 'a' (played) is the
        # only legal recycle.
        assert engine.playlist[-1]["id"] == "a"
        assert [t["id"] for t in engine.playlist].count("b") == 1


# ---------------------------------------------------------------------------
# (b) pick_next_track — session-genre fence
# ---------------------------------------------------------------------------

_MIXED_CATALOG = [
    _track("aural-slow", bpm=52, genre_folder="aural", display_name="Serenity Strings"),
    _track("aural-mid", bpm=60, genre_folder="aural", display_name="Deep Vault"),
    _track("lofi-75", bpm=75, genre_folder="lofi - ambient", display_name="Glockenspiel Dream"),
]


@pytest.fixture
def mixed_catalog():
    import web.backend.pipeline as pipeline

    with patch.object(
        pipeline, "load_catalog",
        return_value=(list(_MIXED_CATALOG), ["aural", "lofi - ambient"]),
    ):
        yield


class TestPickNextTrackGenreFence:
    def test_out_of_genre_tracks_never_surface(self, mixed_catalog):
        out = pick_next_track(40.0, 80.0, {"genre": "aural"})
        assert "aural-slow" in out
        assert "lofi-75" not in out

    def test_the_2026_08_04_bridge_is_blocked(self, mixed_catalog):
        # The incident: aural session, LLM asked for ~70-80 BPM "to get
        # the energy up" and the only matches were lofi. Must now come
        # back empty with the fence explained, not surface the bridge.
        out = pick_next_track(70.0, 80.0, {"genre": "aural"})
        assert "lofi-75" not in out
        assert "restricted to the session's genre" in out

    def test_explicit_override_allows_other_genres(self, mixed_catalog):
        out = pick_next_track(70.0, 80.0, {"genre": "aural"}, include_other_genres=True)
        assert "lofi-75" in out

    def test_no_ctx_genre_stays_unrestricted(self, mixed_catalog):
        out = pick_next_track(70.0, 80.0, {})
        assert "lofi-75" in out


# ---------------------------------------------------------------------------
# (b) extend_set — session-genre fence + engine dedupe passthrough
# ---------------------------------------------------------------------------

class _RecordingEngine:
    def __init__(self):
        self.appended: list[dict] = []

    def append_track(self, track: dict) -> str:
        self.appended.append(track)
        return f"Appended '{track['display_name']}' at position 99."


def _patch_catalog(monkeypatch, tracks):
    import web.backend.pipeline as pipeline

    monkeypatch.setattr(pipeline, "load_catalog", lambda _g=None: (tracks, []))


class TestExtendSetGenreFence:
    def test_rejects_out_of_genre_with_coaching(self, monkeypatch):
        engine = _RecordingEngine()
        _patch_catalog(monkeypatch, list(_MIXED_CATALOG))
        out = extend_set("lofi-75", {"_engine": engine, "genre": "aural"})
        assert "NOT appended" in out
        assert "pick_next_track" in out
        assert engine.appended == []

    def test_explicit_override_appends_other_genre(self, monkeypatch):
        engine = _RecordingEngine()
        _patch_catalog(monkeypatch, list(_MIXED_CATALOG))
        out = extend_set(
            "lofi-75", {"_engine": engine, "genre": "aural"},
            allow_other_genre=True,
        )
        assert "Appended" in out
        assert [t["id"] for t in engine.appended] == ["lofi-75"]

    def test_in_genre_append_passes(self, monkeypatch):
        engine = _RecordingEngine()
        _patch_catalog(monkeypatch, list(_MIXED_CATALOG))
        out = extend_set("aural-mid", {"_engine": engine, "genre": "aural"})
        assert "Appended" in out

    def test_no_ctx_genre_stays_unrestricted(self, monkeypatch):
        engine = _RecordingEngine()
        _patch_catalog(monkeypatch, list(_MIXED_CATALOG))
        out = extend_set("lofi-75", {"_engine": engine})
        assert "Appended" in out

    def test_duplicate_append_rejection_reaches_the_llm(self, monkeypatch):
        # End-to-end through a REAL browser engine: the id is already
        # queued, so the engine's dedupe guard answers and extend_set
        # relays it verbatim for the model to re-pick.
        engine = _browser_engine([
            _track("aural-slow", genre_folder="aural"),
            _track("aural-mid", genre_folder="aural"),
        ])
        _patch_catalog(monkeypatch, list(_MIXED_CATALOG))
        out = extend_set("aural-mid", {"_engine": engine, "genre": "aural"})
        assert "refusing duplicate append" in out
        assert [t["id"] for t in engine.playlist] == ["aural-slow", "aural-mid"]
