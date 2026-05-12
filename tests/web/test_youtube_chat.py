"""Unit tests for the YouTube Live Chat poller (v2.7).

The real ``googleapiclient`` client is replaced by a hand-rolled fake
``_FakeYouTubeClient`` so the tests run without network access or a
Google account. The fake mirrors only the surface we touch:
``liveChatMessages().list(...).execute()`` and
``liveBroadcasts().list(...).execute()``.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake YouTube client
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, result: Any | Exception):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeLiveChatMessages:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)

    def list(self, **kwargs):
        if not self._responses:
            return _FakeRequest({"items": [], "pollingIntervalMillis": 5000})
        nxt = self._responses.pop(0)
        return _FakeRequest(nxt)


class _FakeLiveBroadcasts:
    def __init__(self, response: Any):
        self._response = response

    def list(self, **kwargs):
        return _FakeRequest(self._response)


class _FakeYouTubeClient:
    def __init__(self, chat_responses: list[Any] | None = None, broadcasts_response: Any = None):
        self._chat = _FakeLiveChatMessages(chat_responses or [])
        self._broadcasts = _FakeLiveBroadcasts(broadcasts_response or {"items": []})

    def liveChatMessages(self):
        return self._chat

    def liveBroadcasts(self):
        return self._broadcasts


def _patch_build(monkeypatch, fake_client: _FakeYouTubeClient) -> None:
    """Replace ``googleapiclient.discovery.build`` with a factory returning the fake."""
    from googleapiclient import discovery

    monkeypatch.setattr(discovery, "build", lambda *args, **kwargs: fake_client)


def _msg(text: str, author: str = "alice", author_channel_id: str = "UCalice",
         published_at: str = "2026-05-12T10:00:00Z") -> dict:
    return {
        "snippet": {
            "displayMessage": text,
            "publishedAt": published_at,
            "textMessageDetails": {"messageText": text},
        },
        "authorDetails": {
            "displayName": author,
            "channelId": author_channel_id,
        },
    }


# ---------------------------------------------------------------------------
# discover_active_broadcast
# ---------------------------------------------------------------------------


def _active_broadcast(
    bcid: str = "bcid-1",
    title: str = "Apollo Live",
    live_chat_id: str | None = "lcid-1",
    channel_id: str = "UCowner",
    lifecycle: str = "live",
) -> dict:
    """Shape a fake broadcast that matches the real YouTube response.

    Production code filters on ``status.lifeCycleStatus`` (per the v2.7.1
    fix that drops the incompatible ``broadcastStatus`` query param), so
    every test broadcast needs an explicit lifecycle value.
    """
    return {
        "id": bcid,
        "snippet": {
            "title": title,
            "liveChatId": live_chat_id,
            "channelId": channel_id,
        },
        "status": {"lifeCycleStatus": lifecycle, "privacyStatus": "public"},
        "contentDetails": {},
    }


@pytest.mark.asyncio
async def test_discover_active_broadcast_returns_first_active(monkeypatch):
    from web.backend import youtube_chat

    fake = _FakeYouTubeClient(broadcasts_response={"items": [_active_broadcast()]})
    _patch_build(monkeypatch, fake)
    res = await youtube_chat.discover_active_broadcast(creds=object())
    assert res == {
        "id": "bcid-1",
        "title": "Apollo Live",
        "live_chat_id": "lcid-1",
        "channel_id": "UCowner",
    }


@pytest.mark.asyncio
async def test_discover_active_broadcast_returns_none_when_no_active(monkeypatch):
    from web.backend import youtube_chat

    _patch_build(monkeypatch, _FakeYouTubeClient(broadcasts_response={"items": []}))
    assert await youtube_chat.discover_active_broadcast(object()) is None


@pytest.mark.asyncio
async def test_discover_active_broadcast_returns_none_when_chat_disabled(monkeypatch):
    """A broadcast with no liveChatId (chat disabled on the YT side) is
    treated as 'no broadcast available' — there's nothing to poll."""
    from web.backend import youtube_chat

    fake = _FakeYouTubeClient(broadcasts_response={
        "items": [_active_broadcast(live_chat_id=None)],
    })
    _patch_build(monkeypatch, fake)
    assert await youtube_chat.discover_active_broadcast(object()) is None


@pytest.mark.asyncio
async def test_discover_active_broadcast_skips_completed_and_ready(monkeypatch):
    """Only ``live`` / ``testing`` / ``liveStarting`` broadcasts qualify
    as currently-chattable. Completed / ready / created broadcasts must
    be filtered out (regression for v2.7.0 where status was ignored)."""
    from web.backend import youtube_chat

    fake = _FakeYouTubeClient(broadcasts_response={"items": [
        _active_broadcast(bcid="old", lifecycle="complete"),
        _active_broadcast(bcid="next", lifecycle="ready"),
        _active_broadcast(bcid="now", lifecycle="live"),
        _active_broadcast(bcid="other", lifecycle="created"),
    ]})
    _patch_build(monkeypatch, fake)
    res = await youtube_chat.discover_active_broadcast(creds=object())
    assert res is not None and res["id"] == "now"


@pytest.mark.asyncio
async def test_discover_active_broadcast_does_not_pass_broadcast_status(monkeypatch):
    """Regression for v2.7.1: YouTube's liveBroadcasts.list rejects the
    combination of ``broadcastStatus`` + ``mine=true`` with HTTP 400.
    Production code must list with ``mine=true`` ONLY and filter on
    ``status.lifeCycleStatus`` client-side. This test fails if a future
    edit re-introduces the broadcastStatus kwarg."""
    from web.backend import youtube_chat

    captured_kwargs: dict[str, Any] = {}

    class _CapturingBroadcasts(_FakeLiveBroadcasts):
        def list(self, **kwargs):
            captured_kwargs.update(kwargs)
            return super().list(**kwargs)

    fake = _FakeYouTubeClient()
    fake._broadcasts = _CapturingBroadcasts({"items": [_active_broadcast()]})
    _patch_build(monkeypatch, fake)
    await youtube_chat.discover_active_broadcast(creds=object())
    assert "broadcastStatus" not in captured_kwargs, (
        f"discover_active_broadcast must not pass broadcastStatus together "
        f"with mine=true (YouTube returns 400). Got kwargs: {captured_kwargs!r}"
    )
    assert captured_kwargs.get("mine") is True


# ---------------------------------------------------------------------------
# poll_live_chat — message delivery + filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_live_chat_delivers_each_message(monkeypatch):
    from web.backend import youtube_chat

    received: list[tuple[str, str, int]] = []
    fake = _FakeYouTubeClient(chat_responses=[
        {"items": [_msg("hello"), _msg("how are you", author="bob", author_channel_id="UCbob")],
         "pollingIntervalMillis": 50, "nextPageToken": "p1"},
    ])
    _patch_build(monkeypatch, fake)

    async def on_message(author, text, ts):
        received.append((author, text, ts))

    stop = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.1)
        stop.set()

    asyncio.create_task(stop_soon())
    await youtube_chat.poll_live_chat(
        creds=object(), live_chat_id="lcid", on_message=on_message,
        stop_event=stop,
    )
    assert len(received) == 2
    assert received[0][0] == "alice"
    assert received[0][1] == "hello"
    assert received[0][2] > 0  # timestamp parsed
    assert received[1] == ("bob", "how are you", received[1][2])


@pytest.mark.asyncio
async def test_poll_live_chat_filters_self_replies(monkeypatch):
    """Messages authored by the operator's own channel must be skipped
    so the DJ doesn't treat their own YT mod responses as audience
    requests (would create a feedback loop)."""
    from web.backend import youtube_chat

    received: list[str] = []
    fake = _FakeYouTubeClient(chat_responses=[
        {"items": [
            _msg("from operator", author="me", author_channel_id="UCowner"),
            _msg("from viewer", author="alice", author_channel_id="UCalice"),
        ], "pollingIntervalMillis": 50},
    ])
    _patch_build(monkeypatch, fake)

    async def on_message(author, text, ts):
        received.append(text)

    stop = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.1)
        stop.set()

    asyncio.create_task(stop_soon())
    await youtube_chat.poll_live_chat(
        creds=object(), live_chat_id="lcid", on_message=on_message,
        stop_event=stop, own_channel_id="UCowner",
    )
    assert received == ["from viewer"]


@pytest.mark.asyncio
async def test_poll_live_chat_skips_empty_messages(monkeypatch):
    from web.backend import youtube_chat

    received: list[str] = []
    fake = _FakeYouTubeClient(chat_responses=[
        {"items": [
            _msg(""),
            _msg("   "),
            _msg("real message"),
        ], "pollingIntervalMillis": 50},
    ])
    _patch_build(monkeypatch, fake)

    async def on_message(author, text, ts):
        received.append(text)

    stop = asyncio.Event()
    asyncio.create_task(_set_after(stop, 0.1))
    await youtube_chat.poll_live_chat(
        creds=object(), live_chat_id="lcid", on_message=on_message, stop_event=stop,
    )
    assert received == ["real message"]


@pytest.mark.asyncio
async def test_poll_live_chat_threads_page_token(monkeypatch):
    """The poller must thread ``nextPageToken`` from the previous list
    call into the next call's ``pageToken`` so we don't re-read history."""
    from web.backend import youtube_chat

    # Drop the production 1-s minimum cadence floor so two polls fit in
    # a test-sized window. The floor is a defence against a misbehaving
    # API hint that asks us to hammer; tests don't need it.
    monkeypatch.setattr(youtube_chat, "MIN_POLL_INTERVAL_SEC", 0.01)

    captured_tokens: list[Any] = []

    class _CapturingChat(_FakeLiveChatMessages):
        def list(self, **kwargs):
            captured_tokens.append(kwargs.get("pageToken"))
            return super().list(**kwargs)

    fake = _FakeYouTubeClient()
    fake._chat = _CapturingChat([
        {"items": [_msg("first")], "nextPageToken": "p1", "pollingIntervalMillis": 50},
        {"items": [_msg("second")], "nextPageToken": "p2", "pollingIntervalMillis": 50},
    ])
    _patch_build(monkeypatch, fake)

    received: list[str] = []

    async def on_message(author, text, ts):
        received.append(text)

    stop = asyncio.Event()
    asyncio.create_task(_set_after(stop, 0.5))  # let multiple polls complete
    await youtube_chat.poll_live_chat(
        creds=object(), live_chat_id="lcid", on_message=on_message, stop_event=stop,
    )
    assert captured_tokens[0] is None
    assert captured_tokens[1] == "p1"


# ---------------------------------------------------------------------------
# poll_live_chat — error handling
# ---------------------------------------------------------------------------


def _http_error(status_code: int, reason: str) -> Exception:
    """Construct a ``googleapiclient.errors.HttpError`` with a reason payload."""
    from googleapiclient.errors import HttpError
    import json

    class _Resp:
        def __init__(self, status):
            self.status = status
            # ``HttpError.__init__`` reads ``resp.reason`` during construction
            # — for the HTTP reason phrase, not the API "errors[].reason"
            # we encode in content. Use a stable HTTP phrase so the
            # constructor doesn't crash; the API reason comes from content.
            self.reason = {403: "Forbidden", 404: "Not Found", 401: "Unauthorized"}.get(
                status, "Error"
            )

    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode("utf-8")
    return HttpError(resp=_Resp(status_code), content=content)


@pytest.mark.asyncio
async def test_poll_live_chat_terminates_on_revoked_token(monkeypatch):
    from web.backend import youtube_chat

    fake = _FakeYouTubeClient(chat_responses=[_http_error(401, "authError")])
    _patch_build(monkeypatch, fake)

    status_events: list[dict] = []

    async def on_message(*a, **k):
        return None

    async def on_status(ev):
        status_events.append(ev)

    stop = asyncio.Event()
    await asyncio.wait_for(
        youtube_chat.poll_live_chat(
            creds=object(), live_chat_id="lcid",
            on_message=on_message, stop_event=stop, on_status=on_status,
        ),
        timeout=2.0,
    )
    # poller exited cleanly
    assert stop.is_set()
    assert any(e.get("state") == "disconnected" for e in status_events)


@pytest.mark.asyncio
async def test_poll_live_chat_terminates_on_ended_broadcast(monkeypatch):
    from web.backend import youtube_chat

    fake = _FakeYouTubeClient(chat_responses=[_http_error(404, "liveChatNotFound")])
    _patch_build(monkeypatch, fake)

    status_events: list[dict] = []

    async def on_message(*a, **k):
        return None

    async def on_status(ev):
        status_events.append(ev)

    stop = asyncio.Event()
    await asyncio.wait_for(
        youtube_chat.poll_live_chat(
            creds=object(), live_chat_id="lcid",
            on_message=on_message, stop_event=stop, on_status=on_status,
        ),
        timeout=2.0,
    )
    assert stop.is_set()
    assert any(
        e.get("state") == "disconnected" and "broadcast_ended" in (e.get("reason") or "")
        for e in status_events
    )


@pytest.mark.asyncio
async def test_poll_live_chat_backs_off_on_quota_exceeded(monkeypatch):
    """Quota error should call on_status({state:'quota_exceeded'}) without
    terminating the loop. We patch QUOTA_BACKOFF_SEC down to 0.05 so the
    test doesn't have to wait the full 60 s."""
    from web.backend import youtube_chat

    monkeypatch.setattr(youtube_chat, "QUOTA_BACKOFF_SEC", 0.05)

    # First poll: quota error. Second: clean response. Third: stop.
    fake = _FakeYouTubeClient(chat_responses=[
        _http_error(403, "quotaExceeded"),
        {"items": [_msg("after backoff")], "pollingIntervalMillis": 50},
    ])
    _patch_build(monkeypatch, fake)

    status_events: list[dict] = []
    received: list[str] = []

    async def on_message(author, text, ts):
        received.append(text)

    async def on_status(ev):
        status_events.append(ev)

    stop = asyncio.Event()
    asyncio.create_task(_set_after(stop, 0.5))
    await youtube_chat.poll_live_chat(
        creds=object(), live_chat_id="lcid",
        on_message=on_message, stop_event=stop, on_status=on_status,
    )
    # Quota event surfaced; subsequent poll still delivered.
    assert any(e.get("state") == "quota_exceeded" for e in status_events)
    assert "after backoff" in received


# ---------------------------------------------------------------------------
# Reason extraction
# ---------------------------------------------------------------------------


def test_reason_from_http_error_parses_content():
    from web.backend import youtube_chat

    err = _http_error(403, "quotaExceeded")
    assert youtube_chat._reason_from_http_error(err) == "quotaExceeded"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _set_after(event: asyncio.Event, delay: float) -> None:
    await asyncio.sleep(delay)
    event.set()
