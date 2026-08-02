"""Unit tests for the session-scoped YT poller registry (v2.7.2).

Verifies the ref-counting + grace-window behaviour of
``youtube_runtime`` without spinning up real Google API calls. Both
``youtube_auth`` and ``youtube_chat`` are monkey-patched.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


@pytest.fixture
def fresh_registry(monkeypatch):
    """Reset the module-level singleton between tests so ref-counts
    don't leak across cases."""
    from web.backend import youtube_runtime

    # Replace the singleton with a fresh _Registry instance so each
    # test runs in isolation. The public API names still point at the
    # fresh registry because attach() / snapshot() resolve via the
    # module global.
    monkeypatch.setattr(youtube_runtime, "_registry", youtube_runtime._Registry())
    # Speed up the grace window so tests finish in <1 s rather than
    # waiting the production 30 s default.
    monkeypatch.setattr(youtube_runtime, "_GRACE_SEC", 0.05)
    return youtube_runtime


@pytest.fixture
def fake_yt(monkeypatch):
    """Stub the YT auth + chat boundary so the registry's first-attach
    path resolves without real network calls. Returns a controller
    dict the test can mutate to flip the simulated state."""
    state = {
        "enabled": True,
        "creds_for_user": {1: object(), 2: object()},
        "broadcast": {
            "id": "bc1", "title": "Apollo Live",
            "live_chat_id": "lcid", "channel_id": "UCowner",
        },
    }
    poll_calls: list[dict] = []

    from web.backend import youtube_runtime, youtube_auth, youtube_chat

    monkeypatch.setattr(youtube_auth, "enabled", lambda: state["enabled"])
    monkeypatch.setattr(
        youtube_auth, "get_credentials",
        lambda user_id: state["creds_for_user"].get(user_id),
    )

    async def fake_discover(creds):
        return state["broadcast"]

    monkeypatch.setattr(youtube_chat, "discover_active_broadcast", fake_discover)

    async def fake_poll(creds, live_chat_id, on_message, stop_event, *, own_channel_id=None, on_status=None):
        poll_calls.append({
            "live_chat_id": live_chat_id,
            "own_channel_id": own_channel_id,
        })
        await stop_event.wait()

    monkeypatch.setattr(youtube_chat, "poll_live_chat", fake_poll)
    state["poll_calls"] = poll_calls
    return state


@pytest.mark.asyncio
async def test_first_attach_spawns_poller_and_returns_connected_state(fresh_registry, fake_yt):
    received_messages: list[tuple[str, str, int]] = []

    async def on_message(author, text, ts):
        received_messages.append((author, text, ts))

    async def on_status(payload):
        pass

    sub, state = await fresh_registry.attach(
        user_id=1, session_id="s1",
        on_message=on_message, on_status=on_status,
    )
    assert state["state"] == "connected"
    assert state["broadcast"]["id"] == "bc1"
    # Yield once so the spawned poller task actually runs and records
    # its call into the fake. ``asyncio.create_task`` schedules but
    # doesn't execute synchronously.
    await asyncio.sleep(0.01)
    # Poller was spawned with the right chat id.
    assert fake_yt["poll_calls"] == [{
        "live_chat_id": "lcid",
        "own_channel_id": "UCowner",
    }]
    await sub.detach()
    # Wait long enough for the grace-window teardown to fire.
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_second_attach_on_same_session_reuses_runtime(fresh_registry, fake_yt):
    """Two WSes attaching to the same (user, session) share ONE poller.
    The second attach must NOT trigger a discover + spawn round-trip."""

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub1, state1 = await fresh_registry.attach(1, "s1", on_message, on_status)
    sub2, state2 = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert state1 == state2
    await asyncio.sleep(0.01)
    # Only one poll_live_chat call across both attaches.
    assert len(fake_yt["poll_calls"]) == 1
    await sub1.detach()
    await sub2.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_different_session_gets_its_own_poller(fresh_registry, fake_yt):
    """Same user but a DIFFERENT session_id → distinct runtimes."""

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub1, _ = await fresh_registry.attach(1, "s1", on_message, on_status)
    sub2, _ = await fresh_registry.attach(1, "s2", on_message, on_status)
    await asyncio.sleep(0.01)
    assert len(fake_yt["poll_calls"]) == 2
    await sub1.detach()
    await sub2.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_message_fans_out_to_all_subscribers(fresh_registry, monkeypatch):
    """A single poll_live_chat callback invocation must reach EVERY
    currently-subscribed on_message callback."""
    from web.backend import youtube_runtime, youtube_auth, youtube_chat

    monkeypatch.setattr(youtube_auth, "enabled", lambda: True)
    monkeypatch.setattr(youtube_auth, "get_credentials", lambda uid: object())

    async def fake_discover(creds):
        return {
            "id": "bc", "title": "t", "live_chat_id": "lcid", "channel_id": "UCowner",
        }

    monkeypatch.setattr(youtube_chat, "discover_active_broadcast", fake_discover)

    captured_on_message = {}  # captures the registry's fan-out wrapper

    async def fake_poll(creds, live_chat_id, on_message, stop_event, **kwargs):
        captured_on_message["fn"] = on_message
        await stop_event.wait()

    monkeypatch.setattr(youtube_chat, "poll_live_chat", fake_poll)

    received_a: list[tuple[str, bool]] = []
    received_b: list[tuple[str, bool]] = []

    # v3.7.0 — on_message carries is_first (author's first message this
    # stream) as its fourth argument.
    async def a_on_message(author, text, ts, is_first):
        received_a.append((text, is_first))

    async def b_on_message(author, text, ts, is_first):
        received_b.append((text, is_first))

    async def noop_status(p): pass

    sub_a, _ = await fresh_registry.attach(1, "s1", a_on_message, noop_status)
    sub_b, _ = await fresh_registry.attach(1, "s1", b_on_message, noop_status)

    # Yield once so the poller task starts and captures the fan-out fn.
    await asyncio.sleep(0.01)
    assert "fn" in captured_on_message, "poller didn't start"
    await captured_on_message["fn"]("alice", "hello", 1)
    assert received_a == [("hello", True)]
    assert received_b == [("hello", True)]

    # Second message from the same chatter: fans out again, but is_first
    # is computed ONCE runtime-side — both subscribers see False.
    await captured_on_message["fn"]("alice", "again", 2)
    assert received_a[-1] == ("again", False)
    assert received_b[-1] == ("again", False)

    await sub_a.detach()
    await sub_b.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_teardown_scheduled_when_last_subscriber_leaves(fresh_registry, fake_yt):
    """Last detach → grace timer fires → poller cancelled, runtime
    purged from the registry."""

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub, _ = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert (1, "s1") in fresh_registry._registry._runtimes
    await sub.detach()
    # Grace is 0.05 s; give it a comfortable margin to fire.
    await asyncio.sleep(0.25)
    assert (1, "s1") not in fresh_registry._registry._runtimes


@pytest.mark.asyncio
async def test_reattach_within_grace_window_keeps_runtime(fresh_registry, fake_yt):
    """A WS reconnect inside the grace window must cancel the pending
    teardown and reuse the existing poller — no extra discover call."""

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub1, _ = await fresh_registry.attach(1, "s1", on_message, on_status)
    await asyncio.sleep(0.01)  # let the poller record its first call
    await sub1.detach()
    # Re-attach immediately, well inside the 0.05-s grace.
    sub2, state = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert state["state"] == "connected"
    # Only ONE poll_live_chat call — the runtime was reused.
    assert len(fake_yt["poll_calls"]) == 1
    assert (1, "s1") in fresh_registry._registry._runtimes
    await sub2.detach()
    await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_attach_when_yt_disabled_returns_off_state(fresh_registry, fake_yt):
    """When ``youtube_auth.enabled()`` is False, attach returns
    state="off" and does NOT spawn a poller."""
    fake_yt["enabled"] = False

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub, state = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert state["state"] == "off"
    assert fake_yt["poll_calls"] == []
    await sub.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_attach_when_user_not_connected_returns_disconnected(fresh_registry, fake_yt):
    """YT is configured but the user hasn't OAuthed → ``disconnected``
    state, no poller spawned."""
    fake_yt["creds_for_user"] = {}  # no user has creds

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub, state = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert state["state"] == "disconnected"
    assert state.get("reason") == "not_connected"
    assert fake_yt["poll_calls"] == []
    await sub.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_attach_when_no_active_broadcast_returns_no_broadcast(fresh_registry, fake_yt):
    """User has creds but no live broadcast → ``no_broadcast``, no poller."""
    fake_yt["broadcast"] = None
    from web.backend import youtube_chat

    async def fake_discover(creds):
        return None

    # The fake_yt fixture already monkeypatched discover; re-patch with
    # the no-broadcast return for this test.
    import pytest as _pytest
    # We can't easily re-monkeypatch from inside a test that uses
    # an existing fixture, so import the actual module and use its
    # setattr directly. The previous monkeypatch will be undone by
    # pytest at test exit regardless.
    youtube_chat.discover_active_broadcast = fake_discover  # type: ignore[assignment]

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub, state = await fresh_registry.attach(1, "s1", on_message, on_status)
    assert state["state"] == "no_broadcast"
    assert fake_yt["poll_calls"] == []
    await sub.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_snapshot_returns_state_without_affecting_ref_count(fresh_registry, fake_yt):
    """``snapshot()`` is read-only — calling it does not delay teardown
    or count as a subscriber."""

    async def on_message(a, t, ts): pass
    async def on_status(p): pass

    sub, _ = await fresh_registry.attach(1, "s1", on_message, on_status)
    snap = await fresh_registry.snapshot(1, "s1")
    assert snap is not None and snap["state"] == "connected"
    await sub.detach()
    await asyncio.sleep(0.25)
    assert await fresh_registry.snapshot(1, "s1") is None


# ---------------------------------------------------------------------------
# v3.7.1 — broadcast rediscovery after an early no_broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_broadcast_rediscovers_and_connects(
    fresh_registry, fake_yt, monkeypatch
):
    """The live failure 2026-07-12: the page attaches BEFORE the YouTube
    broadcast flips live, discovery returns None, and chat stayed dead
    for the whole stream. The rediscovery loop must connect once the
    broadcast appears and push the state flip to attached subscribers."""
    monkeypatch.setattr(fresh_registry, "REDISCOVER_INTERVAL_SEC", 0.05)
    fake_yt["broadcast"] = None  # page connects too early

    statuses: list[dict] = []

    async def on_message(author, text, ts, is_first):
        pass

    async def on_status(payload):
        statuses.append(dict(payload))

    sub, snapshot = await fresh_registry.attach(1, "s-early", on_message, on_status)
    assert snapshot["state"] == "no_broadcast"
    assert fake_yt["poll_calls"] == []

    # A couple of probe intervals with the broadcast still absent.
    await asyncio.sleep(0.12)
    assert fake_yt["poll_calls"] == []

    # OBS starts, YouTube flips live.
    fake_yt["broadcast"] = {
        "id": "bc-late", "title": "Apollo Live",
        "live_chat_id": "lcid-late", "channel_id": "UCowner",
    }
    await asyncio.sleep(0.15)

    # Poller connected against the late broadcast…
    assert fake_yt["poll_calls"], "poller never started after rediscovery"
    assert fake_yt["poll_calls"][0]["live_chat_id"] == "lcid-late"
    # …and every attached WS got the state flip (UI pill goes green).
    assert any(s.get("state") == "connected" for s in statuses)

    snap = await fresh_registry.snapshot(1, "s-early")
    assert snap and snap["state"] == "connected"

    await sub.detach()
    await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_rediscovery_task_dies_with_teardown(
    fresh_registry, fake_yt, monkeypatch
):
    """Detaching the last subscriber must cancel the rediscovery loop
    after the grace window — no orphan task probing quota forever."""
    monkeypatch.setattr(fresh_registry, "REDISCOVER_INTERVAL_SEC", 0.05)
    fake_yt["broadcast"] = None

    probes = {"n": 0}
    from web.backend import youtube_chat

    async def counting_discover(creds):
        probes["n"] += 1
        return None

    monkeypatch.setattr(youtube_chat, "discover_active_broadcast", counting_discover)

    async def on_message(author, text, ts, is_first):
        pass

    async def noop_status(p):
        pass

    sub, snapshot = await fresh_registry.attach(1, "s-gone", on_message, noop_status)
    assert snapshot["state"] == "no_broadcast"
    await sub.detach()
    # Grace (0.05s) elapses → teardown cancels the rediscover task.
    await asyncio.sleep(0.25)
    settled = probes["n"]
    await asyncio.sleep(0.25)
    assert probes["n"] == settled, "rediscovery kept probing after teardown"
