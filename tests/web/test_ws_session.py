"""Integration tests for the /ws/sessions/{id} WebSocket endpoint."""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def _receive_until(ws, predicate, limit=20):
    """Receive up to `limit` messages until `predicate(event)` is truthy."""
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if predicate(event):
            return events
    raise AssertionError(f"Predicate never satisfied in {limit} messages: {events}")


def test_ws_rejects_bad_token(auth_client, mock_pipeline):
    sid = auth_client.post("/api/sessions").json()["id"]
    with pytest.raises(WebSocketDisconnect):
        with auth_client.websocket_connect(f"/ws/sessions/{sid}?token=garbage"):
            pass


def test_ws_rejects_other_users_session(auth_client, second_client, mock_pipeline):
    sid = auth_client.post("/api/sessions").json()["id"]

    second_client.post(
        "/api/auth/register",
        json={"username": "u2", "email": "u2@t.io", "password": "pw12345"},
    )
    other_token = second_client.post(
        "/api/auth/login", json={"username": "u2", "password": "pw12345"}
    ).json()["access_token"]

    with pytest.raises(WebSocketDisconnect):
        with second_client.websocket_connect(f"/ws/sessions/{sid}?token={other_token}"):
            pass


def test_ws_initial_state_event(auth_client, auth_token, mock_pipeline):
    sid = auth_client.post("/api/sessions").json()["id"]
    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        assert first["data"]["id"] == sid


def test_ws_genre_intent_runs_planner(auth_client, auth_token, mock_pipeline):
    """genre_intent should confirm genre AND auto-run the Planner, ending on phase_complete: planning."""
    sid = auth_client.post("/api/sessions").json()["id"]
    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial state
        ws.send_json({"type": "genre_intent", "content": "60 minutes of dark techno"})

        # Drain until the final phase_complete for 'planning' arrives
        events = _receive_until(
            ws,
            lambda e: e.get("type") == "phase_complete" and e.get("phase") == "planning",
        )

    phases_started = [e.get("phase") for e in events if e["type"] == "phase_start"]
    phases_done = [e.get("phase") for e in events if e["type"] == "phase_complete"]
    assert "genre" in phases_done
    assert "planning" in phases_started
    assert "planning" in phases_done


def test_ws_get_state_roundtrip(auth_client, auth_token, mock_pipeline):
    sid = auth_client.post("/api/sessions").json()["id"]
    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial
        ws.send_json({"type": "get_state"})
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["data"]["id"] == sid


# ---------------------------------------------------------------------------
# Genre Guard banner suppression — regression tests for issue #23.
#
# Before the fix, _handle_ws_message emitted {"type":"error", ...} on every
# non-confirmed genre turn, including the totally normal turn where the LLM
# is just asking "Is this correct?". Now the handler distinguishes:
#
#   * non-empty assistant response + under MAX_GENRE_TURNS → no error,
#     phase stays at "genre" so the user's next message replies via the
#     same handler;
#   * empty/whitespace assistant response → error + phase reset;
#   * MAX_GENRE_TURNS exceeded → error + phase reset.
#
# The first batch are unit tests against the extracted helper (cheap, fast,
# no WS plumbing). The second batch is a single integration smoke test that
# wires the helper through the real handler.
# ---------------------------------------------------------------------------

class TestGenreGuardErrorPolicy:
    """Unit tests for the _should_emit_genre_error helper. Issue #23."""

    def test_returns_false_when_agent_is_still_asking(self):
        from web.backend.app import _should_emit_genre_error

        history = [
            {"role": "user", "content": "I want some music"},
            {"role": "assistant", "content": "What genre would you like? Lofi, techno, deep house?"},
        ]
        assert _should_emit_genre_error(history) is False

    def test_returns_true_when_assistant_response_is_empty(self):
        from web.backend.app import _should_emit_genre_error

        history = [
            {"role": "user", "content": "I want some music"},
            {"role": "assistant", "content": ""},
        ]
        assert _should_emit_genre_error(history) is True

    def test_returns_true_when_assistant_response_is_whitespace(self):
        from web.backend.app import _should_emit_genre_error

        history = [
            {"role": "user", "content": "I want some music"},
            {"role": "assistant", "content": "   \n\t "},
        ]
        assert _should_emit_genre_error(history) is True

    def test_returns_true_when_user_turn_cap_reached(self):
        from web.backend.app import MAX_GENRE_TURNS, _should_emit_genre_error

        history = []
        for i in range(MAX_GENRE_TURNS):
            history.append({"role": "user", "content": f"turn {i}"})
            history.append({"role": "assistant", "content": "Could you clarify?"})
        assert _should_emit_genre_error(history) is True

    def test_returns_false_just_below_user_turn_cap(self):
        from web.backend.app import MAX_GENRE_TURNS, _should_emit_genre_error

        history = []
        for i in range(MAX_GENRE_TURNS - 1):
            history.append({"role": "user", "content": f"turn {i}"})
            history.append({"role": "assistant", "content": "Could you clarify?"})
        assert _should_emit_genre_error(history) is False


def _drain_until_no_more(ws, max_messages=10):
    """Pull every WS event currently buffered, then return the list."""
    out = []
    for _ in range(max_messages):
        try:
            out.append(ws.receive_json(mode="binary"))
        except Exception:
            break
    return out


def test_ws_genre_guard_no_error_on_in_progress_turn(auth_client, auth_token, mock_pipeline, monkeypatch):
    """When phase_genre_guard returns None but appended a non-empty
    assistant turn (the "Is this correct?" case), the handler must NOT
    emit a misleading error banner. Issue #23."""
    from web.backend import pipeline

    async def fake_in_progress(message, history, ctx, emit):
        await emit({"type": "text_delta", "content": "Did you mean dark techno?"})
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "Did you mean dark techno?"})
        return None  # not yet confirmed

    monkeypatch.setattr(pipeline, "phase_genre_guard", fake_in_progress)

    sid = auth_client.post("/api/sessions").json()["id"]
    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial state
        ws.send_json({"type": "genre_intent", "content": "techno-ish?"})

        events = []
        # Pull until we hit the text_delta from fake_in_progress and a few
        # more frames after, to catch any (incorrect) error emit.
        for _ in range(6):
            events.append(ws.receive_json())
            if events[-1].get("type") == "text_delta":
                break
        # Drain a couple more potential buffered frames.
        ws.send_json({"type": "get_state"})
        for _ in range(4):
            events.append(ws.receive_json())
            if events[-1].get("type") == "state":
                break

    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events == [], f"Unexpected error event(s): {error_events}"

    state_events = [e for e in events if e.get("type") == "state"]
    assert state_events, "Expected a state event in response to get_state"
    assert state_events[-1]["data"]["phase"] == "genre"


def test_ws_genre_guard_error_on_empty_response(auth_client, auth_token, mock_pipeline, monkeypatch):
    """When the LLM returns an empty assistant response (likely an API
    failure), the handler MUST surface the error and reset phase.
    Issue #23."""
    from web.backend import pipeline

    async def fake_empty_response(message, history, ctx, emit):
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": ""})
        return None

    monkeypatch.setattr(pipeline, "phase_genre_guard", fake_empty_response)

    sid = auth_client.post("/api/sessions").json()["id"]
    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial state
        ws.send_json({"type": "genre_intent", "content": "anything"})

        events = _receive_until(ws, lambda e: e.get("type") == "error")
        ws.send_json({"type": "get_state"})
        events.extend(_receive_until(ws, lambda e: e.get("type") == "state"))

    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events, "Expected an error event when assistant response is empty"
    state_events = [e for e in events if e.get("type") == "state"]
    assert state_events[-1]["data"]["phase"] == "init"


def test_ws_genre_guard_error_after_max_turns(auth_client, auth_token, mock_pipeline, monkeypatch):
    """If the user has exchanged MAX_GENRE_TURNS messages without the LLM
    confirming, the handler MUST surface the error and reset phase even
    when the latest assistant response is non-empty. Issue #23.

    We pre-load the session's genre history with (MAX_GENRE_TURNS - 1)
    user/assistant exchanges so the very next genre_intent message hits
    the cap. This avoids round-tripping each turn through the WS event
    loop (which deadlocks on the non-confirm path because the handler
    emits nothing in the in-progress branch).
    """
    from web.backend import pipeline
    from web.backend.app import MAX_GENRE_TURNS
    from web.backend.session_store import store

    async def fake_keeps_asking(message, history, ctx, emit):
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "Could you clarify the genre?"})
        return None

    monkeypatch.setattr(pipeline, "phase_genre_guard", fake_keeps_asking)

    sid = auth_client.post("/api/sessions").json()["id"]

    # Pre-fill genre history so the next user turn pushes us over the cap.
    sess = store.get(sid)
    primed = []
    for i in range(MAX_GENRE_TURNS - 1):
        primed.append({"role": "user", "content": f"primed user turn {i}"})
        primed.append({"role": "assistant", "content": "Could you clarify?"})
    sess.messages["genre"] = primed

    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token={auth_token}") as ws:
        ws.receive_json()  # initial state
        ws.send_json({"type": "genre_intent", "content": "final turn"})
        events = _receive_until(ws, lambda e: e.get("type") == "error")
        ws.send_json({"type": "get_state"})
        state = _receive_until(ws, lambda e: e.get("type") == "state")[-1]

    assert any(e.get("type") == "error" for e in events)
    assert state["data"]["phase"] == "init"
