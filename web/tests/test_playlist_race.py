"""Concurrent-append regression for issue #16.

Without `BEGIN IMMEDIATE` around the read-modify-write inside
`db.add_tracks_to_playlist`, two simultaneous calls both observe
`MAX(position)+1 = N`, both INSERT at `(playlist_id, N)`, and the second
one fails with
`sqlite3.IntegrityError: UNIQUE constraint failed: playlist_tracks.playlist_id, playlist_tracks.position`.

The fix wraps the read-modify-write in `BEGIN IMMEDIATE`, which acquires
a RESERVED lock at BEGIN time and serialises writers without blocking
readers.

Two layers of test:

1. `test_db_concurrent_append_no_integrity_error` — drives `db.add_tracks_to_playlist`
   from real OS threads. This is the most direct repro: at HEAD (with the
   fix) all 20 calls land cleanly; with the fix reverted, a `sqlite3.IntegrityError`
   surfaces on at least one thread.
2. `test_concurrent_append_no_500` — same idea but through the FastAPI
   endpoint via `httpx.AsyncClient` + `ASGITransport`, asserting no 500s
   leak to the client.
"""
from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import pytest


def test_db_concurrent_append_no_integrity_error(stream_env, auth_client):
    """Direct DB-level repro: 20 threads each append one track. With the
    BEGIN IMMEDIATE wrap they all succeed and positions are dense 0..19.
    Without it, at least one raises sqlite3.IntegrityError."""
    from web.backend import db

    # Use the auth_client fixture only to ensure a user exists & DB is set up;
    # we then create a playlist via the DB layer.
    user = db.get_user_by_username("u1")
    assert user is not None
    playlist = db.create_playlist(user["id"], "race-direct")
    pid = playlist["id"]

    errors: list[BaseException] = []

    def append(i: int):
        try:
            db.add_tracks_to_playlist(pid, [f"track-{i}"])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(append, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"got errors: {errors!r}"

    raw = db.get_playlist(pid)
    assert raw is not None
    assert len(raw["track_ids"]) == 20
    assert sorted(raw["track_ids"]) == sorted(f"track-{i}" for i in range(20))

    # Positions must still be dense 0..19 — the invariant remove/reorder rely on.
    with sqlite3.connect(str(db.DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT position FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (pid,),
        ).fetchall()
    assert [r["position"] for r in rows] == list(range(20))


@pytest.mark.asyncio
async def test_concurrent_append_no_500(stream_env, auth_token):
    """End-to-end variant via the ASGI app. Asserts no 500 leaks out to the
    client. FastAPI may serialise async-handler bodies on a single event loop,
    but the underlying DB write path must still be safe — this test catches
    any regression where a raw IntegrityError leaks through the handler."""
    from web.backend import db
    from web.backend.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {auth_token}"},
    ) as ac:
        r = await ac.post("/api/playlists", json={"name": "race"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]

        tasks = [
            ac.post(f"/api/playlists/{pid}/tracks", json={"track_ids": [f"track-{i}"]})
            for i in range(20)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    failures = [r for r in results if r.status_code != 200]
    assert not failures, [r.status_code for r in failures] + [r.text for r in failures]

    raw = db.get_playlist(pid)
    assert raw is not None
    assert len(raw["track_ids"]) == 20
