"""Unit tests for web/backend/ws_manager.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from web.backend.ws_manager import WSManager


@pytest.mark.asyncio
async def test_connect_accepts_and_stores():
    mgr = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    await mgr.connect("sid", ws)
    ws.accept.assert_awaited_once()
    assert mgr.is_connected("sid")


@pytest.mark.asyncio
async def test_send_to_missing_session_is_silent():
    mgr = WSManager()
    await mgr.send("missing", {"type": "noop"})  # must not raise


@pytest.mark.asyncio
async def test_send_forwards_json():
    mgr = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    await mgr.connect("sid", ws)
    await mgr.send("sid", {"type": "hello"})
    ws.send_json.assert_awaited_once_with({"type": "hello"})


@pytest.mark.asyncio
async def test_send_disconnects_on_error():
    mgr = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("broken"))
    await mgr.connect("sid", ws)
    await mgr.send("sid", {"type": "x"})
    assert not mgr.is_connected("sid")


def test_disconnect_removes_session():
    mgr = WSManager()
    # v2.5.1 — connections are keyed on (session_id, channel) so planning
    # and live websockets can coexist on the same session id.
    mgr._connections[("sid", "planning")] = MagicMock()  # type: ignore[assignment]
    mgr.disconnect("sid")
    assert not mgr.is_connected("sid")
    mgr.disconnect("sid")  # idempotent


@pytest.mark.asyncio
async def test_planning_and_live_channels_are_independent():
    """A single session can host /ws/sessions/{id} (planning) and
    /ws/live/{id} (live) at the same time without overwriting each other."""
    mgr = WSManager()
    planning = MagicMock()
    planning.accept = AsyncMock()
    planning.send_json = AsyncMock()
    live = MagicMock()
    live.accept = AsyncMock()
    live.send_json = AsyncMock()

    await mgr.connect("sid", planning)
    await mgr.connect("sid", live, channel="live")
    assert mgr.is_connected("sid")
    assert mgr.is_connected("sid", channel="live")

    await mgr.send("sid", {"type": "p"})
    await mgr.send("sid", {"type": "l"}, channel="live")
    planning.send_json.assert_awaited_once_with({"type": "p"})
    live.send_json.assert_awaited_once_with({"type": "l"})

    mgr.disconnect("sid", channel="live")
    assert mgr.is_connected("sid")
    assert not mgr.is_connected("sid", channel="live")
