"""Session-scoped YouTube Live Chat poller registry (v2.7.2).

In v2.7.0 the YT poller was spawned inside ``live_session_ws`` and tied
to the lifetime of a single WebSocket connection. That meant:
- Every Chrome refresh / OBS Browser Source reconnect killed the
  poller and respawned a new one — wasteful, and operators saw a
  brief gap where YT chat wasn't being ingested.
- Two clients on the same session (Chrome /live + OBS Browser Source)
  spawned two pollers, each independently hitting the YouTube API and
  doubling quota cost.
- The poller's lifecycle was opaque — operators asked "is the backend
  even talking to YouTube right now?" with no clean way to inspect.

This module fixes those three concerns by hoisting the poller to
**session scope**. One poller per ``(user_id, session_id)``, regardless
of how many WS connections are attached. Subscribers (each WS handler)
register two callbacks — ``on_message`` and ``on_status`` — and the
poller fans events out to every active subscriber. When the last
subscriber leaves, the poller stays alive for a grace window
(``_GRACE_SEC``) so a refresh doesn't kill it; on grace expiry it
shuts down cleanly.

Public API
----------
- :class:`Subscription` — opaque handle the WS handler holds; release
  via :meth:`Subscription.detach`.
- :func:`attach` — register a WS as a subscriber to the session's
  poller. Starts the poller on first attach if YT is configured and
  the user has credentials with an active broadcast. Returns a
  :class:`Subscription` plus the current ``state`` snapshot so the
  caller can immediately emit a ``youtube_status`` frame.

Threading + lifecycle
---------------------
- All state mutations go through an ``asyncio.Lock`` so concurrent
  WS attach/detach calls don't race on the ref-counter.
- Cleanup is scheduled via ``loop.call_later`` — cheap, no extra task.
- The poller itself runs as a single ``asyncio.Task`` per session;
  its event loop must match the WS handler's loop (FastAPI's main).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import youtube_auth, youtube_chat

log = logging.getLogger(__name__)


#: How long to keep a poller alive after the last subscriber detaches.
#: Lets a Chrome refresh / OBS Browser Source reconnect re-attach
#: without paying for a fresh discover round-trip and without losing
#: the chat backlog mid-stream. Conservative — short enough that an
#: idle session doesn't burn quota forever.
_GRACE_SEC: float = 30.0

#: v3.7.1 — how often to re-probe for an active broadcast after an
#: initial ``no_broadcast``. The natural setup order (open the live
#: page → start OBS → YouTube flips the broadcast live ~30-60s later)
#: means the one-shot discovery almost always ran too early — observed
#: live 2026-07-12: a whole stream with chat ingest dead because the
#: page connected 2 minutes before the broadcast existed. Cost:
#: liveBroadcasts.list is 1 quota unit per probe — 60/hour is noise
#: against the 10k daily budget.
REDISCOVER_INTERVAL_SEC: float = float(
    os.getenv("APOLLO_YT_REDISCOVER_SEC", "60")
)


# v3.7.0 — the fourth argument is ``is_first``: True when this is the
# author's first message THIS STREAM (computed once, runtime-scoped, so
# it survives WS reconnects and OBS Browser Source refreshes instead of
# re-greeting the whole room on every refresh).
OnMessage = Callable[[str, str, int, bool], Awaitable[None]]
OnStatus = Callable[[dict[str, Any]], Awaitable[None]]


def _first_message_key(author: str) -> str:
    """Normalize an author name for seen-set membership.

    Case-insensitive + whitespace-trimmed so "Marta" and "marta " count
    as the same chatter; kept pure/module-level for direct unit tests.
    """
    return (author or "").strip().casefold()


def register_first_message(seen: set[str], author: str) -> bool:
    """Record ``author`` in ``seen``; True iff this was their first message.

    Pure set logic extracted from the poller fan-out so the greeting
    trigger is unit-testable without spinning up a poller. Unusable
    names (empty/whitespace) are never "first" — no greeting for ghosts.
    """
    key = _first_message_key(author)
    if not key or key in seen:
        return False
    seen.add(key)
    return True


@dataclass(eq=False)
class _Subscriber:
    """One WS attached to a session-scoped poller.

    ``eq=False`` keeps identity-based hashing (each WS handler creates
    its own instance) so subscribers can live in a ``set``.
    """

    on_message: OnMessage
    on_status: OnStatus


@dataclass
class _Runtime:
    """All state for one session-scoped poller."""

    user_id: int
    session_id: str
    subscribers: set[_Subscriber] = field(default_factory=set)
    poller_task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    broadcast: dict | None = None
    state: dict = field(default_factory=lambda: {"state": "disconnected", "reason": "not_connected"})
    cleanup_handle: asyncio.TimerHandle | None = None
    # v3.7.0 — authors who already sent a message this stream (keys via
    # ``_first_message_key``). Lives on the runtime so the greeting
    # trigger survives WS reconnects; a fresh stream gets a fresh set.
    seen_authors: set[str] = field(default_factory=set)


@dataclass
class Subscription:
    """Opaque handle returned by :func:`attach`. Hold until WS closes."""

    _registry: "_Registry"
    _runtime: _Runtime
    _subscriber: _Subscriber

    async def detach(self) -> None:
        await self._registry._detach(self._runtime, self._subscriber)


class _Registry:
    """Process-wide singleton holding all session-scoped runtimes."""

    def __init__(self) -> None:
        self._runtimes: dict[tuple[int, str], _Runtime] = {}
        self._lock = asyncio.Lock()

    async def attach(
        self,
        user_id: int,
        session_id: str,
        on_message: OnMessage,
        on_status: OnStatus,
    ) -> tuple[Subscription, dict]:
        """Register a subscriber and return ``(Subscription, state_snapshot)``.

        On the first attach for a session: probe credentials, discover
        the active broadcast, spawn the poller task. Subsequent
        attaches just register the new callbacks and return the
        current state snapshot (so the caller can immediately emit a
        ``youtube_status`` frame to the new WS).
        """
        sub = _Subscriber(on_message=on_message, on_status=on_status)
        async with self._lock:
            key = (user_id, session_id)
            rt = self._runtimes.get(key)
            if rt is None:
                rt = _Runtime(user_id=user_id, session_id=session_id)
                self._runtimes[key] = rt
                await self._start_poller_unlocked(rt)
            else:
                # New subscriber joining an existing poller — cancel
                # any pending teardown so we keep running.
                if rt.cleanup_handle is not None:
                    rt.cleanup_handle.cancel()
                    rt.cleanup_handle = None
            rt.subscribers.add(sub)
            state_snapshot = dict(rt.state)
        return Subscription(_registry=self, _runtime=rt, _subscriber=sub), state_snapshot

    async def _detach(self, rt: _Runtime, sub: _Subscriber) -> None:
        async with self._lock:
            rt.subscribers.discard(sub)
            if rt.subscribers:
                return
            # Last subscriber left — schedule cleanup after grace.
            # If a new subscriber attaches within _GRACE_SEC, attach()
            # cancels this handle.
            loop = asyncio.get_running_loop()
            rt.cleanup_handle = loop.call_later(
                _GRACE_SEC,
                lambda: asyncio.create_task(self._teardown(rt)),
            )

    async def _teardown(self, rt: _Runtime) -> None:
        async with self._lock:
            if rt.subscribers:
                # A subscriber rejoined during the grace; abort teardown.
                return
            key = (rt.user_id, rt.session_id)
            existing = self._runtimes.get(key)
            if existing is not rt:
                # Already replaced or torn down.
                return
            self._runtimes.pop(key, None)
            rt.stop_event.set()
            task = rt.poller_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        log.info(
            "youtube_runtime: torn down session=%s user=%s after grace",
            rt.session_id, rt.user_id,
        )

    async def _start_poller_unlocked(self, rt: _Runtime) -> None:
        """First-attach path: probe creds + discover + spawn poller.

        Called inside ``self._lock`` so the runtime state is consistent
        for any subscriber that lands right after we kick off the
        background task.
        """
        # Diagnostic — prints in backend.log so we can confirm WHICH
        # branch the runtime lands on when a session attaches. Removed
        # once the poller plumbing stabilises across restarts.
        print(
            f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] start: "
            f"enabled={youtube_auth.enabled()}",
            flush=True,
        )
        if not youtube_auth.enabled():
            # Feature disabled server-side. Subscribers see no events;
            # the runtime exists only to avoid re-probing on each
            # attach for the same session.
            rt.state = {"state": "off"}
            print(
                f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] state=off (disabled)",
                flush=True,
            )
            return
        try:
            creds = youtube_auth.get_credentials(rt.user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "youtube_runtime: get_credentials failed for user=%s: %s",
                rt.user_id, exc,
            )
            creds = None
        if creds is None:
            rt.state = {"state": "disconnected", "reason": "not_connected"}
            print(
                f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] state=disconnected (no creds)",
                flush=True,
            )
            return

        try:
            broadcast = await youtube_chat.discover_active_broadcast(creds)
        except Exception as exc:  # noqa: BLE001
            log.warning("youtube_runtime: discover failed: %s", exc)
            broadcast = None

        if broadcast is None:
            rt.state = {"state": "no_broadcast"}
            print(
                f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] "
                f"state=no_broadcast — re-probing every "
                f"{REDISCOVER_INTERVAL_SEC:.0f}s",
                flush=True,
            )
            # v3.7.1 — don't give up. Keep re-probing while subscribers
            # are attached; the moment the broadcast goes live, connect
            # the poller and push the state flip to every WS. Tracked as
            # ``poller_task`` so the normal teardown path cancels it.
            rt.poller_task = asyncio.create_task(
                self._rediscover_loop(rt, creds),
                name=f"yt-rediscover-{rt.session_id[:8]}",
            )
            return

        rt.broadcast = broadcast
        rt.state = {
            "state": "connected",
            "broadcast": {"id": broadcast["id"], "title": broadcast["title"]},
        }
        rt.poller_task = asyncio.create_task(
            self._run_poller(rt, creds),
            name=f"yt-poller-{rt.session_id[:8]}",
        )
        print(
            f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] state=connected, "
            f"poller_task spawned (broadcast={broadcast['id']})",
            flush=True,
        )

    async def _rediscover_loop(self, rt: _Runtime, creds) -> None:
        """Re-probe for an active broadcast until one appears (v3.7.1).

        Runs as the runtime's ``poller_task`` while in ``no_broadcast``:
        every ``REDISCOVER_INTERVAL_SEC`` it asks YouTube again, and on
        success flips the state, notifies every attached WS (the UI
        pill goes green without a refresh), and hands the task over to
        the normal poller loop. Probes are skipped while no subscribers
        are attached (grace window) so an abandoned session doesn't
        burn quota.
        """
        try:
            while not rt.stop_event.is_set():
                await asyncio.sleep(REDISCOVER_INTERVAL_SEC)
                if rt.stop_event.is_set():
                    return
                if not rt.subscribers:
                    continue
                try:
                    broadcast = await youtube_chat.discover_active_broadcast(creds)
                except Exception as exc:  # noqa: BLE001 — transient API errors must not kill the loop
                    log.warning("youtube_runtime: rediscover probe failed: %s", exc)
                    continue
                if broadcast is None:
                    continue
                rt.broadcast = broadcast
                rt.state = {
                    "state": "connected",
                    "broadcast": {"id": broadcast["id"], "title": broadcast["title"]},
                }
                print(
                    f"[yt-runtime u={rt.user_id} s={rt.session_id[:8]}] "
                    f"rediscovered broadcast={broadcast['id']} — starting poller",
                    flush=True,
                )
                for sub in list(rt.subscribers):
                    try:
                        await sub.on_status(dict(rt.state))
                    except Exception as exc:  # noqa: BLE001
                        log.exception(
                            "youtube_runtime: on_status raised during rediscovery: %s",
                            exc,
                        )
                # Same task becomes the poller wrapper — teardown keeps
                # cancelling ``poller_task`` exactly as before.
                await self._run_poller(rt, creds)
                return
        except asyncio.CancelledError:
            raise

    async def _run_poller(self, rt: _Runtime, creds) -> None:
        """Wrapper around :func:`youtube_chat.poll_live_chat` that fans
        events out to every current subscriber.

        Catches exceptions so a transient failure inside the poller
        doesn't propagate as an unhandled task exception (which would
        be silent without an explicit task supervisor).
        """
        broadcast = rt.broadcast or {}

        async def _fan_message(author: str, text: str, ts_ms: int) -> None:
            # v3.7.0 — first-message detection happens HERE, once per
            # message, before the fan-out: computing it per-subscriber
            # would greet the same chatter once per attached WS.
            is_first = register_first_message(rt.seen_authors, author)
            # Copy the subscriber set so a concurrent detach doesn't
            # mutate it while we iterate.
            for sub in list(rt.subscribers):
                try:
                    await sub.on_message(author, text, ts_ms, is_first)
                except Exception as exc:  # noqa: BLE001 — one bad subscriber shouldn't bring down the poller
                    log.exception("youtube_runtime: subscriber on_message raised: %s", exc)

        async def _fan_status(payload: dict) -> None:
            # Update the runtime's last-known state so future attaches
            # see the latest snapshot even if they joined post-event.
            rt.state = {**payload}
            for sub in list(rt.subscribers):
                try:
                    await sub.on_status(payload)
                except Exception as exc:  # noqa: BLE001
                    log.exception("youtube_runtime: subscriber on_status raised: %s", exc)

        try:
            await youtube_chat.poll_live_chat(
                creds,
                broadcast.get("live_chat_id", ""),
                _fan_message,
                rt.stop_event,
                own_channel_id=broadcast.get("channel_id") or None,
                on_status=_fan_status,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("youtube_runtime: poller crashed: %s", exc)
            rt.state = {"state": "error", "reason": str(exc)[:200]}


# Process-wide singleton — one per FastAPI app instance.
_registry = _Registry()


async def attach(
    user_id: int,
    session_id: str,
    on_message: OnMessage,
    on_status: OnStatus,
) -> tuple[Subscription, dict]:
    """Public wrapper. See :meth:`_Registry.attach`."""
    return await _registry.attach(user_id, session_id, on_message, on_status)


async def snapshot(user_id: int, session_id: str) -> dict | None:
    """Read-only peek at the current runtime state, for diagnostics.

    Returns ``None`` if no runtime exists for the (user, session)
    tuple yet (i.e. nobody has attached). Useful from a debug endpoint
    or a healthcheck — doesn't affect ref counts.
    """
    rt = _registry._runtimes.get((user_id, session_id))
    return dict(rt.state) if rt else None
