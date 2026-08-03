"""Tests for v3.9.1 — session-eligibility screen (minimum track duration).

Motivation (2026-08-03 live): the aural batch contains 35–120 s pieces
that read as cut-off tracks in a mix. The rule: tracks shorter than
``MIN_TRACK_DURATION_SEC`` (default 120 s) are never SELECTED into a
session — offline pipeline, planner playlist, LLM candidate search,
explicit appends/swaps, and the endless fallback picker all screen.
Catalog loaders and id lookups (streaming, ratings) are untouched.

Covers:
  - the pure helpers in ``agent/eligibility.py`` (boundaries, unknowns)
  - ``_autoplay_pick`` (endless fallback) screening, incl. recycle tiers
  - ``pick_next_track`` never surfacing short candidates
  - ``extend_set`` / ``swap_track`` rejecting short ids with coaching
  - ``propose_playlist`` screening before clustering
  - ``main.load_catalog`` screening for the offline pipeline
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import agent.eligibility as eligibility
from agent.eligibility import (
    MIN_TRACK_DURATION_SEC,
    filter_session_eligible,
    ineligibility_reason,
    is_session_eligible,
)
from agent.live_engine import _autoplay_pick
from agent.tools import extend_set, pick_next_track, propose_playlist, swap_track


def _t(track_id: str, duration_sec, *, bpm: float = 100.0, genre: str = "lofi - ambient") -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "genre_folder": genre,
        "genre": genre,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestIsSessionEligible:
    def test_track_at_exactly_the_minimum_is_eligible(self):
        assert is_session_eligible(_t("x", MIN_TRACK_DURATION_SEC)) is True

    def test_track_just_under_the_minimum_is_not_eligible(self):
        assert is_session_eligible(_t("x", MIN_TRACK_DURATION_SEC - 0.1)) is False

    def test_long_track_is_eligible(self):
        assert is_session_eligible(_t("x", 300.0)) is True

    def test_unknown_duration_stays_eligible(self):
        # Legacy entries predate duration backfill — dropping them would
        # silently shrink genres; --fix-incomplete makes the screen bite.
        assert is_session_eligible(_t("x", None)) is True
        assert is_session_eligible({"id": "no-dur-key"}) is True

    def test_garbage_duration_stays_eligible(self):
        assert is_session_eligible(_t("x", "not-a-number")) is True

    def test_env_override_is_honoured_at_call_time(self, monkeypatch):
        monkeypatch.setattr(eligibility, "MIN_TRACK_DURATION_SEC", 30.0)
        assert is_session_eligible(_t("x", 45.0)) is True
        monkeypatch.setattr(eligibility, "MIN_TRACK_DURATION_SEC", 0.0)
        assert is_session_eligible(_t("x", 5.0)) is True  # 0 disables the screen


class TestFilterAndReason:
    def test_filter_preserves_order_and_drops_short(self):
        tracks = [_t("long1", 240), _t("short", 64), _t("long2", 180)]
        assert [t["id"] for t in filter_session_eligible(tracks)] == ["long1", "long2"]

    def test_reason_none_for_eligible(self):
        assert ineligibility_reason(_t("x", 240)) is None

    def test_reason_mentions_both_durations(self):
        reason = ineligibility_reason(_t("x", 64.2))
        assert reason is not None
        assert "64" in reason
        assert f"{MIN_TRACK_DURATION_SEC:.0f}" in reason


# ---------------------------------------------------------------------------
# _autoplay_pick (endless fallback picker)
# ---------------------------------------------------------------------------

class TestAutoplayPickScreens:
    def test_short_track_never_picked_even_when_best_match(self):
        current = _t("playing", 240, bpm=100)
        catalog = [
            _t("short-perfect", 64, bpm=100),   # perfect BPM, too short
            _t("long-worse", 300, bpm=110),
        ]
        pick = _autoplay_pick(current, catalog, "lofi - ambient", set())
        assert pick is not None and pick["id"] == "long-worse"

    def test_all_short_catalog_returns_none(self):
        current = _t("playing", 240)
        catalog = [_t("s1", 30), _t("s2", 90), _t("s3", 119.9)]
        assert _autoplay_pick(current, catalog, "lofi - ambient", set()) is None

    def test_recycle_tier_also_screens_short_tracks(self):
        # allow_repeats recycle must not resurrect a short track either.
        current = _t("playing", 240, bpm=100)
        catalog = [_t("short", 64, bpm=100), _t("long", 300, bpm=130)]
        pick = _autoplay_pick(
            current, catalog, "lofi - ambient", {"short", "long", "playing"},
            allow_repeats=True, recent_ids=["playing"],
        )
        assert pick is not None and pick["id"] == "long"


# ---------------------------------------------------------------------------
# pick_next_track (LLM candidate search)
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_pipeline_catalog():
    import web.backend.pipeline as pipeline

    catalog = [
        _t("long-a", 240, bpm=100),
        _t("short-a", 64, bpm=100),   # would be the perfect match
        _t("long-b", 300, bpm=104),
    ]
    with patch.object(pipeline, "load_catalog", return_value=(catalog, ["lofi - ambient"])):
        yield


def test_pick_next_track_never_surfaces_short_tracks(patched_pipeline_catalog):
    out = pick_next_track(95.0, 105.0, {})
    assert "long-a" in out
    assert "long-b" in out
    assert "short-a" not in out


def test_pick_next_track_reports_no_match_when_only_short_tracks_fit(monkeypatch):
    import web.backend.pipeline as pipeline

    monkeypatch.setattr(
        pipeline, "load_catalog",
        lambda _g=None: ([_t("short-a", 64, bpm=100)], ["lofi - ambient"]),
    )
    out = pick_next_track(95.0, 105.0, {})
    assert "No tracks in catalog matching" in out


# ---------------------------------------------------------------------------
# extend_set / swap_track (explicit-id paths)
# ---------------------------------------------------------------------------

class _FakeEngine:
    def __init__(self):
        self.appended: list[dict] = []

    def append_track(self, track: dict) -> str:
        self.appended.append(track)
        return f"Queued '{track['display_name']}'"


def test_extend_set_rejects_short_track_with_coaching(monkeypatch):
    import web.backend.pipeline as pipeline

    engine = _FakeEngine()
    monkeypatch.setattr(
        pipeline, "load_catalog",
        lambda _g=None: ([_t("short-a", 64)], []),
    )
    out = extend_set("short-a", {"_engine": engine})
    assert "NOT appended" in out
    assert "pick_next_track" in out
    assert engine.appended == []


def test_extend_set_appends_eligible_track(monkeypatch):
    import web.backend.pipeline as pipeline

    engine = _FakeEngine()
    monkeypatch.setattr(
        pipeline, "load_catalog",
        lambda _g=None: ([_t("long-a", 240)], []),
    )
    out = extend_set("long-a", {"_engine": engine})
    assert "Queued" in out
    assert [t["id"] for t in engine.appended] == ["long-a"]


def test_swap_track_rejects_short_replacement(tmp_path, monkeypatch):
    import agent.tools as tools

    catalog_path = tmp_path / "tracks.json"
    catalog_path.write_text(
        json.dumps({"tracks": [_t("short-a", 64), _t("long-a", 240)]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "_CATALOG_PATH", catalog_path)
    playlist = [_t("p1", 240), _t("p2", 240)]
    ctx = {"playlist": playlist}
    out = swap_track(2, "short-a", ctx)
    assert "NOT" in out
    assert playlist[1]["id"] == "p2"  # untouched
    # And the eligible replacement still works.
    out2 = swap_track(2, "long-a", ctx)
    assert "NOT" not in out2
    assert playlist[1]["id"] == "long-a"


# ---------------------------------------------------------------------------
# propose_playlist (planner)
# ---------------------------------------------------------------------------

def _write_catalog(tmp_path, tracks):
    p = tmp_path / "tracks.json"
    p.write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
    return p


def test_propose_playlist_screens_short_tracks(tmp_path, monkeypatch):
    import agent.tools as tools

    tracks = [
        _t("long-a", 240, bpm=100),
        _t("long-b", 250, bpm=102),
        _t("long-c", 260, bpm=104),
        _t("short-a", 64, bpm=100),
        _t("short-b", 90, bpm=102),
    ]
    monkeypatch.setattr(tools, "_CATALOG_PATH", _write_catalog(tmp_path, tracks))
    out = propose_playlist("lofi - ambient", 30, "calm", {})
    assert "short-a" not in out
    assert "short-b" not in out
    assert "long-a" in out or "Track long-a" in out


def test_propose_playlist_all_short_returns_clear_error(tmp_path, monkeypatch):
    import agent.tools as tools

    tracks = [_t("short-a", 64), _t("short-b", 90)]
    monkeypatch.setattr(tools, "_CATALOG_PATH", _write_catalog(tmp_path, tracks))
    out = propose_playlist("lofi - ambient", 30, "calm", {})
    assert "No session-eligible tracks" in out


# ---------------------------------------------------------------------------
# main.load_catalog (offline pipeline)
# ---------------------------------------------------------------------------

def test_main_load_catalog_screens_short_tracks(tmp_path, monkeypatch, capsys):
    import main as main_mod

    catalog_path = _write_catalog(
        tmp_path, [_t("long-a", 240), _t("short-a", 64)],
    )
    monkeypatch.setattr(main_mod, "CATALOG_PATH", str(catalog_path))
    tracks = main_mod.load_catalog("lofi - ambient")
    assert [t["id"] for t in tracks] == ["long-a"]
    assert "Screened 1 track" in capsys.readouterr().out


def test_main_load_catalog_exits_when_all_short(tmp_path, monkeypatch):
    import main as main_mod

    catalog_path = _write_catalog(tmp_path, [_t("short-a", 64)])
    monkeypatch.setattr(main_mod, "CATALOG_PATH", str(catalog_path))
    with pytest.raises(SystemExit):
        main_mod.load_catalog("lofi - ambient")
