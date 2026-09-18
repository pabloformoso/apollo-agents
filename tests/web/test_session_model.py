from __future__ import annotations

import asyncio
import json

import httpx
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
