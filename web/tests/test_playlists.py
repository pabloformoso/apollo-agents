"""Tests for /api/playlists — CRUD + reorder + ownership + hydration.

Reuses the `stream_env` / `auth_client` fixtures from conftest.py: they boot
a TestClient against a clean tmp DB with a fake catalog already wired in.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client: TestClient, username: str, password: str = "pw12345") -> str:
    r = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@test.io", "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _create(client: TestClient, name: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.post("/api/playlists", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Full CRUD
# ---------------------------------------------------------------------------

def test_full_crud_lifecycle(stream_env, auth_client):
    p = _create(auth_client, "My Mix")
    assert p["name"] == "My Mix"
    assert p["track_count"] == 0
    assert p["created_at"]
    assert p["updated_at"] == p["created_at"]

    listing = auth_client.get("/api/playlists").json()
    assert any(item["id"] == p["id"] for item in listing)

    detail = auth_client.get(f"/api/playlists/{p['id']}").json()
    assert detail["name"] == "My Mix"
    assert detail["tracks"] == []

    # PATCH rename — updated_at must move forward.
    time.sleep(1.1)  # iso seconds resolution
    r = auth_client.patch(f"/api/playlists/{p['id']}", json={"name": "Renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["updated_at"] > p["updated_at"]

    # DELETE → 204, then 404 on subsequent GET.
    r = auth_client.delete(f"/api/playlists/{p['id']}")
    assert r.status_code == 204
    r = auth_client.get(f"/api/playlists/{p['id']}")
    assert r.status_code == 404


def test_create_validates_name_length(stream_env, auth_client):
    r = auth_client.post("/api/playlists", json={"name": ""})
    assert r.status_code == 422
    r = auth_client.post("/api/playlists", json={"name": "x" * 101})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Add tracks (duplicates allowed)
# ---------------------------------------------------------------------------

def test_add_tracks_appends_and_allows_duplicates(stream_env, auth_client):
    p = _create(auth_client, "Dupes")
    wav_id = stream_env["wav_track"]["id"]
    mp3_id = stream_env["mp3_track"]["id"]

    r = auth_client.post(f"/api/playlists/{p['id']}/tracks", json={"track_ids": [wav_id, mp3_id]})
    assert r.status_code == 200
    assert r.json()["track_count"] == 2

    # Append the same wav id again — duplicate is intentional.
    r = auth_client.post(f"/api/playlists/{p['id']}/tracks", json={"track_ids": [wav_id]})
    assert r.status_code == 200
    assert r.json()["track_count"] == 3

    detail = auth_client.get(f"/api/playlists/{p['id']}").json()
    ids = [t["id"] for t in detail["tracks"]]
    assert ids == [wav_id, mp3_id, wav_id]


def test_add_tracks_rejects_empty_list(stream_env, auth_client):
    p = _create(auth_client, "X")
    r = auth_client.post(f"/api/playlists/{p['id']}/tracks", json={"track_ids": []})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Remove track compacts positions
# ---------------------------------------------------------------------------

def test_remove_track_compacts_positions(stream_env, auth_client):
    from web.backend import db

    p = _create(auth_client, "Compact")
    wav_id = stream_env["wav_track"]["id"]
    mp3_id = stream_env["mp3_track"]["id"]
    auth_client.post(
        f"/api/playlists/{p['id']}/tracks",
        json={"track_ids": [wav_id, mp3_id, wav_id]},
    )

    r = auth_client.delete(f"/api/playlists/{p['id']}/tracks/{mp3_id}")
    assert r.status_code == 204

    # Inspect the DB directly to verify positions are 0..N-1 dense.
    raw = db.get_playlist(p["id"])
    assert raw is not None
    assert raw["track_ids"] == [wav_id, wav_id]


def test_remove_only_first_occurrence(stream_env, auth_client):
    from web.backend import db

    p = _create(auth_client, "FirstOnly")
    wav_id = stream_env["wav_track"]["id"]
    mp3_id = stream_env["mp3_track"]["id"]
    auth_client.post(
        f"/api/playlists/{p['id']}/tracks",
        json={"track_ids": [wav_id, mp3_id, wav_id]},
    )
    auth_client.delete(f"/api/playlists/{p['id']}/tracks/{wav_id}")
    raw = db.get_playlist(p["id"])
    assert raw is not None
    assert raw["track_ids"] == [mp3_id, wav_id]


def test_remove_unknown_track_404(stream_env, auth_client):
    p = _create(auth_client, "Empty")
    r = auth_client.delete(f"/api/playlists/{p['id']}/tracks/never-added")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------

def test_reorder_rotates_correctly(stream_env, auth_client):
    p = _create(auth_client, "Order")
    wav_id = stream_env["wav_track"]["id"]
    mp3_id = stream_env["mp3_track"]["id"]
    auth_client.post(
        f"/api/playlists/{p['id']}/tracks", json={"track_ids": [wav_id, mp3_id]}
    )

    r = auth_client.put(
        f"/api/playlists/{p['id']}/order",
        json={"track_ids": [mp3_id, wav_id]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["track_ids"] == [mp3_id, wav_id]

    detail = auth_client.get(f"/api/playlists/{p['id']}").json()
    assert [t["id"] for t in detail["tracks"]] == [mp3_id, wav_id]


def test_reorder_rejects_mismatched_set(stream_env, auth_client):
    p = _create(auth_client, "Bad")
    wav_id = stream_env["wav_track"]["id"]
    mp3_id = stream_env["mp3_track"]["id"]
    auth_client.post(
        f"/api/playlists/{p['id']}/tracks", json={"track_ids": [wav_id, mp3_id]}
    )

    # Drops one id.
    r = auth_client.put(
        f"/api/playlists/{p['id']}/order",
        json={"track_ids": [wav_id]},
    )
    assert r.status_code == 422

    # Introduces an unknown id.
    r = auth_client.put(
        f"/api/playlists/{p['id']}/order",
        json={"track_ids": [wav_id, mp3_id, "ghost-id"]},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Ownership — user A cannot see/touch user B's playlist
# ---------------------------------------------------------------------------

def test_ownership_isolation(stream_env, auth_client):
    """auth_client is user `u1`; register a second user and make sure they
    can't see u1's playlist."""
    p = _create(auth_client, "Mine")

    from web.backend.app import app
    other = TestClient(app)
    token2 = _register(other, "u2")
    other.headers.update({"Authorization": f"Bearer {token2}"})

    r = other.get(f"/api/playlists/{p['id']}")
    assert r.status_code == 404
    r = other.patch(f"/api/playlists/{p['id']}", json={"name": "stolen"})
    assert r.status_code == 404
    r = other.delete(f"/api/playlists/{p['id']}")
    assert r.status_code == 404
    r = other.post(f"/api/playlists/{p['id']}/tracks", json={"track_ids": [stream_env["wav_track"]["id"]]})
    assert r.status_code == 404
    r = other.put(f"/api/playlists/{p['id']}/order", json={"track_ids": []})
    assert r.status_code == 404

    # u2's listing is empty even though u1 has a playlist.
    assert other.get("/api/playlists").json() == []


# ---------------------------------------------------------------------------
# Hydration — full Track shape, plus `missing: true` for stale ids
# ---------------------------------------------------------------------------

def test_hydration_returns_full_track(stream_env, auth_client):
    p = _create(auth_client, "Hyd")
    wav_id = stream_env["wav_track"]["id"]
    auth_client.post(f"/api/playlists/{p['id']}/tracks", json={"track_ids": [wav_id]})

    detail = auth_client.get(f"/api/playlists/{p['id']}").json()
    assert len(detail["tracks"]) == 1
    t = detail["tracks"][0]
    assert t["id"] == wav_id
    assert t["display_name"] == stream_env["wav_track"]["display_name"]
    assert t["bpm"] == stream_env["wav_track"]["bpm"]
    assert t.get("missing") is not True


def test_hydration_marks_missing_tracks(stream_env, auth_client, monkeypatch):
    """A track id whose row exists in playlist_tracks but is no longer in the
    catalog should come back with `missing: true` rather than failing the
    request."""
    from web.backend import db

    p = _create(auth_client, "WithGhost")

    # Insert a fabricated id directly so we don't have to make the catalog
    # accept it first.
    db.add_tracks_to_playlist(p["id"], ["ghost-track-id"])

    detail = auth_client.get(f"/api/playlists/{p['id']}").json()
    ghost = next(t for t in detail["tracks"] if t["id"] == "ghost-track-id")
    assert ghost.get("missing") is True
    assert ghost.get("display_name") == "ghost-track-id"


# ---------------------------------------------------------------------------
# Auth required everywhere
# ---------------------------------------------------------------------------

def test_endpoints_require_auth(stream_env):
    from web.backend.app import app
    anon = TestClient(app)
    bodyless = {("get", "/api/playlists"), ("get", "/api/playlists/1"),
                ("delete", "/api/playlists/1"),
                ("delete", "/api/playlists/1/tracks/x")}
    for method, path in [
        ("get", "/api/playlists"),
        ("post", "/api/playlists"),
        ("get", "/api/playlists/1"),
        ("patch", "/api/playlists/1"),
        ("delete", "/api/playlists/1"),
        ("post", "/api/playlists/1/tracks"),
        ("delete", "/api/playlists/1/tracks/x"),
        ("put", "/api/playlists/1/order"),
    ]:
        if (method, path) in bodyless:
            r = getattr(anon, method)(path)
        else:
            r = getattr(anon, method)(path, json={"name": "x", "track_ids": ["x"]})
        assert r.status_code in (401, 403), f"{method} {path} → {r.status_code}"
