"""Unit tests for the session-scoped engine pub/sub (v2.7.2).

Verifies that:
 - ``publish`` fans out to every viewer subscribed on the same key,
 - ``subscribe_viewer`` replays the cached state-snapshot events so a
   late viewer sees the current track immediately,
 - viewers on a different ``(user_id, session_id)`` key do NOT receive
   events from this session (cross-session isolation),
 - ``detach`` removes a single viewer without affecting siblings,
 - ``drop_bus`` clears the cache so a fresh primary starts clean.

The registry is a process-wide singleton; tests reset it between
cases via ``fresh_registry``.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def fresh_registry(monkeypatch):
    from web.backend import live_runtime

    monkeypatch.setattr(live_runtime, "_registry", live_runtime._Registry())
    return live_runtime


@pytest.mark.asyncio
async def test_publish_fans_out_to_every_viewer(fresh_registry):
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def on_a(ev: dict) -> None:
        received_a.append(ev)

    async def on_b(ev: dict) -> None:
        received_b.append(ev)

    await fresh_registry.subscribe_viewer(1, "s1", on_a)
    await fresh_registry.subscribe_viewer(1, "s1", on_b)
    await fresh_registry.publish(1, "s1", {"type": "track_started", "track": {"id": "t1"}})

    assert received_a == [{"type": "track_started", "track": {"id": "t1"}}]
    assert received_b == [{"type": "track_started", "track": {"id": "t1"}}]


@pytest.mark.asyncio
async def test_subscribe_replays_cached_state(fresh_registry):
    """A viewer attaching after the primary already published should
    receive the cached live_state + last load command + last
    track_started immediately so it can render the current picture."""
    await fresh_registry.publish(1, "s1", {
        "type": "live_state",
        "data": {"session_id": "s1", "playlist": [], "engine_state": {}},
    })
    await fresh_registry.publish(1, "s1", {
        "type": "engine_command", "command": "load",
        "track": {"id": "t1", "display_name": "T1"},
    })
    await fresh_registry.publish(1, "s1", {
        "type": "track_started", "track": {"id": "t1"},
    })

    received: list[dict] = []

    async def on_event(ev: dict) -> None:
        received.append(ev)

    await fresh_registry.subscribe_viewer(1, "s1", on_event)
    # Three replays — order matches the cache layout in subscribe_viewer.
    types = [e["type"] for e in received]
    assert "live_state" in types
    assert "engine_command" in types
    assert "track_started" in types
    assert len(received) == 3


@pytest.mark.asyncio
async def test_cross_session_isolation(fresh_registry):
    """A viewer on session A must NOT receive events published to B."""
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def on_a(ev: dict) -> None:
        received_a.append(ev)

    async def on_b(ev: dict) -> None:
        received_b.append(ev)

    await fresh_registry.subscribe_viewer(1, "session-A", on_a)
    await fresh_registry.subscribe_viewer(1, "session-B", on_b)
    await fresh_registry.publish(1, "session-A", {"type": "ping", "n": 1})

    assert len(received_a) == 1
    assert received_b == []


@pytest.mark.asyncio
async def test_detach_removes_only_that_subscriber(fresh_registry):
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def on_a(ev: dict) -> None:
        received_a.append(ev)

    async def on_b(ev: dict) -> None:
        received_b.append(ev)

    sub_a = await fresh_registry.subscribe_viewer(1, "s1", on_a)
    await fresh_registry.subscribe_viewer(1, "s1", on_b)
    await sub_a.detach()
    await fresh_registry.publish(1, "s1", {"type": "after_detach"})

    assert received_a == []  # a is gone
    assert received_b == [{"type": "after_detach"}]


@pytest.mark.asyncio
async def test_drop_bus_clears_cache_for_fresh_primary(fresh_registry):
    """A second primary on the same session must NOT inherit the
    previous primary's track_started cache — that would replay a
    stale track to viewers that attach later."""
    await fresh_registry.publish(1, "s1", {
        "type": "track_started", "track": {"id": "old"},
    })
    await fresh_registry.drop_bus(1, "s1")

    received: list[dict] = []

    async def on_event(ev: dict) -> None:
        received.append(ev)

    await fresh_registry.subscribe_viewer(1, "s1", on_event)
    assert received == []  # No stale replay


@pytest.mark.asyncio
async def test_publish_with_no_viewers_is_safe(fresh_registry):
    """Primary calls publish even with zero viewers; must be a no-op
    (and must still update the cache so a late viewer replays it)."""
    await fresh_registry.publish(1, "s1", {
        "type": "track_started", "track": {"id": "t1"},
    })

    received: list[dict] = []

    async def on_event(ev: dict) -> None:
        received.append(ev)

    await fresh_registry.subscribe_viewer(1, "s1", on_event)
    # The viewer landed AFTER the publish — it should see the cached
    # track_started via replay.
    assert len(received) == 1
    assert received[0]["type"] == "track_started"


@pytest.mark.asyncio
async def test_subscriber_exception_does_not_break_fan_out(fresh_registry):
    """One bad viewer (callback raises) must not prevent other
    viewers from receiving the event."""
    received: list[dict] = []

    async def on_bad(ev: dict) -> None:
        raise RuntimeError("simulated viewer crash")

    async def on_good(ev: dict) -> None:
        received.append(ev)

    await fresh_registry.subscribe_viewer(1, "s1", on_bad)
    await fresh_registry.subscribe_viewer(1, "s1", on_good)
    await fresh_registry.publish(1, "s1", {"type": "after_crash"})

    assert received == [{"type": "after_crash"}]
