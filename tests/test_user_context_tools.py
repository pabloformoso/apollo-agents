"""Tests for v2.3.0 — agent tools that surface per-user data.

Covers `agent.tools.get_user_playlists`, `get_playlist_tracks`,
`get_user_ratings`, `get_favorite_tracks`. The four tools lazily import
`web.backend.{db, pipeline}` to avoid circular imports; this module sets
up an isolated SQLite database via the existing `db.DB_PATH` indirection
and stubs `pipeline.load_catalog` so we don't need real `tracks/`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Make the project root importable so `from web.backend ...` works when
# this file is collected outside the `tests/web/` package.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point `db.DB_PATH` at a temp SQLite file and run init_db()."""
    from web.backend import db

    test_db = tmp_path / "user_context.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    return db


@pytest.fixture
def stub_catalog(monkeypatch):
    """Replace `pipeline.load_catalog` with a small in-memory catalog so the
    tools that hydrate track ids don't need a real `tracks/tracks.json`."""
    from web.backend import pipeline

    catalog = [
        {
            "id": "lofi-fav-1",
            "display_name": "Lofi Favourite One",
            "genre_folder": "lofi",
            "genre": "lofi",
            "bpm": 90,
            "camelot_key": "8A",
        },
        {
            "id": "lofi-fav-2",
            "display_name": "Lofi Favourite Two",
            "genre_folder": "lofi",
            "genre": "lofi",
            "bpm": 92,
            "camelot_key": "9A",
        },
        {
            "id": "techno-fav-1",
            "display_name": "Techno Favourite",
            "genre_folder": "techno",
            "genre": "techno",
            "bpm": 130,
            "camelot_key": "10A",
        },
        {
            "id": "lofi-mid",
            "display_name": "Lofi Mid",
            "genre_folder": "lofi",
            "genre": "lofi",
            "bpm": 88,
            "camelot_key": "7A",
        },
    ]

    def _fake_load(genre=None):
        if genre:
            t = genre.strip().lower()
            return [c for c in catalog if c["genre_folder"].lower() == t], ["lofi", "techno"]
        return catalog, ["lofi", "techno"]

    monkeypatch.setattr(pipeline, "load_catalog", _fake_load)
    return catalog


# ---------------------------------------------------------------------------
# get_user_playlists
# ---------------------------------------------------------------------------

def test_get_user_playlists_with_user_id(isolated_db):
    from agent.tools import get_user_playlists

    user_id = isolated_db.create_user("alice", "alice@test.io", "h")
    p1 = isolated_db.create_playlist(user_id, "Late Night")
    isolated_db.add_tracks_to_playlist(p1["id"], ["t1", "t2", "t3"])
    isolated_db.create_playlist(user_id, "Peak Energy")

    out = get_user_playlists({"user_id": user_id})

    assert "| id | name | tracks |" in out
    assert "Late Night" in out
    assert "| 3 |" in out  # track count for "Late Night"
    assert "Peak Energy" in out
    assert "| 0 |" in out  # empty playlist


def test_get_user_playlists_without_user_id(isolated_db):
    from agent.tools import get_user_playlists

    assert get_user_playlists({}) == "User context not available."


def test_get_user_playlists_user_has_none(isolated_db):
    from agent.tools import get_user_playlists

    user_id = isolated_db.create_user("bob", "bob@test.io", "h")
    out = get_user_playlists({"user_id": user_id})
    assert out == "User has no saved playlists."


# ---------------------------------------------------------------------------
# get_playlist_tracks (with ownership check)
# ---------------------------------------------------------------------------

def test_get_playlist_tracks_owner(isolated_db, stub_catalog):
    from agent.tools import get_playlist_tracks

    user_id = isolated_db.create_user("carol", "carol@test.io", "h")
    p = isolated_db.create_playlist(user_id, "Mixtape")
    isolated_db.add_tracks_to_playlist(p["id"], ["lofi-fav-1", "techno-fav-1"])

    out = get_playlist_tracks(p["id"], {"user_id": user_id})

    assert "| pos | id | display_name | bpm | key |" in out
    assert "| 0 |" in out
    assert "lofi-fav-1" in out
    assert "Lofi Favourite One" in out
    assert "techno-fav-1" in out


def test_get_playlist_tracks_ownership_denial(isolated_db, stub_catalog):
    """User A asks for User B's playlist → 'Not authorized.'"""
    from agent.tools import get_playlist_tracks

    user_a = isolated_db.create_user("usera", "a@test.io", "h")
    user_b = isolated_db.create_user("userb", "b@test.io", "h")
    pb = isolated_db.create_playlist(user_b, "B's Mix")
    isolated_db.add_tracks_to_playlist(pb["id"], ["lofi-fav-1"])

    out = get_playlist_tracks(pb["id"], {"user_id": user_a})
    assert out == "Not authorized."


def test_get_playlist_tracks_missing_playlist(isolated_db, stub_catalog):
    from agent.tools import get_playlist_tracks

    user_id = isolated_db.create_user("dave", "d@test.io", "h")
    out = get_playlist_tracks(99999, {"user_id": user_id})
    assert out == "Playlist not found."


def test_get_playlist_tracks_without_user_id(isolated_db):
    from agent.tools import get_playlist_tracks

    assert get_playlist_tracks(1, {}) == "User context not available."


# ---------------------------------------------------------------------------
# get_user_ratings
# ---------------------------------------------------------------------------

def test_get_user_ratings_min_rating_filter(isolated_db):
    from agent.tools import get_user_ratings

    user_id = isolated_db.create_user("erin", "e@test.io", "h")
    isolated_db.upsert_track_rating(user_id, "t1", 5)
    isolated_db.upsert_track_rating(user_id, "t2", 3)
    isolated_db.upsert_track_rating(user_id, "t3", 1)

    # Default: all ratings
    out_all = get_user_ratings({"user_id": user_id})
    parsed_all = json.loads(out_all)
    assert parsed_all == {"t1": 5, "t2": 3, "t3": 1}

    # Filter by min_rating=4 → only t1
    out_fav = get_user_ratings({"user_id": user_id}, min_rating=4)
    parsed_fav = json.loads(out_fav)
    assert parsed_fav == {"t1": 5}

    # Filter by min_rating=6 → empty
    out_empty = get_user_ratings({"user_id": user_id}, min_rating=6)
    assert out_empty == "No ratings."


def test_get_user_ratings_without_user_id(isolated_db):
    from agent.tools import get_user_ratings

    assert get_user_ratings({}) == "User context not available."


def test_get_user_ratings_no_ratings_for_user(isolated_db):
    from agent.tools import get_user_ratings

    user_id = isolated_db.create_user("frank", "f@test.io", "h")
    assert get_user_ratings({"user_id": user_id}) == "No ratings."


# ---------------------------------------------------------------------------
# get_favorite_tracks
# ---------------------------------------------------------------------------

def test_get_favorite_tracks_with_genre_filter(isolated_db, stub_catalog):
    from agent.tools import get_favorite_tracks

    user_id = isolated_db.create_user("gina", "g@test.io", "h")
    isolated_db.upsert_track_rating(user_id, "lofi-fav-1", 5)
    isolated_db.upsert_track_rating(user_id, "lofi-fav-2", 4)
    isolated_db.upsert_track_rating(user_id, "techno-fav-1", 5)
    isolated_db.upsert_track_rating(user_id, "lofi-mid", 3)  # not a favorite

    # No genre filter — should include both lofi and techno favorites.
    out_all = get_favorite_tracks({"user_id": user_id})
    assert "lofi-fav-1" in out_all
    assert "lofi-fav-2" in out_all
    assert "techno-fav-1" in out_all
    assert "lofi-mid" not in out_all

    # Genre = lofi → techno favorite filtered out.
    out_lofi = get_favorite_tracks({"user_id": user_id}, genre="lofi")
    assert "lofi-fav-1" in out_lofi
    assert "lofi-fav-2" in out_lofi
    assert "techno-fav-1" not in out_lofi


def test_get_favorite_tracks_no_favorites_returns_message(isolated_db, stub_catalog):
    from agent.tools import get_favorite_tracks

    user_id = isolated_db.create_user("hank", "h@test.io", "h")
    # Only a 3-star rating — no favorites
    isolated_db.upsert_track_rating(user_id, "lofi-mid", 3)

    out = get_favorite_tracks({"user_id": user_id})
    assert out == "No favorites."


def test_get_favorite_tracks_no_match_for_genre(isolated_db, stub_catalog):
    """User has favorites, but none in the requested genre."""
    from agent.tools import get_favorite_tracks

    user_id = isolated_db.create_user("ivy", "i@test.io", "h")
    isolated_db.upsert_track_rating(user_id, "lofi-fav-1", 5)

    out = get_favorite_tracks({"user_id": user_id}, genre="techno")
    assert out == "No favorites within genre 'techno'."


def test_get_favorite_tracks_without_user_id(isolated_db):
    from agent.tools import get_favorite_tracks

    assert get_favorite_tracks({}) == "User context not available."
