"""Integration tests for the v2.6.0 Curate apply/ignore endpoints.

The bounded editor turn inside ``apply`` is exercised through the
``mock_pipeline`` ``fake_editor`` stub so the suite stays deterministic
and the LLM never runs.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.backend.notes import note_id
from web.backend.session_store import store


def _seed_session_with_critic_notes(
    auth_client: TestClient, problems: list[dict] | None = None,
) -> tuple[str, list[str]]:
    """Create a session and inject critic problems server-side.

    Returns ``(session_id, [note_ids])``. The legacy ``GET .../`` route
    won't have populated ``structured_problems`` (planner mock leaves
    that to phase_critique which we don't run here), so we poke them in
    directly via the in-memory store.
    """
    sid = auth_client.post("/api/sessions").json()["id"]
    s = store.get(sid)
    assert s is not None
    s.structured_problems = problems or [
        {
            "pos_from": 1, "pos_to": 2, "key_pair": "Am→Em",
            "bpm_diff": 8, "text": "BPM jump. Try a bridge.",
        },
        {
            "pos_from": 3, "pos_to": 3, "key_pair": "",
            "bpm_diff": 2, "text": "Energy plateau at position 3.",
        },
    ]
    s.context_variables["playlist"] = [
        {"id": "t1", "display_name": "T1", "bpm": 120, "camelot_key": "8A"},
        {"id": "t2", "display_name": "T2", "bpm": 128, "camelot_key": "9A"},
        {"id": "t3", "display_name": "T3", "bpm": 130, "camelot_key": "10A"},
    ]
    s.phase = "critique"
    return sid, [note_id(p) for p in s.structured_problems]


# ─── /apply ──────────────────────────────────────────────────────────


def test_apply_runs_editor_turn_and_marks_handled(auth_client, mock_pipeline):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)

    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/apply")
    assert r.status_code == 200
    data = r.json()
    # Note status flips to "applied" via the handled_notes dict.
    assert nid in data["handled"]
    applied = [n for n in data["notes"] if n["id"] == nid][0]
    assert applied["status"] == "applied"
    # Phase auto-promoted critique → editing.
    assert data["phase"] == "editing"


def test_apply_unknown_note_returns_404(auth_client):
    sid, _ = _seed_session_with_critic_notes(auth_client)
    r = auth_client.post(f"/api/sessions/{sid}/notes/deadbeef/apply")
    assert r.status_code == 404


def test_apply_returns_422_when_editor_phase_raises(
    auth_client, monkeypatch, mock_pipeline,
):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)

    async def _boom(message, history, ctx, emit):
        raise RuntimeError("simulated editor crash")

    from web.backend import pipeline
    monkeypatch.setattr(pipeline, "phase_editor", _boom)

    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/apply")
    assert r.status_code == 422
    # And handled_notes was NOT updated because the turn failed.
    s = store.get(sid)
    assert s is not None
    assert nid not in s.handled_notes


def test_apply_rejects_during_live_session(auth_client, mock_pipeline):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "performing"
    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/apply")
    assert r.status_code == 409


def test_apply_is_idempotent_when_already_applied(auth_client, mock_pipeline):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    s = store.get(sid)
    assert s is not None
    s.handled_notes[nid] = "applied"

    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/apply")
    assert r.status_code == 200
    # Still marked as applied — no duplicate side effects.
    assert s.handled_notes[nid] == "applied"


def test_apply_other_users_session_returns_404(
    auth_client, second_client, mock_pipeline,
):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"},
    ).json()["access_token"]
    r = second_client.post(
        f"/api/sessions/{sid}/notes/{nid}/apply",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ─── /ignore ─────────────────────────────────────────────────────────


def test_ignore_marks_note_handled(auth_client):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/ignore")
    assert r.status_code == 200
    assert r.json()["handled"] == [nid]

    # Subsequent GET reflects status=ignored on that note.
    fresh = auth_client.get(f"/api/sessions/{sid}").json()
    targeted = [n for n in fresh["notes"] if n["id"] == nid][0]
    assert targeted["status"] == "ignored"


def test_ignore_is_idempotent(auth_client):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    r1 = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/ignore").json()
    r2 = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/ignore").json()
    assert r1["handled"] == r2["handled"] == [nid]


def test_ignore_does_not_call_editor(auth_client, monkeypatch):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)

    called = {"n": 0}

    async def _boom(message, history, ctx, emit):
        called["n"] += 1
        raise AssertionError("editor must not run on ignore")

    from web.backend import pipeline
    monkeypatch.setattr(pipeline, "phase_editor", _boom)
    r = auth_client.post(f"/api/sessions/{sid}/notes/{nid}/ignore")
    assert r.status_code == 200
    assert called["n"] == 0


def test_ignore_other_users_session_returns_404(
    auth_client, second_client,
):
    sid, [nid, _] = _seed_session_with_critic_notes(auth_client)
    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"},
    ).json()["access_token"]
    r = second_client.post(
        f"/api/sessions/{sid}/notes/{nid}/ignore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
