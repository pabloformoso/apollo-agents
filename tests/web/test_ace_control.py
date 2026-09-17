"""S0 lifecycle, admission, and supervisor tests; no host commands or GPU."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from web.backend import ace_control as control, ace_supervisor as supervisor, auth, db, generator, permissions
from web.backend.ace_control_contract import ServiceState, queue_counts
from web.backend.app import app


@pytest.fixture
def operator(auth_client):
    token = auth.create_access_token({"sub": "1", "caps": sorted(permissions.capabilities_for({permissions.ADMIN_ROLE}))})
    auth_client.headers["Authorization"] = f"Bearer {token}"
    auth_client.auth_token = token
    return auth_client


@pytest.fixture
def managed(monkeypatch, operator):
    monkeypatch.setenv("ACESTEP_CONTROL_URL", "http://controller.test")
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "s" * 40)
    monkeypatch.setattr(generator, "live_session_active", lambda: False)
    upstream = AsyncMock(return_value=ServiceState(state="stopped"))
    monkeypatch.setattr(control, "controller", upstream)
    return upstream


def test_status_requires_auth(client):
    assert client.get("/api/generator/service").status_code == 401
    assert client.post("/api/generator/service/start").status_code == 401


def test_unconfigured_status_is_honest(auth_client):
    body = auth_client.get("/api/generator/service").json()
    assert body["configured"] is False
    assert body["ready"] is False
    assert body["state"] == "unknown"


def test_lifecycle_admin_and_explicit_actions(auth_client, managed):
    assert auth_client.post("/api/generator/service/start").status_code == 200
    managed.assert_awaited_once_with("start")
    assert auth_client.post("/api/generator/service/restart").status_code == 404


@pytest.mark.parametrize("roles", [set(), {"apollo-publisher"}, {"apollo-broadcaster"}])
def test_only_admin_controls_service(auth_client, managed, roles):
    app.dependency_overrides[auth.get_current_user] = lambda: {
        "id": 1, "capabilities": permissions.capabilities_for(roles),
    }
    try:
        assert auth_client.get("/api/generator/service").json()["can_manage"] is False
        assert auth_client.post("/api/generator/service/start").status_code == 403
        assert auth_client.post("/api/generator/service/stop").status_code == 403
        assert all(call.args == () for call in managed.await_args_list)
    finally:
        app.dependency_overrides.pop(auth.get_current_user)
    assert permissions.MANAGE_GENERATOR in permissions.capabilities_for({permissions.ADMIN_ROLE})


def test_controller_outage_is_not_stopped(auth_client, managed):
    managed.side_effect = HTTPException(503, "Controller unavailable")
    status = auth_client.get("/api/generator/service").json()
    assert not status["reachable"]
    assert status["state"] == "unknown"
    assert auth_client.post("/api/generator/service/start").status_code == 503


def test_live_blocks_both_commands(auth_client, managed, monkeypatch):
    monkeypatch.setattr(generator, "live_session_active", lambda: True)
    for action in ("start", "stop"):
        assert auth_client.post(f"/api/generator/service/{action}").status_code == 409
    managed.assert_not_awaited()


def test_results_must_survive_before_stop(auth_client, managed):
    with db._conn() as c:
        c.execute("INSERT INTO generations VALUES (?, ?, ?, ?, ?)", ("task", 1, "now", "pending", "{}"))
    assert auth_client.get("/api/generator/service").json()["pending_results"] == 1
    managed.reset_mock()
    assert auth_client.post("/api/generator/service/stop").status_code == 409
    managed.assert_not_awaited()
    db.set_generation_status("task", 1, "done")
    assert auth_client.post("/api/generator/service/stop").status_code == 200


@pytest.mark.parametrize("path,body", [
    ("tasks", {"prompt": "ambient", "genre_folder": "healing"}),
    ("edit", {"file": "/tmp/take.wav", "mode": "cover"}),
])
def test_generation_and_edits_pass_admission(auth_client, managed, path, body):
    managed.side_effect = HTTPException(409, "LLM holds the GPU")
    response = auth_client.post(f"/api/generator/{path}", json=body)
    assert response.status_code == 409
    assert response.json()["detail"] == "LLM holds the GPU"
    managed.assert_awaited_once_with("check")


async def test_live_admission_refuses_running_or_unknown(managed):
    for state in ("running", "starting", "stopping", "unknown", "unresponsive"):
        managed.return_value = ServiceState(state=state)
        with pytest.raises(HTTPException):
            async with control.live_admission():
                pytest.fail("Live cannot register while ACE is active or unknown")
    managed.return_value = ServiceState(state="stopped")
    async with control.live_admission():
        assert control.gate().locked()


async def test_stop_waits_for_submission_and_its_record(managed, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    pending = 0
    monkeypatch.setattr(control, "pending_results", lambda: pending)

    async def submit():
        nonlocal pending
        dependency = control.generation_access({"id": 1})
        await anext(dependency)
        entered.set()
        await release.wait()
        pending = 1
        await dependency.aclose()

    task = asyncio.create_task(submit())
    await entered.wait()
    stopping = asyncio.create_task(control.service_action("stop", {
        "id": 1, "capabilities": {permissions.MANAGE_GENERATOR},
    }))
    await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    await task
    with pytest.raises(HTTPException) as caught:
        await stopping
    assert caught.value.status_code == 409
    assert not any(call.args == ("stop",) for call in managed.await_args_list)


@pytest.mark.parametrize("stats,expected", [
    ({"jobs": {"queued": 0, "running": 1}, "queue_size": 2}, (2, 1)),
    ({"queued": 0, "running": 0}, (0, 0)),
    ({}, None), ({"jobs": {"running": 0}, "queue_size": 0}, None),
    ({"queued": False, "running": 0}, None),
    ({"queued": "0", "running": 0}, None),
    ({"queued": -1, "running": 0}, None),
])
def test_queue_schema(stats, expected):
    assert queue_counts(stats) == expected


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "s" * 40)
    monkeypatch.setattr(supervisor, "_lock", asyncio.Lock())
    monkeypatch.setattr(supervisor, "llm_idle", AsyncMock())
    monkeypatch.setattr(supervisor, "ace_json", AsyncMock(side_effect=httpx.ConnectError("off")))
    monkeypatch.setattr(supervisor, "systemctl", AsyncMock(return_value="LoadState=loaded\nActiveState=inactive"))
    client = TestClient(supervisor.app)
    client.headers["Authorization"] = "Bearer " + "s" * 40
    return client


def test_host_auth_fails_closed(host, monkeypatch):
    host.headers.clear()
    assert host.get("/v1/service").status_code == 401
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "short")
    assert host.post("/v1/service/start").status_code == 503
    supervisor.systemctl.assert_not_awaited()


def test_host_start_and_idempotency(host, monkeypatch):
    assert host.post("/v1/service/start").json()["state"] == "starting"
    assert supervisor.systemctl.await_args.args == ("start",)
    monkeypatch.setattr(supervisor, "observe", AsyncMock(return_value=ServiceState(state="starting")))
    supervisor.systemctl.reset_mock()
    assert host.post("/v1/service/start").status_code == 200
    supervisor.systemctl.assert_not_awaited()
    assert host.post("/v1/service/arbitrary-command").status_code == 404


@pytest.mark.parametrize("state,queued,running,expected", [
    ("running", 0, 0, 200), ("running", 1, 0, 409),
    ("running", 0, 1, 409), ("running", None, None, 409),
    ("unknown", None, None, 409), ("unresponsive", None, None, 409),
    ("stopped", None, None, 200),
])
def test_host_stop_refuses_unknown_or_busy(host, monkeypatch, state, queued, running, expected):
    monkeypatch.setattr(supervisor, "observe", AsyncMock(return_value=ServiceState(
        state=state, queued=queued, running=running,
    )))
    assert host.post("/v1/service/stop").status_code == expected
    if expected == 409 or state == "stopped":
        supervisor.systemctl.assert_not_awaited()
    else:
        supervisor.systemctl.assert_awaited_once_with("stop")


async def test_observe_reads_real_stats_and_lm_residency(monkeypatch):
    monkeypatch.setattr(supervisor, "systemctl", AsyncMock(return_value="LoadState=loaded\nActiveState=active"))
    monkeypatch.setattr(supervisor, "ace_json", AsyncMock(side_effect=[
        {"status": "ok", "models_initialized": False, "llm_initialized": True},
        {"jobs": {"queued": 2, "running": 1}, "queue_size": 2},
    ]))
    state = await supervisor.observe()
    assert state.ready and state.loaded
    assert (state.queued, state.running) == (2, 1)
    supervisor.ace_json.side_effect = httpx.ConnectError("offline")
    assert (await supervisor.observe()).state == "unresponsive"


@pytest.mark.parametrize("response", [
    {"data": [{"state": "loaded"}]}, {"data": [{}]}, {"data": None}, {},
])
async def test_llm_probe_never_assumes_idle(monkeypatch, response):
    original = httpx.AsyncClient
    monkeypatch.setattr(supervisor.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)), **kwargs,
    ))
    with pytest.raises(HTTPException) as caught:
        await supervisor.llm_idle()
    assert caught.value.status_code == 409


async def test_llm_idle_and_controller_wire_contract(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"state": "not-loaded"}]})
        return httpx.Response(200, json=ServiceState(state="starting").model_dump())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    await supervisor.llm_idle()
    monkeypatch.setenv("ACESTEP_CONTROL_URL", "http://controller.test")
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "s" * 40)
    assert (await control.controller("start")).state == "starting"
    assert requests[-1].url.path == "/v1/service/start"
    assert requests[-1].headers["Authorization"] == "Bearer " + "s" * 40


@pytest.mark.parametrize("body", [{}, {"state": "invented"}, {"state": "running", "queued": -1}])
async def test_bad_controller_response_is_unavailable(monkeypatch, body):
    original = httpx.AsyncClient
    monkeypatch.setenv("ACESTEP_CONTROL_URL", "http://controller.test")
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "s" * 40)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)), **kwargs,
    ))
    with pytest.raises(HTTPException) as caught:
        await control.controller()
    assert caught.value.status_code == 503


async def test_unmanaged_process_is_not_reported_stopped(monkeypatch):
    monkeypatch.setattr(supervisor, "systemctl", AsyncMock(return_value="LoadState=loaded\nActiveState=inactive"))
    monkeypatch.setattr(supervisor, "ace_json", AsyncMock(return_value={"status": "ok"}))
    state = await supervisor.observe()
    assert state.state == "unknown"
    assert "outside the managed service" in state.reason


def test_live_ws_reports_ace_conflict_without_registering(auth_client, auth_token, mock_pipeline, managed):
    from tests.web.test_live_ws import _seed_playlist
    from web.backend.ws_manager import ws_manager
    from starlette.websockets import WebSocketDisconnect

    managed.return_value = ServiceState(state="running", ready=True)
    sid = auth_client.post("/api/sessions").json()["id"]
    _seed_playlist(auth_client, sid)
    with auth_client.websocket_connect(f"/ws/live/{sid}?token={auth_token}") as ws:
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "Stop ACE" in error["message"]
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 4002
    assert not ws_manager.active_sessions(channel="live")


async def test_systemctl_uses_only_fixed_argv(monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"active\n", b"")))
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", spawn)
    assert await supervisor.systemctl("start") == "active"
    assert spawn.await_args.args == ("/usr/bin/systemctl", "--user", "start", "apollo-acestep.service")
    process.returncode = 1
    with pytest.raises(HTTPException) as caught:
        await supervisor.systemctl("stop")
    assert caught.value.status_code == 503


async def test_systemctl_reaps_timed_out_child(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    process = SimpleNamespace(returncode=None, communicate=AsyncMock(return_value=(b"", b"")), kill=Mock())
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))

    async def timeout(awaitable, seconds):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(supervisor.asyncio, "wait_for", timeout)
    with pytest.raises(TimeoutError):
        await supervisor.systemctl("stop")
    process.kill.assert_called_once()
    process.communicate.assert_awaited_once()


@pytest.mark.parametrize("body", [{"code": 500, "data": {}}, [], {"data": []}])
async def test_ace_probe_rejects_malformed_envelopes(monkeypatch, body):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)), **kwargs,
    ))
    with pytest.raises(ValueError):
        await supervisor.ace_json("/v1/stats")


async def test_ace_probe_unwraps_and_authenticates(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setenv("ACESTEP_API_KEY", "ace-test-key")

    def respond(request):
        assert request.headers["Authorization"] == "Bearer ace-test-key"
        return httpx.Response(200, json={"code": 200, "data": {"status": "ok"}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    assert await supervisor.ace_json("/health") == {"status": "ok"}


def test_partial_controller_configuration_cannot_fall_back(operator, monkeypatch):
    monkeypatch.setenv("ACESTEP_CONTROL_URL", "http://controller.test")
    monkeypatch.delenv("ACESTEP_CONTROL_TOKEN", raising=False)
    assert operator.post("/api/generator/service/start").status_code == 503
    response = operator.post("/api/generator/tasks", json={"prompt": "ambient", "genre_folder": "healing"})
    assert response.status_code == 503


def test_local_registration_does_not_grant_host_control(auth_client):
    assert auth_client.get("/api/generator/service").json()["can_manage"] is False
    assert auth_client.post("/api/generator/service/start").status_code == 403
