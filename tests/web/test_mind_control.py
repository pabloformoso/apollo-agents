"""Mind lifecycle safety: fake host only, no real model loads."""
import asyncio
from unittest.mock import AsyncMock
import httpx

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from web.backend import mind_supervisor as mind, mind_control as control, ace_supervisor as ace, auth, permissions
from web.backend.ace_control_contract import ServiceState


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLLO_MIND_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(mind, "_task", None)
    monkeypatch.setattr(mind, "_uncertain", False)
    monkeypatch.setattr(mind, "_operation", None)
    monkeypatch.setattr(mind, "_error", None)
    monkeypatch.setattr(ace, "_lock", asyncio.Lock())


def test_settings_roundtrip():
    settings = mind.Settings(gpu_fraction=0.0, allow_shared_gpu=True)
    mind.save_settings(settings)
    assert mind.read_settings() == settings
    assert mind.settings_path().stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", [{"gpu_fraction": 2}, {"context_length": 0}, {"model_key": ""}, {"command": "anything"}])
def test_invalid_settings(value):
    with pytest.raises(ValidationError):
        mind.Settings(**value)


def test_unreadable_settings_fail_closed():
    mind.settings_path().write_text("not json")
    with pytest.raises(HTTPException) as exc:
        mind.read_settings()
    assert exc.value.status_code == 503


def test_gateway_auth_and_admin(client, auth_client, monkeypatch):
    upstream = AsyncMock(return_value={})
    monkeypatch.setattr(control, "host", upstream)
    client.headers.clear()
    assert client.get("/api/mind").status_code == 401
    assert client.post("/api/mind/actions/start").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "1", "caps": []})
    assert client.post("/api/mind/actions/start").status_code == 403
    assert client.put("/api/mind/settings", json={}).status_code == 403
    upstream.assert_not_awaited()
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "1", "caps": sorted(permissions.capabilities_for({permissions.ADMIN_ROLE}))})
    assert client.post("/api/mind/actions/start").status_code == 200
    upstream.assert_awaited_once_with("/actions/start", "POST")


def test_only_installed_models(monkeypatch):
    monkeypatch.setattr(mind, "inventory", AsyncMock(return_value=([], [])))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.configure(mind.Settings(model_key="--evil")))
    assert exc.value.status_code == 422


def test_unload_only_reserved_alias(monkeypatch):
    command = AsyncMock()
    monkeypatch.setattr(mind, "command", command)
    asyncio.run(mind.perform("unload", mind.Settings()))
    command.assert_awaited_once_with(mind.lms(), "unload", "apollo-mind", timeout=30)


def test_load_fixed_argv(monkeypatch):
    command = AsyncMock()
    monkeypatch.setattr(mind, "command", command)
    asyncio.run(mind.perform("load", mind.Settings()))
    args = command.call_args.args
    assert args[:3] == (mind.lms(), "load", "google/gemma-4-e4b")
    assert "--identifier" in args and "apollo-mind" in args
    assert "--yes" in args


def test_timeout_blocks_further_mutations(monkeypatch):
    monkeypatch.setattr(mind, "command", AsyncMock(side_effect=TimeoutError))
    asyncio.run(mind.perform("load", mind.Settings()))
    with pytest.raises(HTTPException):
        mind.ensure_idle()


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


def test_ace_coexistence_requires_opt_in(monkeypatch):
    monkeypatch.setattr(mind, "inventory", AsyncMock(return_value=([{"key": mind.Settings().model_key}], [])))
    monkeypatch.setattr(ace, "observe", AsyncMock(return_value=ServiceState(state="running")))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mind.action("load"))
    assert exc.value.status_code == 409
    assert mind._task is None


def test_inference_blocks_unload_even_when_caller_disconnects(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def inference(payload):
            entered.set()
            await release.wait()
            return {}
        monkeypatch.setattr(ace, "observe", AsyncMock(return_value=ServiceState(state="stopped")))
        monkeypatch.setattr(mind, "inventory", AsyncMock(return_value=([], [{"identifier": mind.MODEL_ID}])))
        monkeypatch.setattr(mind, "service_state", AsyncMock(return_value="active"))
        monkeypatch.setattr(mind, "infer_request", inference)
        caller = asyncio.create_task(mind.infer({"intent": "continue"}))
        await entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert mind.busy()
        with pytest.raises(HTTPException) as exc:
            await mind.action("unload")
        assert exc.value.status_code == 409
        release.set()
        await mind._task
        assert not mind.busy()
    asyncio.run(scenario())
