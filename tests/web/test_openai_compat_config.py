"""_openai_compat_config — (base_url, api_key) per OpenAI-compatible provider.

The helper exists twice by design (agent/run.py and web/backend/pipeline.py
mirror their provider detection), so both copies are pinned here. _PROVIDER
is resolved at import time in both modules; tests monkeypatch the module
attribute rather than reloading.
"""
from __future__ import annotations

import pytest

import agent.run as agent_run
from web.backend import pipeline


@pytest.mark.parametrize("mod", [agent_run, pipeline], ids=["agent", "web"])
def test_litellm_uses_proxy_url_and_key(mod, monkeypatch):
    monkeypatch.setattr(mod, "_PROVIDER", "litellm")
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-team")
    assert mod._openai_compat_config() == ("https://litellm.example.org/v1", "sk-team")


@pytest.mark.parametrize("mod", [agent_run, pipeline], ids=["agent", "web"])
def test_litellm_key_has_placeholder_default(mod, monkeypatch):
    monkeypatch.setattr(mod, "_PROVIDER", "litellm")
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.org/v1")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    base, key = mod._openai_compat_config()
    assert base == "https://litellm.example.org/v1"
    assert key  # OpenAI client rejects an empty api_key


@pytest.mark.parametrize("mod", [agent_run, pipeline], ids=["agent", "web"])
def test_ollama_keeps_localhost_default(mod, monkeypatch):
    monkeypatch.setattr(mod, "_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert mod._openai_compat_config() == ("http://localhost:11434/v1", "ollama")


@pytest.mark.parametrize("mod", [agent_run, pipeline], ids=["agent", "web"])
def test_ollama_env_override(mod, monkeypatch):
    monkeypatch.setattr(mod, "_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://100.68.5.104:1234/v1")
    assert mod._openai_compat_config() == ("http://100.68.5.104:1234/v1", "ollama")
