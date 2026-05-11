"""Integration tests for the /ws/live/{id} WebSocket endpoint (v2.5.1)."""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def _seed_playlist(client, sid: str) -> list[dict]:
    """Inject a tiny playlist directly into the session store so the live WS
    handler has something to play. The planning flow is exercised by
    ``test_ws_session.py`` — we don't need to repeat it here."""
    from web.backend.session_store import store

    s = store.get(sid)
    playlist = [
        {
            "id": "t1",
            "display_name": "Track One",
            "bpm": 124.0,
            "camelot_key": "8A",
            "duration_sec": 30.0,
            "hot_cues": [],
        },
        {
            "id": "t2",
            "display_name": "Track Two",
            "bpm": 126.0,
            "camelot_key": "9A",
            "duration_sec": 30.0,
            "hot_cues": [],
        },
    ]
    s.context_variables["playlist"] = playlist
    store.save(s)
    return playlist


def test_live_ws_rejects_bad_token(auth_client, mock_pipeline):
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with pytest.raises(WebSocketDisconnect):
        with auth_client.websocket_connect(f"/ws/live/{sid}?token=garbage"):
            pass


def test_live_ws_rejects_other_users_session(
    auth_client, second_client, mock_pipeline
):
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)

    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    other_token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"}
    ).json()["access_token"]

    with pytest.raises(WebSocketDisconnect):
        with second_client.websocket_connect(
            f"/ws/live/{sid}?token={other_token}"
        ):
            pass


def test_live_ws_rejects_session_with_empty_playlist(
    auth_client, auth_token, mock_pipeline
):
    """No playlist on the session = no live performance. The handler closes
    the socket immediately so the UI can fall back to the planning flow."""
    sid = auth_client.post("/api/sessions").json()["id"]
    with pytest.raises(WebSocketDisconnect):
        with auth_client.websocket_connect(
            f"/ws/live/{sid}?token={auth_token}"
        ):
            pass


def test_live_ws_handshake_emits_initial_state_and_track_started(
    auth_client, auth_token, mock_pipeline
):
    sid = auth_client.post("/api/sessions").json()["id"]
    playlist = _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        # The first message is always the live_state snapshot.
        first = ws.receive_json()
        assert first["type"] == "live_state"
        assert first["data"]["session_id"] == sid
        assert len(first["data"]["playlist"]) == len(playlist)

        # Then the engine emits track_started + the engine_command load
        # (ordering between them isn't guaranteed because they go through
        # the same emitter callback). Drain a few frames and assert both
        # appeared.
        events = [first]
        for _ in range(8):
            events.append(ws.receive_json())
            if any(e.get("type") == "track_started" for e in events):
                break

    types = [e.get("type") for e in events]
    assert "track_started" in types
    started = next(e for e in events if e.get("type") == "track_started")
    assert started["track"]["id"] == "t1"


def test_live_ws_routes_user_command_to_engine_skip(
    auth_client, auth_token, mock_pipeline
):
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        # Drain handshake
        ws.receive_json()  # live_state
        # Wait for first track_started
        for _ in range(8):
            ev = ws.receive_json()
            if ev.get("type") == "track_started":
                break

        ws.send_json({"type": "user_msg", "text": "skip"})

        # Drain until we see the second track_started (proves skip routed
        # through the mock fake_phase_live → engine.skip_track()).
        seen_skip = False
        for _ in range(20):
            ev = ws.receive_json()
            if (
                ev.get("type") == "track_started"
                and ev.get("track", {}).get("id") == "t2"
            ):
                seen_skip = True
                break
        assert seen_skip


def test_live_ws_disconnect_cleans_up(auth_client, auth_token, mock_pipeline):
    """Closing the websocket from the client side must cancel the live phase
    task and release the engine. We verify by reconnecting on the same
    session id immediately after — if the previous run leaked, the second
    connect would race the stale task / emitter."""
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)

    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # live_state — confirms handshake
        # Drop straight out of the with-block to trigger disconnect.

    # A second connect on the same session must succeed — proves the WS
    # manager freed the slot (channel="live") and the previous phase task
    # got cancelled cleanly. If either leaked we'd hang here.
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws2:
        first = ws2.receive_json()
        assert first["type"] == "live_state"


def test_live_ws_get_state_returns_engine_snapshot(
    auth_client, auth_token, mock_pipeline
):
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial live_state
        for _ in range(6):
            ev = ws.receive_json()
            if ev.get("type") == "track_started":
                break
        ws.send_json({"type": "get_state"})
        # The next live_state response carries the latest engine snapshot.
        for _ in range(6):
            ev = ws.receive_json()
            if ev.get("type") == "live_state":
                assert "engine_state" in ev["data"]
                assert ev["data"]["engine_state"]["current_track"] is not None
                return
        raise AssertionError("Never received live_state in response to get_state")


# ---------------------------------------------------------------------------
# v2.6.0 — set_endless_mode round-trip
# ---------------------------------------------------------------------------

def test_live_ws_set_endless_mode_round_trip(
    auth_client, auth_token, mock_pipeline
):
    """Sending ``set_endless_mode`` over the live WS must:
       - persist the flag to ``session.context_variables["endless_mode"]``,
       - flip the live engine's ``_endless_mode`` attribute, and
       - echo an ``endless_mode`` confirmation event back to the client.
    The frontend uses the echo as the source of truth for the toggle pill.
    """
    from web.backend.session_store import store

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial live_state
        # Drain until track_started so the engine is up.
        for _ in range(8):
            ev = ws.receive_json()
            if ev.get("type") == "track_started":
                break

        # ── Enable ──
        ws.send_json({"type": "set_endless_mode", "enabled": True})
        for _ in range(8):
            ev = ws.receive_json()
            if ev.get("type") == "endless_mode":
                assert ev.get("enabled") is True
                break
        else:
            raise AssertionError("No endless_mode echo for enabled=True")
        assert store.get(sid).context_variables.get("endless_mode") is True

        # ── Disable ──
        ws.send_json({"type": "set_endless_mode", "enabled": False})
        for _ in range(8):
            ev = ws.receive_json()
            if ev.get("type") == "endless_mode":
                assert ev.get("enabled") is False
                break
        else:
            raise AssertionError("No endless_mode echo for enabled=False")
        assert store.get(sid).context_variables.get("endless_mode") is False
