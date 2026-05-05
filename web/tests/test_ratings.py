"""Tests for v2.2.2 — per-user track ratings.

Covers PUT/DELETE /api/tracks/{id}/rating and the `user_rating` hydration
on /api/catalog. Reuses the `stream_env` fixture from conftest because it
already wires up an in-memory test DB and a fake catalog with stable IDs.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _register_login(client: TestClient, username: str, password: str = "pw12345") -> str:
    """Register a fresh user and return their bearer token."""
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@test.io", "password": password},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# PUT — create + upsert
# ---------------------------------------------------------------------------

def test_put_rating_creates_new_row(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.put(
        f"/api/tracks/{track_id}/rating",
        json={"rating": 4},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["track_id"] == track_id
    assert body["rating"] == 4


def test_put_rating_upserts_single_row(stream_env, auth_client, auth_token):
    """A second PUT updates the existing row instead of creating a duplicate."""
    from web.backend import db

    track_id = stream_env["wav_track"]["id"]
    auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 3})
    r = auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 5})
    assert r.status_code == 200
    assert r.json()["rating"] == 5

    # Direct DB peek — exactly one row should exist.
    with db._conn() as c:
        rows = c.execute(
            "SELECT rating FROM track_ratings WHERE track_id = ?",
            (track_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["rating"] == 5


def test_put_rating_below_one_is_422(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 0})
    assert r.status_code == 422


def test_put_rating_above_five_is_422(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    r = auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 6})
    assert r.status_code == 422


def test_put_rating_requires_auth(stream_env):
    """No bearer token → 401."""
    from web.backend.app import app

    client = TestClient(app)
    r = client.put(
        f"/api/tracks/{stream_env['wav_track']['id']}/rating",
        json={"rating": 4},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# DELETE — idempotent
# ---------------------------------------------------------------------------

def test_delete_rating_removes_row(stream_env, auth_client, auth_token):
    track_id = stream_env["wav_track"]["id"]
    auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 4})
    r = auth_client.delete(f"/api/tracks/{track_id}/rating")
    assert r.status_code == 204

    # Confirm via /api/catalog: user_rating now null.
    cat = auth_client.get("/api/catalog").json()
    track = next(t for t in cat["tracks"] if t["id"] == track_id)
    assert track["user_rating"] is None


def test_delete_rating_idempotent(stream_env, auth_client, auth_token):
    """DELETE on a non-existent rating still returns 204."""
    track_id = stream_env["wav_track"]["id"]
    # No PUT first — straight to DELETE.
    r1 = auth_client.delete(f"/api/tracks/{track_id}/rating")
    assert r1.status_code == 204
    # Second DELETE on the same id still works.
    r2 = auth_client.delete(f"/api/tracks/{track_id}/rating")
    assert r2.status_code == 204


# ---------------------------------------------------------------------------
# /api/catalog hydration
# ---------------------------------------------------------------------------

def test_catalog_returns_user_rating_for_owner(stream_env, auth_client, auth_token):
    """After PUT, /api/catalog returns the rating the caller set."""
    track_id = stream_env["wav_track"]["id"]
    auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 4})

    cat = auth_client.get("/api/catalog").json()
    track = next(t for t in cat["tracks"] if t["id"] == track_id)
    assert track["user_rating"] == 4


def test_catalog_returns_null_rating_for_unrated(stream_env, auth_client, auth_token):
    """Tracks without any rating expose user_rating = null, not missing."""
    track_id = stream_env["mp3_track"]["id"]
    cat = auth_client.get("/api/catalog").json()
    track = next(t for t in cat["tracks"] if t["id"] == track_id)
    assert "user_rating" in track
    assert track["user_rating"] is None


def test_catalog_does_not_leak_other_users_ratings(stream_env, auth_client, auth_token):
    """User A rates a track 5★; user B's catalog must still show null for it.

    This is the hard isolation guarantee — the v2.3 agent integration will
    rely on each user's ratings being strictly private.
    """
    from web.backend.app import app
    from web.backend.session_store import store

    track_id = stream_env["wav_track"]["id"]

    # User A (the auth_client fixture) rates the track 5★.
    r = auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 5})
    assert r.status_code == 200

    # Spin up user B on a fresh client + token.
    store._reset()  # don't disturb user-A's session-store rows
    client_b = TestClient(app)
    token_b = _register_login(client_b, "u2")
    client_b.headers.update({"Authorization": f"Bearer {token_b}"})

    cat_b = client_b.get("/api/catalog").json()
    track_b = next(t for t in cat_b["tracks"] if t["id"] == track_id)
    assert track_b["user_rating"] is None, (
        f"User B saw user A's rating: {track_b}"
    )

    # And user A still sees their own.
    cat_a = auth_client.get("/api/catalog").json()
    track_a = next(t for t in cat_a["tracks"] if t["id"] == track_id)
    assert track_a["user_rating"] == 5


def test_catalog_user_rating_changes_after_update_and_delete(
    stream_env, auth_client, auth_token
):
    """Ratings reflect the latest PUT and disappear after DELETE."""
    track_id = stream_env["wav_track"]["id"]

    auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 2})
    cat = auth_client.get("/api/catalog").json()
    assert next(t for t in cat["tracks"] if t["id"] == track_id)["user_rating"] == 2

    auth_client.put(f"/api/tracks/{track_id}/rating", json={"rating": 4})
    cat = auth_client.get("/api/catalog").json()
    assert next(t for t in cat["tracks"] if t["id"] == track_id)["user_rating"] == 4

    auth_client.delete(f"/api/tracks/{track_id}/rating")
    cat = auth_client.get("/api/catalog").json()
    assert next(t for t in cat["tracks"] if t["id"] == track_id)["user_rating"] is None
