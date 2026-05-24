"""Unit tests for Azure OpenAI client construction.

Covers the four `_build_*` helpers introduced when switching the project
from direct OpenAI to Azure OpenAI:

  * main._build_azure_chat_client         (text/json chat completions)
  * main._build_azure_image_client        (DALL-E 3 artwork)
  * agent.run._build_azure_client         (sync chat client for the CLI agent)
  * web.backend.pipeline._build_async_azure_client (async streaming client)

Each helper reads the same three required env vars
(AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and an api_version with a
sensible default) — the tests assert kwargs are forwarded verbatim to
the SDK and that the default api_version is applied when unset.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def azure_env(monkeypatch):
    """Set the minimum Azure env vars all helpers expect."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-deploy")
    monkeypatch.setenv("AZURE_OPENAI_IMAGE_DEPLOYMENT", "dalle3-deploy")
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_IMAGE_API_VERSION", raising=False)
    return monkeypatch


class _StubAzureClient:
    """Captures the kwargs the helper passed to the SDK constructor."""
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


# ---------------------------------------------------------------------------
# main._build_azure_chat_client
# ---------------------------------------------------------------------------

def test_main_chat_client_uses_default_api_version(azure_env):
    import main
    azure_env.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    main._build_azure_chat_client()

    assert _StubAzureClient.last_kwargs == {
        "api_key": "test-key",
        "azure_endpoint": "https://test.openai.azure.com/",
        "api_version": "2024-10-21",
    }


def test_main_chat_client_respects_explicit_api_version(azure_env):
    import main
    azure_env.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    azure_env.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    main._build_azure_chat_client()

    assert _StubAzureClient.last_kwargs["api_version"] == "2025-01-01-preview"


# ---------------------------------------------------------------------------
# main._build_azure_image_client
# ---------------------------------------------------------------------------

def test_main_image_client_falls_back_to_chat_endpoint_and_key(azure_env):
    """When IMAGE_ENDPOINT/IMAGE_API_KEY are unset, reuse the chat resource."""
    import main
    azure_env.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    main._build_azure_image_client()

    assert _StubAzureClient.last_kwargs == {
        "api_key": "test-key",
        "azure_endpoint": "https://test.openai.azure.com/",
        "api_version": "2024-02-01",
    }


def test_main_image_client_uses_separate_endpoint_and_key_when_set(azure_env):
    """Image deployments often live on a different Azure resource — verify
    the override env vars take precedence over the chat ones."""
    import main
    azure_env.setenv("AZURE_OPENAI_IMAGE_ENDPOINT", "https://img.cognitiveservices.azure.com/")
    azure_env.setenv("AZURE_OPENAI_IMAGE_API_KEY", "image-resource-key")
    azure_env.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    main._build_azure_image_client()

    assert _StubAzureClient.last_kwargs == {
        "api_key": "image-resource-key",
        "azure_endpoint": "https://img.cognitiveservices.azure.com/",
        "api_version": "2024-02-01",
    }


def test_main_image_client_respects_explicit_image_api_version(azure_env):
    import main
    azure_env.setenv("AZURE_OPENAI_IMAGE_API_VERSION", "2024-05-01-preview")
    azure_env.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    main._build_azure_image_client()

    assert _StubAzureClient.last_kwargs["api_version"] == "2024-05-01-preview"


# ---------------------------------------------------------------------------
# main._decode_image_response
# ---------------------------------------------------------------------------

class _ImageData:
    def __init__(self, b64_json=None, url=None):
        self.b64_json = b64_json
        self.url = url


class _ImageResponse:
    def __init__(self, data):
        self.data = data


def test_decode_image_response_handles_b64_json():
    import base64
    import main

    payload = b"\x89PNG\r\n\x1a\n-fake-png-bytes-"
    encoded = base64.b64encode(payload).decode()
    response = _ImageResponse([_ImageData(b64_json=encoded)])

    assert main._decode_image_response(response) == payload


def test_decode_image_response_handles_url(monkeypatch):
    """gpt-image-* sometimes returns a presigned URL instead of base64."""
    import main

    payload = b"\x89PNG\r\n\x1a\n-from-url-"
    response = _ImageResponse([_ImageData(url="https://example.test/img.png")])

    class _FakeResp:
        def __enter__(self_inner): return self_inner
        def __exit__(self_inner, *a): return False
        def read(self_inner): return payload

    captured = {}
    def fake_urlopen(url):
        captured["url"] = url
        return _FakeResp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert main._decode_image_response(response) == payload
    assert captured["url"] == "https://example.test/img.png"


def test_decode_image_response_raises_when_empty():
    import main

    response = _ImageResponse([_ImageData()])
    with pytest.raises(ValueError, match="neither b64_json nor url"):
        main._decode_image_response(response)


def test_main_chat_client_raises_without_required_env(monkeypatch):
    """Missing AZURE_OPENAI_API_KEY/ENDPOINT must raise KeyError, not silently
    construct a broken client. The artwork/disambiguation call sites guard with
    a presence check before calling the helper, but the helper itself should
    fail loudly if anyone forgets that guard."""
    import main
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setattr(main, "AzureOpenAI", _StubAzureClient, raising=True)

    with pytest.raises(KeyError):
        main._build_azure_chat_client()


# ---------------------------------------------------------------------------
# agent.run._build_azure_client
# ---------------------------------------------------------------------------

def test_agent_run_build_azure_client_uses_default_api_version(azure_env):
    from openai import AzureOpenAI as _RealAzureOpenAI  # noqa: F401  (ensure module import)
    import openai
    from agent import run as agent_run

    azure_env.setattr(openai, "AzureOpenAI", _StubAzureClient, raising=True)

    agent_run._build_azure_client()

    assert _StubAzureClient.last_kwargs == {
        "api_key": "test-key",
        "azure_endpoint": "https://test.openai.azure.com/",
        "api_version": "2024-10-21",
    }


def test_agent_run_build_azure_client_respects_api_version(azure_env):
    import openai
    from agent import run as agent_run

    azure_env.setenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview")
    azure_env.setattr(openai, "AzureOpenAI", _StubAzureClient, raising=True)

    agent_run._build_azure_client()

    assert _StubAzureClient.last_kwargs["api_version"] == "2025-03-01-preview"


# ---------------------------------------------------------------------------
# web.backend.pipeline._build_async_azure_client
# ---------------------------------------------------------------------------

def test_pipeline_build_async_azure_client_uses_default_api_version(azure_env):
    import openai
    from web.backend import pipeline

    azure_env.setattr(openai, "AsyncAzureOpenAI", _StubAzureClient, raising=True)

    pipeline._build_async_azure_client()

    assert _StubAzureClient.last_kwargs == {
        "api_key": "test-key",
        "azure_endpoint": "https://test.openai.azure.com/",
        "api_version": "2024-10-21",
    }


def test_pipeline_build_async_azure_client_respects_api_version(azure_env):
    import openai
    from web.backend import pipeline

    azure_env.setenv("AZURE_OPENAI_API_VERSION", "2025-06-01-preview")
    azure_env.setattr(openai, "AsyncAzureOpenAI", _StubAzureClient, raising=True)

    pipeline._build_async_azure_client()

    assert _StubAzureClient.last_kwargs["api_version"] == "2025-06-01-preview"
