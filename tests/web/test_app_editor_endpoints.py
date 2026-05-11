"""Integration tests for the deterministic Editor endpoints
(``reorder`` / ``insert`` / ``DELETE tracks/{n}``) plus the
``_editor_phase_guard`` helper they share.

The freeform ``editor_command`` SSE endpoint has its own file
(``test_app_editor_sse.py``) because it exercises StreamingResponse
plumbing that needs ``client.stream``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.backend.session_store import store


def _seed_session(auth_client: TestClient, tracks: list[dict] | None = None) -> str:
    """Create a session and inject a 3-track playlist (editing phase)."""
    sid = auth_client.post("/api/sessions").json()["id"]
    s = store.get(sid)
    assert s is not None
    s.context_variables["playlist"] = tracks or [
        {"id": "t1", "display_name": "T1", "bpm": 120, "camelot_key": "8A"},
        {"id": "t2", "display_name": "T2", "bpm": 124, "camelot_key": "9A"},
        {"id": "t3", "display_name": "T3", "bpm": 128, "camelot_key": "10A"},
    ]
    s.context_variables["genre"] = "techno"
    s.phase = "editing"
    s.messages.setdefault("editor", [])
    return sid


# ─── /tracks/reorder ─────────────────────────────────────────────────


def test_reorder_applies_new_order(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [2, 0, 1]},
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["playlist"]]
    assert ids == ["t3", "t1", "t2"]


def test_reorder_rejects_duplicate_indices(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0, 0, 1]},
    )
    assert r.status_code == 422


def test_reorder_rejects_missing_indices(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0, 1]},  # length mismatch
    )
    assert r.status_code == 422


def test_reorder_rejects_out_of_range_indices(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0, 1, 99]},
    )
    assert r.status_code == 422


def test_reorder_auto_promotes_phase_from_critique(auth_client):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "critique"

    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [2, 1, 0]},
    )
    assert r.status_code == 200
    assert r.json()["phase"] == "editing"


def test_reorder_rejected_during_live_session(auth_client):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "performing"
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0, 1, 2]},
    )
    assert r.status_code == 409


# ─── DELETE /tracks/{n} ──────────────────────────────────────────────


def test_delete_removes_track_at_index(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.delete(f"/api/sessions/{sid}/tracks/1")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["playlist"]]
    assert ids == ["t1", "t3"]


def test_delete_out_of_range_returns_404(auth_client):
    sid = _seed_session(auth_client)
    r = auth_client.delete(f"/api/sessions/{sid}/tracks/99")
    assert r.status_code == 404


def test_delete_negative_index_returns_404(auth_client):
    sid = _seed_session(auth_client)
    # FastAPI's int path-converter accepts negative ints; we still 404.
    r = auth_client.delete(f"/api/sessions/{sid}/tracks/-1")
    assert r.status_code == 404


def test_delete_auto_promotes_phase_from_checkpoint2(auth_client):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "checkpoint2"
    r = auth_client.delete(f"/api/sessions/{sid}/tracks/0")
    assert r.status_code == 200
    assert r.json()["phase"] == "editing"


def test_delete_rejected_during_live_session(auth_client):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "performing"
    r = auth_client.delete(f"/api/sessions/{sid}/tracks/0")
    assert r.status_code == 409


# ─── /tracks/insert ──────────────────────────────────────────────────


@pytest.fixture
def patched_catalog(monkeypatch):
    """The endpoint validates ``track_id`` via ``pipeline.get_track_by_id``.
    The base ``mock_pipeline`` fixture doesn't patch that lookup (it only
    swaps the phases), so we stub it directly here. Returns the fake
    track id used by these tests."""
    fake_track = {
        "id": "fake-insert-track",
        "display_name": "Fake Insert",
        "bpm": 122,
        "camelot_key": "8A",
        "genre": "techno",
    }
    from web.backend import pipeline
    monkeypatch.setattr(
        pipeline, "get_track_by_id",
        lambda tid: fake_track if tid == fake_track["id"] else None,
    )
    return fake_track["id"]


def test_insert_known_track(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": 1, "track_id": patched_catalog},
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["playlist"]]
    assert ids == ["t1", patched_catalog, "t2", "t3"]


def test_insert_unknown_track_returns_422(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": 0, "track_id": "does-not-exist"},
    )
    assert r.status_code == 422


def test_insert_clamps_position_to_end(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": 999, "track_id": patched_catalog},
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["playlist"]]
    assert ids[-1] == patched_catalog


def test_insert_at_zero_prepends(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": 0, "track_id": patched_catalog},
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["playlist"]]
    assert ids[0] == patched_catalog


def test_insert_rejects_negative_position(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": -3, "track_id": patched_catalog},
    )
    # Pydantic ge=0 → 422.
    assert r.status_code == 422


def test_insert_rejected_during_live_session(auth_client, patched_catalog):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "performing"
    r = auth_client.post(
        f"/api/sessions/{sid}/tracks/insert",
        json={"at": 0, "track_id": patched_catalog},
    )
    assert r.status_code == 409


# ─── Cross-cutting auth + ownership ──────────────────────────────────


def test_reorder_other_users_session_returns_404(auth_client, second_client):
    sid = _seed_session(auth_client)
    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"},
    ).json()["access_token"]
    r = second_client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0, 1, 2]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_reorder_unauthenticated_returns_401(client):
    sid = "anything"
    r = client.post(
        f"/api/sessions/{sid}/tracks/reorder",
        json={"order": [0]},
    )
    assert r.status_code == 401
