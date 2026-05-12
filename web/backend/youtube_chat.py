"""YouTube Live Chat poller for Apollo (v2.7, read-only).

Discovers the operator's currently-active live broadcast and streams
its chat messages into a caller-supplied async callback. Designed to
run as a background asyncio task alongside the live engine WebSocket
in :mod:`web.backend.app`; each chat message becomes a synthetic
``user_msg`` that joins the existing ``audience_request_batch`` rail
in :mod:`web.backend.pipeline`. The DJ agent never knows or cares
that some audience requests came from YouTube.

API contract
------------
- :func:`discover_active_broadcast(creds)` — return ``{id, title, live_chat_id, channel_id}``
  for the operator's currently-active broadcast, or ``None`` if there
  isn't one.
- :func:`poll_live_chat(creds, live_chat_id, on_message, stop_event, own_channel_id)` —
  poll loop that exits on ``stop_event`` or terminal API error. Calls
  ``on_message(author, text, ts_ms)`` for every new message. Respects
  the API's ``pollingIntervalMillis`` hint (typically 5-15 s) and
  falls back to ``DEFAULT_POLL_INTERVAL_SEC`` when missing. On
  ``quotaExceeded`` it backs off to ``QUOTA_BACKOFF_SEC``; on revoked
  / ended-broadcast errors it sets ``stop_event`` and returns.

Both functions push their blocking ``googleapiclient`` calls through
``asyncio.to_thread`` so the WS event loop stays responsive even when
Google's API is slow.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Fallback poll cadence when the API doesn't return ``pollingIntervalMillis``.
DEFAULT_POLL_INTERVAL_SEC: float = 10.0

#: Back-off when YouTube returns ``quotaExceeded``. The default quota of
#: 10 000 units/day permits ~2000 list calls (5 units each). One stuck
#: client at 60 s polls = 60/day = harmless if accidentally left on.
QUOTA_BACKOFF_SEC: float = 60.0

#: Hard floor on poll cadence — defends against a misbehaving API hint
#: that asks us to hammer it.
MIN_POLL_INTERVAL_SEC: float = 1.0


# ---------------------------------------------------------------------------
# Broadcast discovery
# ---------------------------------------------------------------------------


async def discover_active_broadcast(creds) -> dict[str, str] | None:
    """Return the operator's currently-active broadcast, or ``None``.

    Uses ``liveBroadcasts.list(broadcastStatus="active", mine=true)``.
    If multiple broadcasts are active (rare — channel managing multiple
    simultaneous streams) we pick the first; the WS handler emits a
    warning event with the others so the operator knows.
    """
    return await asyncio.to_thread(_discover_active_broadcast_sync, creds)


def _discover_active_broadcast_sync(creds) -> dict[str, str] | None:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    try:
        resp = yt.liveBroadcasts().list(
            part="snippet,status,contentDetails",
            broadcastStatus="active",
            mine=True,
            maxResults=5,
        ).execute()
    except HttpError as exc:
        log.warning("liveBroadcasts.list failed: %s", exc)
        return None

    items = resp.get("items") or []
    if not items:
        return None
    item = items[0]
    snip = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    live_chat_id = snip.get("liveChatId") or content.get("liveChatId")
    if not live_chat_id:
        # A broadcast can be active without a chat (rare — usually
        # disabled chat on the broadcast settings). No chat = no
        # ingest, treat as "no broadcast available".
        log.info("Active broadcast %s has no liveChatId — chat disabled", item.get("id"))
        return None
    return {
        "id": item["id"],
        "title": snip.get("title", item["id"]),
        "live_chat_id": live_chat_id,
        "channel_id": snip.get("channelId", ""),
    }


# ---------------------------------------------------------------------------
# Chat polling loop
# ---------------------------------------------------------------------------


OnMessage = Callable[[str, str, int], Awaitable[None]]


async def poll_live_chat(
    creds,
    live_chat_id: str,
    on_message: OnMessage,
    stop_event: asyncio.Event,
    *,
    own_channel_id: str | None = None,
    on_status: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    """Poll the YouTube Live Chat until ``stop_event`` is set.

    Calls ``on_message(author_display_name, text, published_at_ms)``
    for each new chat message (skipping ones authored by the
    ``own_channel_id`` operator to avoid self-echo).

    Optional ``on_status`` is invoked with operational events
    (``{"state": "quota_exceeded"}``, ``{"state": "disconnected",
    "reason": "..."}``) so the caller can surface them to the
    frontend.
    """
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    next_page_token: str | None = None

    while not stop_event.is_set():
        try:
            resp = await asyncio.to_thread(
                _list_chat_messages, yt, live_chat_id, next_page_token,
            )
        except HttpError as exc:
            interval = await _handle_http_error(exc, on_status)
            if interval is None:
                # Terminal — caller should treat as disconnected.
                stop_event.set()
                return
            await _sleep_or_stop(interval, stop_event)
            continue
        except Exception as exc:  # noqa: BLE001 — defensive; networking can throw anything
            log.exception("poll_live_chat unexpected: %s", exc)
            if on_status:
                await on_status({"state": "error", "reason": str(exc)[:200]})
            await _sleep_or_stop(DEFAULT_POLL_INTERVAL_SEC, stop_event)
            continue

        for item in resp.get("items") or []:
            snip = item.get("snippet") or {}
            author = item.get("authorDetails") or {}
            if author.get("channelId") and author.get("channelId") == own_channel_id:
                # Skip self-replies so the operator doesn't see their
                # own chat moderation surface up as an audience request.
                continue
            text = snip.get("displayMessage") or snip.get("textMessageDetails", {}).get("messageText") or ""
            if not text.strip():
                continue
            ts_ms = _parse_published_at_ms(snip.get("publishedAt"))
            display_name = author.get("displayName") or "viewer"
            try:
                await on_message(display_name, text, ts_ms)
            except Exception as exc:  # noqa: BLE001 — never let a callback kill the poller
                log.exception("on_message callback raised: %s", exc)

        next_page_token = resp.get("nextPageToken") or None
        interval_ms = resp.get("pollingIntervalMillis")
        try:
            interval = max(MIN_POLL_INTERVAL_SEC, float(interval_ms) / 1000.0)
        except (TypeError, ValueError):
            interval = DEFAULT_POLL_INTERVAL_SEC
        await _sleep_or_stop(interval, stop_event)


def _list_chat_messages(yt, live_chat_id: str, page_token: str | None):
    """Synchronous wrapper used through ``asyncio.to_thread``."""
    req = yt.liveChatMessages().list(
        liveChatId=live_chat_id,
        part="snippet,authorDetails",
        pageToken=page_token,
        maxResults=200,
    )
    return req.execute()


async def _handle_http_error(exc, on_status) -> float | None:
    """Map ``HttpError`` to a back-off duration, or ``None`` for terminal.

    Returns the seconds to sleep before next attempt. ``None`` signals
    the caller should set ``stop_event`` and return — terminal errors
    are revoked tokens, ended broadcasts, or 4xx other than 403/429.
    """
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
    reason = _reason_from_http_error(exc)

    if status_code == 403 and reason == "quotaExceeded":
        log.warning("YouTube quota exceeded — backing off to %.0fs", QUOTA_BACKOFF_SEC)
        if on_status:
            await on_status({"state": "quota_exceeded"})
        return QUOTA_BACKOFF_SEC

    if status_code in (401, 403):
        # Revoked, scope missing, banned, etc. — all unrecoverable for
        # this session.
        log.info("YouTube chat poll forbidden (%s / %s) — stopping", status_code, reason)
        if on_status:
            await on_status({"state": "disconnected", "reason": reason or str(status_code)})
        return None

    if status_code == 404:
        # liveChatId no longer exists → broadcast ended.
        log.info("YouTube live chat 404 — broadcast ended")
        if on_status:
            await on_status({"state": "disconnected", "reason": "broadcast_ended"})
        return None

    # Transient (5xx, network blips). Brief back-off, then retry.
    log.warning("YouTube chat poll transient error: %s", exc)
    return DEFAULT_POLL_INTERVAL_SEC


def _reason_from_http_error(exc) -> str | None:
    """Extract the Google-API reason string (e.g. ``"quotaExceeded"``).

    HttpError stores it in ``exc.error_details`` (list of dicts) on
    newer client versions; we fall back to parsing ``exc.content``
    JSON for older versions.
    """
    details = getattr(exc, "error_details", None) or []
    for d in details:
        if isinstance(d, dict) and d.get("reason"):
            return d["reason"]
    try:
        import json
        content = getattr(exc, "content", b"")
        if content:
            payload = json.loads(content)
            errors = payload.get("error", {}).get("errors") or []
            if errors and isinstance(errors[0], dict):
                return errors[0].get("reason")
    except Exception:  # noqa: BLE001
        pass
    return None


def _parse_published_at_ms(ts: str | None) -> int:
    """Convert a YouTube ISO 8601 timestamp to epoch milliseconds.

    Best-effort: returns 0 if the value is missing or unparseable
    (callers fall back to local clock).
    """
    if not ts:
        return 0
    try:
        from datetime import datetime
        # YouTube serialises with "Z" suffix; datetime.fromisoformat handles
        # both Z and offset formats in 3.11+.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return int(datetime.fromisoformat(ts).timestamp() * 1000)
    except ValueError:
        return 0


async def _sleep_or_stop(seconds: float, stop_event: asyncio.Event) -> None:
    """Sleep for ``seconds`` or break early when ``stop_event`` is set."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return
