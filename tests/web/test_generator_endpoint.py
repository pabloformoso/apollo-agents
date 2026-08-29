"""``GET /api/generator/health`` + the live-session VRAM guard (G0).

All HTTP toward ACE-Step is served by ``httpx.MockTransport`` (injected
through the ``generator._client`` seam), so no test can reach a real
generation box.

The guard tests exercise the REAL registry: ``ws_manager``'s connection
table, populated by the primary live WS handler. One test drives an
actual ``/ws/live/{id}`` connection to prove the guard is wired to the
handler and not to a parallel bookkeeping dict.
"""
from __future__ import annotations

import httpx
import pytest

from web.backend import acestep_client as ac
from web.backend import generator
from web.backend.ws_manager import ws_manager


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data, *, code: int = 200, error=None) -> dict:
    return {
        "data": data, "code": code, "error": error,
        "timestamp": 1700000000000, "extra": None,
    }


_STATS = {
    "queued": 2, "running": 1, "avg_job_seconds": 41.0, "queue_maxsize": 200,
}


def _install_ace(monkeypatch, responder):
    """Point ``generator._client`` at a MockTransport; return the call log."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responder(request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        generator, "_client", lambda: ac.AceStepClient(transport=transport)
    )
    return calls


def _up(request: httpx.Request) -> httpx.Response:
    """A healthy box: /health ok, /v1/stats returns queue info."""
    if request.url.path == "/health":
        return httpx.Response(200, json=_envelope({"status": "ok"}))
    if request.url.path == "/v1/stats":
        return httpx.Response(200, json=_envelope(_STATS))
    return httpx.Response(404, json=_envelope(None, code=404, error="nope"))


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


@pytest.fixture(autouse=True)
def clean_live_registry():
    """Isolate the process-wide WS registry between tests."""
    saved = dict(ws_manager._connections)
    ws_manager._connections.clear()
    yield ws_manager._connections
    ws_manager._connections.clear()
    ws_manager._connections.update(saved)


@pytest.fixture
def ace_off(monkeypatch):
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


@pytest.fixture
def ace_on(monkeypatch):
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


# ── Auth ─────────────────────────────────────────────────────────────


def test_health_requires_auth(client, ace_off):
    assert client.get("/api/generator/health").status_code == 401


def test_health_rejects_a_bad_token(client, ace_off):
    r = client.get(
        "/api/generator/health", headers={"Authorization": "Bearer garbage"}
    )
    assert r.status_code == 401


# ── The three states of the flag ─────────────────────────────────────


def test_env_unset_reports_unavailable_without_any_http(
    auth_client, ace_off, monkeypatch
):
    """The default install: no ACESTEP_BASE_URL ⇒ disabled, not an error."""
    calls = _install_ace(monkeypatch, _up)

    r = auth_client.get("/api/generator/health")

    assert r.status_code == 200
    assert r.json() == {
        "available": False, "blocked_by_live": False, "stats": None,
    }
    assert calls == []  # not a single request attempted


def test_server_down_reports_unavailable(auth_client, ace_on, monkeypatch):
    """Box off per the VRAM protocol — a normal state, still a 200."""
    calls = _install_ace(monkeypatch, _down)

    r = auth_client.get("/api/generator/health")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["stats"] is None
    # Only /health was probed; no point asking a dead box for stats.
    assert [c.url.path for c in calls] == ["/health"]


def test_server_up_reports_available_with_stats(
    auth_client, ace_on, monkeypatch
):
    calls = _install_ace(monkeypatch, _up)

    r = auth_client.get("/api/generator/health")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["blocked_by_live"] is False
    assert body["stats"] == _STATS  # passed through, envelope stripped
    assert [c.url.path for c in calls] == ["/health", "/v1/stats"]


def test_stats_failure_degrades_to_null_stats(
    auth_client, ace_on, monkeypatch
):
    """Alive but /v1/stats broken: still available, just no ETA data."""

    def half_up(request):
        if request.url.path == "/health":
            return httpx.Response(200, json=_envelope({"status": "ok"}))
        return httpx.Response(500, json=_envelope(None, code=500, error="boom"))

    _install_ace(monkeypatch, half_up)

    body = auth_client.get("/api/generator/health").json()

    assert body["available"] is True
    assert body["stats"] is None


def test_health_response_shape_is_exactly_the_contract(
    auth_client, ace_on, monkeypatch
):
    _install_ace(monkeypatch, _up)
    body = auth_client.get("/api/generator/health").json()
    assert set(body) == {"available", "blocked_by_live", "stats"}


def test_api_key_is_forwarded_when_set(
    auth_client, ace_on, monkeypatch
):
    monkeypatch.setenv(ac.ENV_API_KEY, "sk-ace-endpoint")
    calls = _install_ace(monkeypatch, _up)

    auth_client.get("/api/generator/health")

    assert all(c.headers["authorization"] == "Bearer sk-ace-endpoint" for c in calls)


def test_no_api_key_no_auth_header(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _up)
    auth_client.get("/api/generator/health")
    assert all("authorization" not in c.headers for c in calls)


# ── The VRAM guard ───────────────────────────────────────────────────


class _FakeWS:
    """Stand-in for the WebSocket object the live handler registers."""


def test_live_session_active_false_on_empty_registry(clean_live_registry):
    assert generator.live_session_active() is False


def test_live_session_active_true_when_a_live_ws_is_registered(
    clean_live_registry,
):
    clean_live_registry[("sess-1", generator.LIVE_WS_CHANNEL)] = _FakeWS()
    assert generator.live_session_active() is True


def test_live_session_active_ignores_the_planning_channel(
    clean_live_registry,
):
    """Planning WS = wizard chat, no engine, no VRAM. Must not block."""
    clean_live_registry[("sess-1", "planning")] = _FakeWS()
    assert generator.live_session_active() is False


def test_live_session_active_is_session_scoped_when_asked(
    clean_live_registry,
):
    clean_live_registry[("sess-1", generator.LIVE_WS_CHANNEL)] = _FakeWS()
    assert generator.live_session_active("sess-1") is True
    assert generator.live_session_active("sess-2") is False
    # …but the box-wide question stays True: a shared GPU does not care
    # which session is on air.
    assert generator.live_session_active() is True


def test_blocked_by_live_flips_with_the_registry(
    auth_client, ace_on, monkeypatch, clean_live_registry
):
    _install_ace(monkeypatch, _up)

    assert auth_client.get("/api/generator/health").json()["blocked_by_live"] is False

    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()
    body = auth_client.get("/api/generator/health").json()
    assert body["blocked_by_live"] is True
    assert body["available"] is True  # the box is up; it is just off-limits

    clean_live_registry.pop(("sess-live", generator.LIVE_WS_CHANNEL))
    assert auth_client.get("/api/generator/health").json()["blocked_by_live"] is False


def test_blocked_by_live_true_even_when_generator_is_off(
    auth_client, ace_off, monkeypatch, clean_live_registry
):
    """The two flags are independent signals."""
    _install_ace(monkeypatch, _up)
    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()

    body = auth_client.get("/api/generator/health").json()

    assert body == {"available": False, "blocked_by_live": True, "stats": None}


def test_ws_manager_active_sessions_reads_the_real_table(clean_live_registry):
    clean_live_registry[("a", "live")] = _FakeWS()
    clean_live_registry[("b", "live")] = _FakeWS()
    clean_live_registry[("c", "planning")] = _FakeWS()

    assert sorted(ws_manager.active_sessions("live")) == ["a", "b"]
    assert ws_manager.active_sessions("planning") == ["c"]
    assert ws_manager.active_sessions("nope") == []


def test_guard_flips_with_a_real_live_websocket(
    auth_client, auth_token, mock_pipeline, clean_live_registry
):
    """End-to-end proof the guard reads the handler's own registry.

    Not a fake entry: this opens the actual ``/ws/live/{id}`` primary
    socket the live DJ uses and checks the guard both while it is up and
    after the handler's ``finally`` has run.
    """
    from web.backend.session_store import store

    sid = auth_client.post("/api/sessions").json()["id"]
    s = store.get(sid)
    s.context_variables["playlist"] = [
        {"id": "t1", "display_name": "Track One", "bpm": 124.0,
         "camelot_key": "8A", "duration_sec": 30.0, "hot_cues": []},
        {"id": "t2", "display_name": "Track Two", "bpm": 126.0,
         "camelot_key": "9A", "duration_sec": 30.0, "hot_cues": []},
    ]
    store.save(s)

    assert generator.live_session_active() is False

    with auth_client.websocket_connect(
        f"/ws/live/{sid}?token={auth_token}"
    ) as ws:
        ws.receive_json()  # handshake frame — the handler is running
        assert generator.live_session_active() is True
        assert generator.live_session_active(sid) is True

    assert generator.live_session_active() is False
