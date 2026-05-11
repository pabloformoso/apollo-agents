"""Integration tests for ``POST /api/sessions/{id}/editor_command`` —
the SSE wrapper around ``pipeline.phase_editor``.

The TestClient's ``stream()`` helper opens the response without
buffering, so we can iterate the raw SSE frames line-by-line.
"""
from __future__ import annotations

from typing import Iterable

import pytest

from web.backend import pipeline
from web.backend.session_store import store


# ─── SSE parsing helpers ─────────────────────────────────────────────


def _parse_sse(lines: Iterable[bytes]) -> list[dict]:
    """Decode an SSE byte stream into a list of ``{event, data}`` dicts.

    Default event is ``message``; ``event:`` lines override until the
    next blank line. Heartbeat / comment lines (starting with ``:``)
    are skipped.
    """
    import json

    events: list[dict] = []
    current_event = "message"
    data_buf: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_buf:
                data_str = "\n".join(data_buf)
                try:
                    parsed = json.loads(data_str)
                except json.JSONDecodeError:
                    parsed = data_str
                events.append({"event": current_event, "data": parsed})
                data_buf.clear()
                current_event = "message"
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_buf.append(line[len("data:"):].lstrip())
    return events


def _seed_session(auth_client) -> str:
    sid = auth_client.post("/api/sessions").json()["id"]
    s = store.get(sid)
    assert s is not None
    s.context_variables["playlist"] = [
        {"id": "t1", "display_name": "T1", "bpm": 120, "camelot_key": "8A"},
    ]
    s.context_variables["genre"] = "techno"
    s.phase = "editing"
    return sid


# ─── Happy path: streaming + terminal ``done`` ───────────────────────


def test_editor_command_streams_events_and_closes_with_done(
    auth_client, mock_pipeline,
):
    sid = _seed_session(auth_client)
    with auth_client.stream(
        "POST",
        f"/api/sessions/{sid}/editor_command",
        json={"text": "tweak the set"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        events = _parse_sse(response.iter_bytes())

    # The fake editor emits one text_delta + the bridge wraps with
    # phase_complete + a terminal `done` named event.
    assert any(
        e["event"] == "done"
        for e in events
    ), f"missing terminal done event in {events}"
    # phase_complete must carry the updated session payload.
    phase_completes = [e for e in events if isinstance(e.get("data"), dict)
                       and e["data"].get("type") == "phase_complete"]
    assert phase_completes
    assert "playlist" in phase_completes[-1]["data"]["data"]


def test_editor_command_chains_validate_when_build_lands(
    auth_client, mock_pipeline,
):
    """The fake editor stashes ``last_build`` when ``message`` starts
    with "build "; the SSE bridge should then auto-run phase_validate
    just like the WS dispatcher does."""
    sid = _seed_session(auth_client)
    with auth_client.stream(
        "POST",
        f"/api/sessions/{sid}/editor_command",
        json={"text": "build smoke-set"},
    ) as response:
        events = _parse_sse(response.iter_bytes())

    # We expect a `phase_start validating` somewhere in the stream.
    phase_starts = [
        e for e in events if isinstance(e.get("data"), dict)
        and e["data"].get("type") == "phase_start"
    ]
    assert any(p["data"].get("phase") == "validating" for p in phase_starts)

    # Final session state should be phase="rating" after fake_validate.
    fresh = auth_client.get(f"/api/sessions/{sid}").json()
    assert fresh["phase"] == "rating"


def test_editor_command_surfaces_error_frame(
    auth_client, monkeypatch, mock_pipeline,
):
    sid = _seed_session(auth_client)

    async def _boom(message, history, ctx, emit):
        raise RuntimeError("simulated editor crash")

    monkeypatch.setattr(pipeline, "phase_editor", _boom)

    with auth_client.stream(
        "POST",
        f"/api/sessions/{sid}/editor_command",
        json={"text": "anything"},
    ) as response:
        events = _parse_sse(response.iter_bytes())

    errors = [e for e in events if e["event"] == "error"]
    assert errors, f"expected an error event in {events}"
    assert "simulated editor crash" in errors[0]["data"]["message"]


def test_editor_command_auto_promotes_phase(auth_client, mock_pipeline):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "critique"

    with auth_client.stream(
        "POST",
        f"/api/sessions/{sid}/editor_command",
        json={"text": "swap things"},
    ) as response:
        _ = list(response.iter_bytes())

    fresh = auth_client.get(f"/api/sessions/{sid}").json()
    assert fresh["phase"] in {"editing", "rating"}  # rating if build landed
    # Concretely it should be "editing" because we sent "swap things",
    # not "build".
    assert fresh["phase"] == "editing"


def test_editor_command_rejected_during_live(auth_client, mock_pipeline):
    sid = _seed_session(auth_client)
    s = store.get(sid)
    assert s is not None
    s.phase = "performing"
    r = auth_client.post(
        f"/api/sessions/{sid}/editor_command",
        json={"text": "swap"},
    )
    assert r.status_code == 409


def test_editor_command_rejects_empty_text(auth_client, mock_pipeline):
    sid = _seed_session(auth_client)
    r = auth_client.post(
        f"/api/sessions/{sid}/editor_command",
        json={"text": ""},
    )
    # Pydantic min_length=1 → 422.
    assert r.status_code == 422


def test_editor_command_unauthenticated(client):
    r = client.post(
        "/api/sessions/sid/editor_command",
        json={"text": "swap"},
    )
    assert r.status_code == 401


def test_editor_command_other_users_session_returns_404(
    auth_client, second_client, mock_pipeline,
):
    sid = _seed_session(auth_client)
    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"},
    ).json()["access_token"]
    r = second_client.post(
        f"/api/sessions/{sid}/editor_command",
        json={"text": "swap"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
