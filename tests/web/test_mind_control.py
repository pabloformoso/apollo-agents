"""Mind service safety: fake host only, no real service or model touched.

The Mind owns no model any more — it thinks with the main LLM
(``main_llm``), so what is pinned here is the service half (start/stop,
port ownership, in-flight protection) and that inference always names
the main LLM and is only forwarded when that model is resident.
"""
import asyncio
from unittest.mock import AsyncMock
import httpx

import pytest
from fastapi import HTTPException

from web.backend import mind_supervisor as mind, mind_control as control, ace_supervisor as ace, auth, main_llm, permissions


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(mind, "_task", None)
    monkeypatch.setattr(mind, "_uncertain", False)
    monkeypatch.setattr(mind, "_operation", None)
    monkeypatch.setattr(mind, "_error", None)
    monkeypatch.setattr(ace, "_lock", asyncio.Lock())


def _admin_token():
    return auth.create_access_token({"sub": "1", "caps": sorted(permissions.capabilities_for({permissions.ADMIN_ROLE}))})


# ─── the Apollo gateway ────────────────────────────────────────────────

def test_gateway_auth_and_admin(client, auth_client, monkeypatch):
    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(control, "host", upstream)
    client.headers.clear()
    assert client.get("/api/mind").status_code == 401
    assert client.post("/api/mind/actions/start").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "1", "caps": []})
    assert client.post("/api/mind/actions/start").status_code == 403
    upstream.assert_not_awaited()
    client.headers["Authorization"] = "Bearer " + _admin_token()
    assert client.post("/api/mind/actions/start").status_code == 200
    upstream.assert_awaited_once_with("/actions/start", "POST")


def test_the_gateway_has_no_model_actions_or_settings(client, auth_client, monkeypatch):
    """Residency belongs to /api/main-llm; the old Mind routes are gone, not aliased."""
    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(control, "host", upstream)
    client.headers["Authorization"] = "Bearer " + _admin_token()
    assert client.post("/api/mind/actions/load").status_code == 404
    assert client.post("/api/mind/actions/unload").status_code == 404
    assert client.put("/api/mind/settings", json={"model_key": "x"}).status_code in {404, 405}
    upstream.assert_not_awaited()


def test_status_names_the_main_llm(client, auth_client, monkeypatch):
    monkeypatch.setattr(control, "host", AsyncMock(return_value={"service": "active", "busy": False}))
    main_llm.save_settings(main_llm.Settings(model_key="chosen-model"))
    client.headers["Authorization"] = "Bearer " + _admin_token()
    body = client.get("/api/mind").json()
    assert body["main_llm"] == "chosen-model"
    assert body["can_manage"] is True


def test_infer_publishes_and_forwards_the_main_llm(client, auth_client, monkeypatch):
    upstream = AsyncMock(return_value={"code": "stack()"})
    monkeypatch.setattr(control, "host", upstream)
    main_llm.save_settings(main_llm.Settings(model_key="chosen-model"))
    client.headers["Authorization"] = "Bearer " + _admin_token()

    assert client.get("/api/mind/infer").json() == {"models": ["chosen-model"], "default": "chosen-model"}

    assert client.post("/api/mind/infer", json={"intent": "darker"}).status_code == 200
    upstream.assert_awaited_once_with("/infer", "POST", {"intent": "darker", "model": "chosen-model"})

    # Naming the same model is fine; naming another is a contract break.
    assert client.post("/api/mind/infer", json={"intent": "d", "model": "chosen-model"}).status_code == 200
    assert client.post("/api/mind/infer", json={"intent": "d", "model": "some-other"}).status_code == 422
    assert upstream.await_count == 2


def test_inference_pending_reads_the_host_and_degrades_to_false(monkeypatch):
    monkeypatch.delenv("ACESTEP_CONTROL_URL", raising=False)
    assert asyncio.run(control.inference_pending()) is False

    monkeypatch.setenv("ACESTEP_CONTROL_URL", "http://gpu:8010")
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "x" * 32)
    monkeypatch.setattr(control, "host", AsyncMock(return_value={"busy": True, "uncertain": False}))
    assert asyncio.run(control.inference_pending()) is True
    monkeypatch.setattr(control, "host", AsyncMock(return_value={"busy": False, "uncertain": True}))
    assert asyncio.run(control.inference_pending()) is True
    monkeypatch.setattr(control, "host", AsyncMock(return_value={"busy": False, "uncertain": False}))
    assert asyncio.run(control.inference_pending()) is False
    monkeypatch.setattr(control, "host", AsyncMock(side_effect=HTTPException(503, "down")))
    assert asyncio.run(control.inference_pending()) is False


# ─── the host supervisor ───────────────────────────────────────────────

LOADED = [{"identifier": "google/gemma-4-e4b", "modelKey": "google/gemma-4-e4b"}]


def test_is_loaded_matches_key_or_identifier():
    assert mind.is_loaded(LOADED, "google/gemma-4-e4b")
    assert mind.is_loaded([{"identifier": "alias", "modelKey": "k"}], "alias")
    assert not mind.is_loaded(LOADED, "qwen/qwen3.6-27b")
    assert not mind.is_loaded([], "google/gemma-4-e4b")


def test_loaded_models_only_trusts_a_well_formed_listing(monkeypatch):
    monkeypatch.setattr(mind, "command", AsyncMock(return_value='[{"identifier": "a", "modelKey": "a"}]'))
    assert asyncio.run(mind.loaded_models()) == [{"identifier": "a", "modelKey": "a"}]
    monkeypatch.setattr(mind, "command", AsyncMock(return_value='{"not": "a list"}'))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.loaded_models())
    assert exc.value.status_code == 503


def test_status_reports_service_and_resident_models(monkeypatch):
    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(200, json={"models": [], "default": None})
    monkeypatch.setattr(mind.httpx, "AsyncClient", lambda **kwargs: client)
    body = asyncio.run(mind.status())
    assert body["service"] == "active" and body["reachable"] is True
    assert body["loaded_models"] == ["google/gemma-4-e4b"]
    assert body["busy"] is False and body["uncertain"] is False
    assert "settings" not in body and "model_loaded" not in body


def test_infer_requires_the_named_model_to_be_resident(monkeypatch):
    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=[]))
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.infer({"intent": "d", "model": "google/gemma-4-e4b"}))
    assert exc.value.status_code == 409 and "Load the main LLM" in exc.value.detail
    assert mind._task is None


def test_infer_requires_a_model_name(monkeypatch):
    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
    for payload in ({"intent": "d"}, {"intent": "d", "model": ""}, {"intent": "d", "model": 3}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(mind.infer(payload))
        assert exc.value.status_code == 422


def test_infer_requires_the_service_to_be_active(monkeypatch):
    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="inactive"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.infer({"intent": "d", "model": "google/gemma-4-e4b"}))
    assert exc.value.status_code == 409 and "Start the Mind service" in exc.value.detail


def test_infer_forwards_the_model_it_was_given(monkeypatch):
    forwarded = []

    async def capture(payload):
        forwarded.append(payload)
        return {}

    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
    monkeypatch.setattr(mind, "infer_request", capture)
    asyncio.run(mind.infer({"intent": "d", "model": "google/gemma-4-e4b"}))
    assert forwarded == [{"intent": "d", "model": "google/gemma-4-e4b"}]


def test_only_service_actions_exist(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ACESTEP_CONTROL_TOKEN", "t" * 32)
    client = TestClient(ace.app, headers={"Authorization": "Bearer " + "t" * 32})
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="inactive"))
    assert client.post("/v1/mind/actions/load").status_code == 422
    assert client.post("/v1/mind/actions/unload").status_code == 422


def test_start_refuses_an_unmanaged_process_on_the_port(monkeypatch):
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="inactive"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(200, json={"models": []})
    monkeypatch.setattr(mind.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.action("start"))
    assert exc.value.status_code == 409 and "unmanaged" in exc.value.detail


def test_stop_is_refused_while_an_answer_is_in_flight(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def inference(payload):
            entered.set()
            await release.wait()
            return {}

        monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
        monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
        monkeypatch.setattr(mind, "infer_request", inference)
        caller = asyncio.create_task(mind.infer({"intent": "continue", "model": "google/gemma-4-e4b"}))
        await entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert mind.busy()
        with pytest.raises(HTTPException) as exc:
            await mind.action("stop")
        assert exc.value.status_code == 409
        release.set()
        await mind._task
        assert not mind.busy()
    asyncio.run(scenario())


def test_inference_transport_timeout_is_uncertain(monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.side_effect = httpx.ReadTimeout("late")
    monkeypatch.setattr(mind.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(mind.infer_request({}))
    assert mind._uncertain
    with pytest.raises(HTTPException):
        mind.ensure_idle()


def test_start_and_infer_stay_refused_while_uncertain(monkeypatch):
    monkeypatch.setattr(mind, "_uncertain", True)
    monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
    monkeypatch.setattr(mind, "loaded_models", AsyncMock(return_value=LOADED))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.action("start"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.infer({"intent": "continue", "model": "google/gemma-4-e4b"}))
    assert exc.value.status_code == 409


def test_stop_clears_an_uncertain_transport(monkeypatch):
    """Stopping the unit kills the process that might still be answering: the one
    action that can resolve an unresolved transport, so it must not be refused by it."""
    async def scenario():
        monkeypatch.setattr(mind, "_uncertain", True)
        monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
        command = AsyncMock(return_value="")
        monkeypatch.setattr(mind, "command", command)
        assert await mind.action("stop") == {"accepted": True}
        await mind._task
        assert not mind._uncertain
        assert mind._error is None
        assert command.await_args.args[:3] == ("/usr/bin/systemctl", "--user", "stop")
    asyncio.run(scenario())


def test_a_failed_stop_leaves_the_transport_unresolved(monkeypatch):
    async def scenario():
        monkeypatch.setattr(mind, "_uncertain", True)
        monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
        monkeypatch.setattr(mind, "command", AsyncMock(side_effect=HTTPException(503, "no systemctl")))
        await mind.action("stop")
        await mind._task
        assert mind._uncertain
        assert mind._error == "no systemctl"
    asyncio.run(scenario())


def test_ace_admission_refuses_while_any_model_is_resident(monkeypatch):
    """The GPU protocol is symmetric and has no shared-GPU opt-out any more."""
    client = AsyncMock()
    client.__aenter__.return_value = client
    request = httpx.Request("GET", "http://127.0.0.1:1234/api/v0/models")
    client.get.return_value = httpx.Response(200, json={"data": [{"id": "a", "state": "loaded"}]}, request=request)
    monkeypatch.setattr(ace.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ace.llm_idle())
    assert exc.value.status_code == 409 and "main LLM" in exc.value.detail

    client.get.return_value = httpx.Response(200, json={"data": [{"id": "a", "state": "not-loaded"}]}, request=request)
    asyncio.run(ace.llm_idle())
