"""Integration test for the v2.7 YouTube Live Chat ingest path.

End-to-end-ish: we mock the two ``youtube_*`` modules' public
functions (``get_credentials``, ``discover_active_broadcast``,
``poll_live_chat``) to avoid any real Google round-trip, then drive
the live WebSocket and assert that messages our fake poller emits
end up in the same ``user_msg`` queue the in-browser chat input
already feeds — i.e. the ``[YT @author]`` prefix preserved, the
poller cleanly stopped on disconnect.

The deterministic ``fake_phase_live`` (mock_pipeline.py) echoes any
non-control ``user_msg`` as a ``dj_chat`` "Heard: <text>" event, so
we have a clear thing to assert on without an LLM in the loop.
"""
from __future__ import annotations

import asyncio

import pytest


def _seed_playlist(client, sid: str) -> None:
    """Inject a tiny playlist into the session so the live WS accepts it
    (the handler closes connections with empty playlists at 1008)."""
    from web.backend.session_store import store

    s = store.get(sid)
    s.context_variables["playlist"] = [
        {
            "id": "t1", "display_name": "Track One",
            "bpm": 124.0, "camelot_key": "8A",
            "duration_sec": 30.0, "hot_cues": [],
        },
        {
            "id": "t2", "display_name": "Track Two",
            "bpm": 126.0, "camelot_key": "9A",
            "duration_sec": 30.0, "hot_cues": [],
        },
    ]
    store.save(s)


def _patch_youtube_pipeline(
    monkeypatch,
    *,
    messages: list[tuple[str, str, int]],
    broadcast: dict | None,
):
    """Install fakes for the three module-level YT touchpoints the live
    WS handler reaches into. Returns the asyncio.Event the test can use
    to assert the poller was cleanly torn down."""
    from web.backend import youtube_auth, youtube_chat

    monkeypatch.setattr(youtube_auth, "enabled", lambda: True)
    monkeypatch.setattr(youtube_auth, "get_credentials", lambda user_id: object())

    async def fake_discover(creds):
        return broadcast

    monkeypatch.setattr(youtube_chat, "discover_active_broadcast", fake_discover)

    poll_started = asyncio.Event()
    poll_stopped = asyncio.Event()

    async def fake_poll(creds, live_chat_id, on_message, stop_event, *, own_channel_id=None, on_status=None):
        poll_started.set()
        for author, text, ts in messages:
            await on_message(author, text, ts)
            await asyncio.sleep(0.02)
        # Hold open until the WS handler tears us down so the test can
        # observe the cleanup path.
        try:
            await stop_event.wait()
        finally:
            poll_stopped.set()

    monkeypatch.setattr(youtube_chat, "poll_live_chat", fake_poll)
    return poll_started, poll_stopped


def test_youtube_status_event_when_connected(auth_client, auth_token, mock_pipeline, monkeypatch):
    """When the operator has YT creds + an active broadcast, the live WS
    must emit a ``youtube_status: connected`` frame on connect so the
    frontend pill can render."""
    _patch_youtube_pipeline(
        monkeypatch,
        messages=[],
        broadcast={"id": "bc1", "title": "Apollo Live", "live_chat_id": "lcid", "channel_id": "UCowner"},
    )

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        # Drain a handful of frames; the youtube_status event arrives
        # alongside the engine startup events.
        seen_status = False
        for _ in range(10):
            ev = ws.receive_json()
            if ev.get("type") == "youtube_status":
                assert ev["state"] == "connected"
                assert ev["broadcast"]["id"] == "bc1"
                assert ev["broadcast"]["title"] == "Apollo Live"
                seen_status = True
                break
        assert seen_status, "no youtube_status frame in the first 10 messages"


def test_youtube_status_no_broadcast_when_creds_but_idle(auth_client, auth_token, mock_pipeline, monkeypatch):
    """Operator is linked but isn't currently broadcasting — emit
    ``no_broadcast`` once and don't start a poller."""
    _patch_youtube_pipeline(monkeypatch, messages=[], broadcast=None)

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        seen = False
        for _ in range(10):
            ev = ws.receive_json()
            if ev.get("type") == "youtube_status":
                assert ev["state"] == "no_broadcast"
                seen = True
                break
        assert seen


def test_youtube_messages_become_audience_requests(auth_client, auth_token, mock_pipeline, monkeypatch):
    """The integration claim: a message emitted by ``on_message`` inside
    the YT poller must land in ``command_queue`` as a ``user_msg`` with
    the ``[YT @author]`` prefix. The deterministic fake_phase_live
    echoes any user_msg back as ``dj_chat: "Heard: <text>. ..."``, so
    we assert on that echo to confirm round-trip through the queue."""
    _patch_youtube_pipeline(
        monkeypatch,
        messages=[
            ("alice", "play something deeper", 1_700_000_000_000),
            ("bob", "more bpm please", 1_700_000_001_000),
        ],
        broadcast={"id": "bc1", "title": "Apollo Live", "live_chat_id": "lcid", "channel_id": "UCowner"},
    )

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        echoes: list[str] = []
        # Pump frames generously — track_started + engine_command + the
        # YT-driven dj_chat echoes all come through.
        for _ in range(60):
            ev = ws.receive_json()
            if ev.get("type") == "dj_chat":
                echoes.append(ev.get("text", ""))
                if len(echoes) >= 2:
                    break

        assert any("[YT @alice]" in e and "play something deeper" in e for e in echoes), \
            f"alice's YT message not echoed back as dj_chat — saw {echoes!r}"
        assert any("[YT @bob]" in e and "more bpm please" in e for e in echoes), \
            f"bob's YT message not echoed back as dj_chat — saw {echoes!r}"


def test_youtube_poller_torn_down_on_ws_disconnect(auth_client, auth_token, mock_pipeline, monkeypatch):
    """Closing the WS must signal ``stop_event`` so the poller exits.
    The fake sets a `poll_stopped` event in its finally; we wait on it
    after the WS context manager exits."""
    poll_started, poll_stopped = _patch_youtube_pipeline(
        monkeypatch,
        messages=[],
        broadcast={"id": "bc1", "title": "Apollo Live", "live_chat_id": "lcid", "channel_id": "UCowner"},
    )

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        # Wait for the connected status to confirm the poller was spawned.
        for _ in range(10):
            ev = ws.receive_json()
            if ev.get("type") == "youtube_status" and ev.get("state") == "connected":
                break
        # Quit triggers the WS cleanup path.
        ws.send_json({"type": "quit"})

    # The poller's finally should have set poll_stopped by the time the
    # WS context exits. We give it a small grace window in case the
    # task cancellation lands asynchronously.
    async def _wait_stop():
        try:
            await asyncio.wait_for(poll_stopped.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    asyncio.new_event_loop().run_until_complete(_wait_stop())
    assert poll_stopped.is_set(), "yt poller never tore down on WS disconnect"


def test_no_youtube_events_when_user_not_connected(auth_client, auth_token, mock_pipeline, monkeypatch):
    """``get_credentials`` returning ``None`` (the unconnected case) must
    short-circuit the YT branch entirely — no youtube_status frame, no
    poller spawned, live session runs exactly as v2.6.x did."""
    from web.backend import youtube_auth

    monkeypatch.setattr(youtube_auth, "enabled", lambda: True)
    monkeypatch.setattr(youtube_auth, "get_credentials", lambda user_id: None)

    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        # Drain whatever the engine startup emits (typically live_state +
        # track_started + an engine_command). Each receive has a short
        # timeout so we don't hang past the engine's quiet period — the
        # claim under test is simply "no youtube_status frame appears".
        seen_types: list[str] = []
        # Wait for the first track_started — that's the signal the engine
        # is up and we've seen all the synchronous startup frames.
        for _ in range(15):
            ev = ws.receive_json()
            seen_types.append(ev.get("type"))
            if ev.get("type") == "track_started":
                break
        # Quit so the handler tears down cleanly rather than hanging on
        # command_queue.get() in fake_phase_live.
        ws.send_json({"type": "quit"})
        assert "youtube_status" not in seen_types, \
            f"youtube_status leaked through despite no creds — saw {seen_types}"
