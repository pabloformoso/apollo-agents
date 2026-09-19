"""The main LLM: one model, one settings file, one load path, every caller."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from web.backend import main_llm, mind_control


def test_endpoint_strips_openai_v1_path(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1/")
    assert main_llm.endpoint() == "http://100.68.5.104:1234"


def test_settings_roundtrip_uses_restricted_file(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "settings.json"
    monkeypatch.setenv("APOLLO_MAIN_LLM_SETTINGS_PATH", str(path))
    settings = main_llm.Settings(model_key="google/gemma-4-e4b", context_length=4096, flash_attention=False)
    main_llm.save_settings(settings)
    assert main_llm.read_settings() == settings
    assert path.stat().st_mode & 0o777 == 0o600


def test_persisted_model_overrides_environment(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "env-model")
    assert main_llm.persisted_model() is None
    assert main_llm.current_model() == "env-model"
    main_llm.save_settings(main_llm.Settings(model_key="selected-model"))
    assert main_llm.persisted_model() == "selected-model"
    assert main_llm.current_model() == "selected-model"


def test_default_model_is_the_agent_model_not_a_second_env_name(monkeypatch):
    """SESSION_MODEL (PR #207) is gone: there is one model, so one initial default."""
    monkeypatch.setenv("SESSION_MODEL", "stale-session-model")
    monkeypatch.setenv("BRIEF_MODEL", "brief-only-override")
    monkeypatch.setenv("AGENT_MODEL", "the-main-llm")
    assert main_llm.default_model() == "the-main-llm"
    monkeypatch.delenv("AGENT_MODEL")
    assert main_llm.default_model() == main_llm._DEFAULT_MODEL


def test_legacy_session_model_file_is_read_until_the_first_save(monkeypatch, tmp_path):
    """A choice saved under the old name still applies after the rename."""
    legacy = tmp_path / "session-model-settings.json"
    legacy.write_text(json.dumps({"model_key": "chosen-yesterday", "context_length": 4096, "flash_attention": True}))
    assert main_llm.persisted_model() == "chosen-yesterday"
    assert main_llm.read_settings().context_length == 4096

    main_llm.save_settings(main_llm.Settings(model_key="chosen-today"))
    assert main_llm.persisted_model() == "chosen-today"
    assert main_llm.settings_path().exists()
    assert json.loads(legacy.read_text())["model_key"] == "chosen-yesterday", "the legacy file is never written"


def test_unreadable_settings_fail_closed_but_never_break_inference(monkeypatch):
    main_llm.settings_path().parent.mkdir(parents=True, exist_ok=True)
    main_llm.settings_path().write_text("not json")
    with pytest.raises(HTTPException) as exc:
        main_llm.read_settings()
    assert exc.value.status_code == 503
    assert main_llm.persisted_model() is None


def test_model_record_marks_loaded_instance():
    record = main_llm._model_record({
        "key": "google/gemma-4-e4b",
        "display_name": "Gemma 4 E4B",
        "loaded_instances": [{"instance_id": "google/gemma-4-e4b"}],
    })
    assert record["state"] == "loaded"
    assert record["loaded_instances"][0]["instance_id"] == "google/gemma-4-e4b"


def test_list_models_prefers_v1_and_normalizes(monkeypatch):
    calls: list[str] = []

    async def fake_request(path, method="GET", payload=None):
        calls.append(path)
        return {"models": [{"key": "model-a", "display_name": "Model A", "loaded_instances": []}]}

    monkeypatch.setattr(main_llm, "_request", fake_request)
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:1234/v1")
    models = asyncio.run(main_llm.list_models())
    assert calls == ["/api/v1/models"]
    assert models[0]["key"] == "model-a"


def test_list_models_falls_back_to_v0(monkeypatch):
    calls: list[str] = []

    async def fake_request(path, method="GET", payload=None):
        calls.append(path)
        if path.endswith("/v1/models"):
            raise HTTPException(404, "not supported")
        return {"data": [{"id": "model-b", "state": "not-loaded"}]}

    monkeypatch.setattr(main_llm, "_request", fake_request)
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:1234/v1")
    models = asyncio.run(main_llm.list_models())
    assert calls == ["/api/v1/models", "/api/v0/models"]
    assert models[0]["key"] == "model-b"


ADMIN = {"capabilities": frozenset({"manage_generator"})}


def test_load_uses_unsaved_selector_settings(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []
    saved: list[main_llm.Settings] = []

    async def fake_models():
        return [{
            "key": "model-b", "name": "Model B", "type": "llm",
            "loaded_instances": [], "max_context_length": 8192,
        }]

    async def fake_request(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {"status": "loaded"}

    async def no_capacity_check():
        return None

    monkeypatch.setattr(main_llm, "list_models", fake_models)
    monkeypatch.setattr(main_llm, "_request", fake_request)
    monkeypatch.setattr(main_llm, "_ensure_capacity", no_capacity_check)
    monkeypatch.setattr(main_llm, "save_settings", saved.append)
    settings = main_llm.Settings(model_key="model-b", context_length=4096)

    result = asyncio.run(main_llm.action("load", settings, ADMIN))

    assert result == {"status": "loaded"}
    assert saved == [settings]
    assert calls == [(
        "/api/v1/models/load", "POST", {
            "model": "model-b", "context_length": 4096,
            "flash_attention": True, "echo_load_config": True,
        },
    )]


def test_shared_gpu_capacity_reports_ace_conflict(monkeypatch):
    class State:
        loaded = True
        state = "running"

    async def fake_controller():
        return State()

    monkeypatch.setattr(main_llm, "_shares_host_with_ace", lambda: True)
    monkeypatch.setattr(main_llm.ace_control, "configured", lambda: True)
    monkeypatch.setattr(main_llm.ace_control, "controller", fake_controller)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main_llm._ensure_capacity())
    assert error.value.status_code == 409
    assert "Stop ACE" in str(error.value.detail)


def _unload_fakes(monkeypatch, calls):
    async def fake_models():
        return [{
            "key": "model-b", "name": "Model B", "type": "llm",
            "loaded_instances": [{"instance_id": "model-b"}], "max_context_length": 8192,
        }]

    async def fake_request(path, method="GET", payload=None):
        calls.append((path, method, payload))
        return {"status": "unloaded"}

    monkeypatch.setattr(main_llm, "list_models", fake_models)
    monkeypatch.setattr(main_llm, "_request", fake_request)


def test_unload_waits_for_an_algorave_answer_in_flight(monkeypatch):
    """The Mind's request outlives the browser; the model must outlive the request."""
    calls: list = []
    _unload_fakes(monkeypatch, calls)

    async def pending():
        return True

    monkeypatch.setattr(mind_control, "inference_pending", pending)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main_llm.action("unload", None, ADMIN))
    assert error.value.status_code == 409
    assert "Mind is answering" in str(error.value.detail)
    assert calls == []


def test_unload_proceeds_when_the_mind_is_idle_or_unreachable(monkeypatch):
    calls: list = []
    _unload_fakes(monkeypatch, calls)

    async def idle():
        return False

    monkeypatch.setattr(mind_control, "inference_pending", idle)
    result = asyncio.run(main_llm.action("unload", None, ADMIN))
    assert result == {"status": "unloaded"}
    assert calls == [("/api/v1/models/unload", "POST", {"instance_id": "model-b"})]


def test_only_administrators_manage_the_main_llm():
    with pytest.raises(HTTPException) as error:
        asyncio.run(main_llm.action("load", None, {"capabilities": frozenset()}))
    assert error.value.status_code == 403


def test_the_router_lives_at_main_llm(client, auth_client):
    client.headers.clear()
    assert client.get("/api/main-llm").status_code == 401
    assert client.get("/api/session-model").status_code == 404
