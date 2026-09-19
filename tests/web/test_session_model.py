from __future__ import annotations

import asyncio
import pytest
from fastapi import HTTPException

from web.backend import session_model


def test_endpoint_strips_openai_v1_path(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1/")
    assert session_model.endpoint() == "http://100.68.5.104:1234"


def test_settings_roundtrip_uses_restricted_file(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "settings.json"
    monkeypatch.setenv("APOLLO_SESSION_MODEL_SETTINGS_PATH", str(path))
    settings = session_model.Settings(model_key="google/gemma-4-e4b", context_length=4096, flash_attention=False)
    session_model.save_settings(settings)
    assert session_model.read_settings() == settings
    assert path.stat().st_mode & 0o777 == 0o600


def test_persisted_model_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLLO_SESSION_MODEL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("AGENT_MODEL", "env-model")
    assert session_model.persisted_model() is None
    session_model.save_settings(session_model.Settings(model_key="selected-model"))
    assert session_model.persisted_model() == "selected-model"


def test_model_record_marks_loaded_instance():
    record = session_model._model_record({
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

    monkeypatch.setattr(session_model, "_request", fake_request)
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:1234/v1")
    models = asyncio.run(session_model.list_models())
    assert calls == ["/api/v1/models"]
    assert models[0]["key"] == "model-a"


def test_list_models_falls_back_to_v0(monkeypatch):
    calls: list[str] = []

    async def fake_request(path, method="GET", payload=None):
        calls.append(path)
        if path.endswith("/v1/models"):
            raise HTTPException(404, "not supported")
        return {"data": [{"id": "model-b", "state": "not-loaded"}]}

    monkeypatch.setattr(session_model, "_request", fake_request)
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:1234/v1")
    models = asyncio.run(session_model.list_models())
    assert calls == ["/api/v1/models", "/api/v0/models"]
    assert models[0]["key"] == "model-b"


def test_load_uses_unsaved_selector_settings(monkeypatch, tmp_path):
    calls: list[tuple[str, str, dict | None]] = []
    saved: list[session_model.Settings] = []

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

    monkeypatch.setenv("APOLLO_SESSION_MODEL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(session_model, "list_models", fake_models)
    monkeypatch.setattr(session_model, "_request", fake_request)
    monkeypatch.setattr(session_model, "_ensure_session_model_capacity", no_capacity_check)
    monkeypatch.setattr(session_model, "save_settings", saved.append)
    user = {"capabilities": frozenset({"manage_generator"})}
    settings = session_model.Settings(model_key="model-b", context_length=4096)

    result = asyncio.run(session_model.action("load", settings, user))

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

    monkeypatch.setattr(session_model, "_shares_host_with_ace", lambda: True)
    monkeypatch.setattr(session_model.ace_control, "configured", lambda: True)
    monkeypatch.setattr(session_model.ace_control, "controller", fake_controller)
    with pytest.raises(HTTPException) as error:
        asyncio.run(session_model._ensure_session_model_capacity())
    assert error.value.status_code == 409
    assert "Stop ACE" in str(error.value.detail)
