"""Session-scoped engine-event pub/sub for the live channel (v2.7.2).

Until v2.7.2, every WebSocket landing on ``/api/sessions/{id}/live/stream``
built its own ``LiveEngineBrowser`` instance and pushed events back over
that single socket via :mod:`ws_manager` — which is keyed by
``(session_id, channel)`` and silently overwrites the previous entry on
duplicate connect. The result: when an OBS Browser Source opened the
same URL the operator's tab was already on, the two handlers stomped
each other in the manager's dict, one of them exited, its ``finally``
unregistered the channel, and *both* clients ended up disconnected.

This module fixes the contention by hoisting engine events to **session
scope**. The primary ``live`` WS owns the engine; the new ``live-viewer``
WS attaches as a read-only subscriber. Both receive the same emit stream
via fan-out, but only the primary drives the engine and accepts
commands. Viewers (OBS Browser Source, dashboards, debug consoles) come
and go without disturbing the primary.

Public API
----------
- :func:`publish(user_id, session_id, event)` — primary calls this on
  every engine emit. Viewer subscribers attached to the matching bus
  receive the event via their ``on_event`` callback.
- :func:`subscribe_viewer(user_id, session_id, on_event)` — register a
  viewer. Returns a :class:`ViewerSubscription` whose ``detach()``
  removes it. On subscribe, the bus replays the cached state-snapshot
  events (``live_state`` + last ``track_started``) so the viewer sees
  the current picture immediately instead of waiting for the next
  natural emit.

Caching strategy
----------------
A late-arriving viewer (Chrome refresh, OBS Browser Source reconnect)
needs to know *what's playing right now*. Caching every event is
wasteful; instead we keep one snapshot per "shape":

- ``live_state`` — the playlist + engine state, emitted at handshake.
- ``track_started`` — the most recent track, useful for visualizer +
  now-playing overlay.
- ``engine_command load`` — the active deck's audio src, so a viewer
  that joins mid-track can load the same file and resume playback in
  rough sync. (The viewer's exact playback position will lag a few
  hundred ms; that's acceptable for a passive viewer.)

Lifecycle
---------
Buses are created lazily on first ``publish`` or ``subscribe_viewer``
call and removed when the primary detaches. We do not currently
implement a grace window for the primary — if the operator's WS dies,
the bus disappears and viewers see their next event stream go silent.
That matches the prior single-WS behaviour while fixing the
contention case.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(eq=False)
class _Subscriber:
    """One viewer attached to a session's engine bus.

    ``eq=False`` keeps identity-based hashing so subscribers can live
    in a ``set`` despite holding a callable.
    """

    on_event: OnEvent


@dataclass
class _Bus:
    """All subscribers + cached state for one session's engine stream."""

    viewers: set[_Subscriber] = field(default_factory=set)
    #: Most recent ``live_state`` payload (handshake snapshot).
    last_live_state: dict | None = None
    #: Most recent ``track_started`` payload (now-playing).
    last_track_started: dict | None = None
    #: Most recent ``engine_command`` with ``command in {"load","crossfade"}``
    #: so a late viewer can pick up the active deck.
    last_load_command: dict | None = None


@dataclass
class ViewerSubscription:
    """Opaque handle returned by :func:`subscribe_viewer`. Hold until WS closes."""

    _registry: "_Registry"
    _key: tuple[int, str]
    _subscriber: _Subscriber

    async def detach(self) -> None:
        await self._registry._detach_viewer(self._key, self._subscriber)


class _Registry:
    """Process-wide singleton holding all per-session buses."""

    def __init__(self) -> None:
        self._buses: dict[tuple[int, str], _Bus] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self, user_id: int, session_id: str, event: dict[str, Any]
    ) -> None:
        """Fan out an engine event to every viewer on this session.

        Also updates the per-shape state cache so a viewer joining
        after this call still sees a coherent picture. Returns
        immediately if no bus exists — primaries call this even when
        no viewers are attached, so the no-op case must be cheap.
        """
        async with self._lock:
            bus = self._buses.get((user_id, session_id))
            if bus is None:
                # Lazily create the bus so a viewer landing before the
                # primary's first publish still finds a place to attach.
                bus = _Bus()
                self._buses[(user_id, session_id)] = bus
            self._update_cache(bus, event)
            # Snapshot the subscriber list under the lock so a
            # concurrent detach doesn't mutate during fan-out.
            viewers = list(bus.viewers)
        # Fan out outside the lock — viewer callbacks may themselves
        # take a moment (ws.send_json is a network round-trip on a
        # slow client).
        for sub in viewers:
            try:
                await sub.on_event(event)
            except Exception as exc:  # noqa: BLE001
                log.exception("live_runtime: viewer.on_event raised: %s", exc)

    @staticmethod
    def _update_cache(bus: _Bus, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "live_state":
            bus.last_live_state = dict(event)
        elif event_type == "track_started":
            bus.last_track_started = dict(event)
        elif event_type == "engine_command" and event.get("command") in (
            "load",
            "crossfade",
        ):
            bus.last_load_command = dict(event)

    async def subscribe_viewer(
        self, user_id: int, session_id: str, on_event: OnEvent
    ) -> ViewerSubscription:
        """Register a read-only viewer. Replays cached state inline."""
        key = (user_id, session_id)
        sub = _Subscriber(on_event=on_event)
        async with self._lock:
            bus = self._buses.get(key)
            if bus is None:
                bus = _Bus()
                self._buses[key] = bus
            bus.viewers.add(sub)
            # Snapshot the cache while we hold the lock; replay outside.
            # Order matches the engine's natural emit sequence so a late
            # viewer doesn't see a stale ``track_started`` get overridden
            # by a fresher ``engine_command load`` mid-render: handshake
            # state first, then the current track header, then the active
            # deck's load command.
            replay = [
                ev
                for ev in (
                    bus.last_live_state,
                    bus.last_track_started,
                    bus.last_load_command,
                )
                if ev is not None
            ]
        for ev in replay:
            try:
                await on_event(ev)
            except Exception as exc:  # noqa: BLE001
                log.exception("live_runtime: replay on_event raised: %s", exc)
        return ViewerSubscription(_registry=self, _key=key, _subscriber=sub)

    async def _detach_viewer(
        self, key: tuple[int, str], sub: _Subscriber
    ) -> None:
        async with self._lock:
            bus = self._buses.get(key)
            if bus is None:
                return
            bus.viewers.discard(sub)
            # We don't drop the bus when viewers reach zero — the
            # primary may still be publishing and a new viewer can
            # arrive at any time. ``drop_bus`` is the explicit teardown.

    async def drop_bus(self, user_id: int, session_id: str) -> None:
        """Called by the primary WS handler on disconnect.

        Removes the bus so a fresh primary on the same session starts
        with an empty cache. Any viewers still attached will see their
        next ``publish`` go nowhere — their WS handler should also
        exit shortly when the user navigates away.
        """
        async with self._lock:
            self._buses.pop((user_id, session_id), None)


# Process-wide singleton — one per FastAPI app instance.
_registry = _Registry()


async def publish(
    user_id: int, session_id: str, event: dict[str, Any]
) -> None:
    """Public wrapper. See :meth:`_Registry.publish`."""
    await _registry.publish(user_id, session_id, event)


async def subscribe_viewer(
    user_id: int, session_id: str, on_event: OnEvent
) -> ViewerSubscription:
    """Public wrapper. See :meth:`_Registry.subscribe_viewer`."""
    return await _registry.subscribe_viewer(user_id, session_id, on_event)


async def drop_bus(user_id: int, session_id: str) -> None:
    """Public wrapper. See :meth:`_Registry.drop_bus`."""
    await _registry.drop_bus(user_id, session_id)
