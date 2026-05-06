"""Tests for v2.3.0 — user context loader and prompt formatter.

Covers `pipeline.load_user_context()` (DB → dict shape, empty fallback,
60s TTL cache) and `pipeline._format_user_summary()` (caps + empty string).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# load_user_context — shape, empty fallback, caching
# ---------------------------------------------------------------------------

def test_load_user_context_returns_playlists_and_ratings(tmp_db, monkeypatch):
    from web.backend import db, pipeline

    # Reset cache between tests so prior fixtures don't bleed in.
    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("ctxuser", "ctxuser@test.io", "hash")

    # Two playlists, with one tracking 2 tracks
    p1 = db.create_playlist(user_id, "Late Night")
    db.add_tracks_to_playlist(p1["id"], ["t-fav-1", "t-fav-2"])
    db.create_playlist(user_id, "Empty Bucket")

    # Mixed ratings: 2 favorites (>=4), 1 dislike (<=2), 1 neutral (=3)
    db.upsert_track_rating(user_id, "t-fav-1", 5)
    db.upsert_track_rating(user_id, "t-fav-2", 4)
    db.upsert_track_rating(user_id, "t-mid", 3)
    db.upsert_track_rating(user_id, "t-bad", 1)

    out = pipeline.load_user_context(user_id)

    # Shape
    assert set(out.keys()) == {"playlists", "ratings", "favorite_ids", "dislike_ids"}

    # Playlists with track_count
    names = sorted(p["name"] for p in out["playlists"])
    assert names == ["Empty Bucket", "Late Night"]
    by_name = {p["name"]: p for p in out["playlists"]}
    assert by_name["Late Night"]["track_count"] == 2
    assert by_name["Empty Bucket"]["track_count"] == 0

    # Ratings & derived sets
    assert out["ratings"] == {"t-fav-1": 5, "t-fav-2": 4, "t-mid": 3, "t-bad": 1}
    assert out["favorite_ids"] == {"t-fav-1", "t-fav-2"}
    assert out["dislike_ids"] == {"t-bad"}


def test_load_user_context_unknown_user_returns_empty(tmp_db, monkeypatch):
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    out = pipeline.load_user_context(99999)  # never created

    assert out["playlists"] == []
    assert out["ratings"] == {}
    assert out["favorite_ids"] == set()
    assert out["dislike_ids"] == set()


def test_load_user_context_caches_within_60s(tmp_db, monkeypatch):
    """Inside the same minute bucket, a second call must not hit the DB."""
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("cacher", "cacher@test.io", "hash")
    db.upsert_track_rating(user_id, "tA", 5)

    # Pin time to a stable bucket
    fixed = 1_000_000.0
    monkeypatch.setattr(pipeline.time, "time", lambda: fixed)

    out1 = pipeline.load_user_context(user_id)
    assert out1["favorite_ids"] == {"tA"}

    # Mutate DB underneath: cache must shadow the change while bucket holds.
    db.upsert_track_rating(user_id, "tB", 5)

    out2 = pipeline.load_user_context(user_id)
    assert out2["favorite_ids"] == {"tA"}, "cache should hide the new rating"

    # Roll the clock past the 60s boundary — cache must rebuild now.
    monkeypatch.setattr(pipeline.time, "time", lambda: fixed + 61)

    out3 = pipeline.load_user_context(user_id)
    assert out3["favorite_ids"] == {"tA", "tB"}


# ---------------------------------------------------------------------------
# _format_user_summary — caps, empty fallback, genre filter
# ---------------------------------------------------------------------------

def test_format_user_summary_caps_favorites_at_10_and_dislikes_at_5():
    from web.backend import pipeline

    favorite_ids = {f"fav{i:02d}" for i in range(15)}
    dislike_ids = {f"bad{i:02d}" for i in range(8)}
    user_ctx = {
        "favorite_ids": favorite_ids,
        "dislike_ids": dislike_ids,
        "ratings": {},
        "playlists": [],
    }

    text = pipeline._format_user_summary(user_ctx, genre=None)

    assert "USER PREFERENCES" in text

    # Find the favorites and dislikes lines and count comma-separated ids.
    lines = text.splitlines()
    fav_line = next(l for l in lines if l.startswith("- Favorites"))
    dis_line = next(l for l in lines if l.startswith("- Dislikes"))

    # Extract the id list after the last colon. The format is
    # "- Favorites (...): N tracks. Top K: id1, id2, ..."
    fav_ids = [s.strip() for s in fav_line.rsplit(": ", 1)[-1].split(",")]
    dis_ids = [s.strip() for s in dis_line.rsplit(": ", 1)[-1].split(",")]

    assert len(fav_ids) == 10
    assert len(dis_ids) == 5
    # Total favorites count (15) is reported, even though only 10 are listed.
    assert "15 tracks" in fav_line
    assert "8 tracks" in dis_line


def test_format_user_summary_returns_empty_string_when_no_data():
    from web.backend import pipeline

    user_ctx = {
        "favorite_ids": set(),
        "dislike_ids": set(),
        "ratings": {},
        "playlists": [],
    }

    assert pipeline._format_user_summary(user_ctx, genre=None) == ""
    assert pipeline._format_user_summary(user_ctx, genre="techno") == ""


def test_format_user_summary_includes_playlists_when_no_ratings():
    """A user with playlists but no ratings still gets a non-empty block."""
    from web.backend import pipeline

    user_ctx = {
        "favorite_ids": set(),
        "dislike_ids": set(),
        "ratings": {},
        "playlists": [
            {"id": 1, "name": "Late Night", "track_count": 12},
            {"id": 2, "name": "Peak Energy", "track_count": 8},
        ],
    }
    text = pipeline._format_user_summary(user_ctx, genre=None)
    assert "USER PREFERENCES" in text
    assert "Late Night" in text
    assert "12 tracks" in text


def test_format_user_summary_genre_filter_surfaces_in_genre_ids_first(
    tmp_db, monkeypatch
):
    """When `genre` is given, ids that exist in the catalog of that genre
    appear before unrelated ids in the truncated output."""
    from web.backend import pipeline

    # Build a fake catalog with two ids in the requested genre.
    in_genre_track = {
        "id": "in-genre-1",
        "display_name": "In Genre 1",
        "genre_folder": "techno",
        "genre": "techno",
        "bpm": 128,
        "camelot_key": "8A",
    }

    monkeypatch.setattr(
        pipeline,
        "load_catalog",
        lambda genre=None: ([in_genre_track], ["techno"]),
    )

    favorite_ids = {f"unrelated-{i:02d}" for i in range(12)} | {"in-genre-1"}
    user_ctx = {
        "favorite_ids": favorite_ids,
        "dislike_ids": set(),
        "ratings": {},
        "playlists": [],
    }

    text = pipeline._format_user_summary(user_ctx, genre="techno")
    fav_line = next(l for l in text.splitlines() if l.startswith("- Favorites"))
    fav_ids = [s.strip() for s in fav_line.rsplit(": ", 1)[-1].split(",")]

    # The in-genre id must be among the first listed ids and counted.
    assert "in-genre-1" in fav_ids
    # The line annotates the in-genre count.
    assert "within 'techno': 1" in fav_line
