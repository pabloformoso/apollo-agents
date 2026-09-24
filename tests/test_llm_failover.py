"""Local LLM (gemma on LM Studio) → Azure gpt-4o failover.

Regression for the 2026-09-24 demo: after a few model swaps LM Studio
answered ``400 Failed to load model "google/gemma-4-e4b"`` and the brief
parser returned all-null twice (11:25/11:26 UTC). The SDK never retries
a 400, so nothing recovered.

No test here reaches a network: the root conftest pins
``APOLLO_LLM_FAILOVER=0`` and each test opts in with fake Azure env and
fake SDK classes.
"""
from __future__ import annotations

import asyncio

import httpx
import openai
import pytest

from agent import llm_failover

REQ = httpx.Request("POST", "http://lmstudio:1234/v1/chat/completions")
LOAD_FAILED = 'Failed to load model "google/gemma-4-e4b". Error: Failed to load model.'


def _status_error(cls, status: int, message: str):
    return cls(message, response=httpx.Response(status, request=REQ), body=None)


def load_failed_400():
    return _status_error(openai.BadRequestError, 400, f"Error code: 400 - {LOAD_FAILED}")


@pytest.fixture
def azure_env(monkeypatch):
    monkeypatch.setenv("APOLLO_LLM_FAILOVER", "1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    monkeypatch.delenv("APOLLO_LLM_FAILOVER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("APOLLO_LLM_FAILOVER_COOLDOWN_SEC", raising=False)
    llm_failover.reset()
    yield
    llm_failover.reset()


# ── Classification ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [
        openai.APIConnectionError(request=REQ),
        openai.APITimeoutError(request=REQ),
        _status_error(openai.InternalServerError, 500, "boom"),
        _status_error(openai.NotFoundError, 404, "model not found"),
        _status_error(openai.RateLimitError, 429, "slow down"),
        load_failed_400(),
        _status_error(openai.BadRequestError, 400, "No models loaded. Please load a model"),
    ],
    ids=["connect", "timeout", "500", "404", "429", "400-load", "400-none-loaded"],
)
def test_outages_fail_over(exc):
    assert llm_failover.is_local_outage(exc)


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(openai.BadRequestError, 400, "messages: field required"),
        _status_error(openai.AuthenticationError, 401, "bad key"),
        ValueError("a bug in our code"),
    ],
    ids=["400-bad-request", "401", "not-an-api-error"],
)
def test_a_bad_request_is_not_an_outage(exc):
    # It would fail identically on Azure — and cost money doing it.
    assert not llm_failover.is_local_outage(exc)


def test_configured_needs_key_endpoint_and_deployment(azure_env, monkeypatch):
    assert llm_failover.configured()
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT")
    assert not llm_failover.configured()
    monkeypatch.setenv("APOLLO_LLM_FAILOVER_DEPLOYMENT", "gpt-4o-dedicated")
    assert llm_failover.configured()
    assert llm_failover.deployment() == "gpt-4o-dedicated"


def test_switch_off(azure_env, monkeypatch):
    monkeypatch.setenv("APOLLO_LLM_FAILOVER", "0")
    assert not llm_failover.configured()


# ── call(): the breaker ───────────────────────────────────────────────────


def test_healthy_local_never_touches_azure(azure_env):
    def azure():
        raise AssertionError("Azure must not be called")

    assert llm_failover.call("t", lambda: "gemma", azure) == "gemma"


def test_outage_fails_over_and_holds_on_azure(azure_env, capsys):
    calls = []

    def local():
        calls.append("local")
        raise load_failed_400()

    def azure():
        calls.append("azure")
        return "gpt-4o"

    assert llm_failover.call("t", local, azure) == "gpt-4o"
    # Within the cooldown, local is not even tried.
    assert llm_failover.call("t", local, azure) == "gpt-4o"
    assert calls == ["local", "azure", "azure"]
    out = capsys.readouterr().out
    assert "[llm-failover]" in out and "gpt-4o" in out and "Failed to load model" in out


def test_non_outage_error_propagates(azure_env):
    def local():
        raise _status_error(openai.BadRequestError, 400, "messages: field required")

    with pytest.raises(openai.BadRequestError):
        llm_failover.call("t", local, lambda: "never")
    assert not llm_failover.local_down()


def test_after_cooldown_local_is_tried_again(azure_env, monkeypatch, capsys):
    monkeypatch.setenv("APOLLO_LLM_FAILOVER_COOLDOWN_SEC", "0")

    def down():
        raise openai.APIConnectionError(request=REQ)

    llm_failover.call("t", down, lambda: "azure")
    assert llm_failover.call("t", lambda: "gemma", lambda: "azure") == "gemma"
    assert "back on it" in capsys.readouterr().out


def test_acall_mirrors_call(azure_env):
    async def local():
        raise openai.APIConnectionError(request=REQ)

    async def azure():
        return "gpt-4o"

    assert asyncio.run(llm_failover.acall("t", local, azure)) == "gpt-4o"
    assert llm_failover.local_down()


# ── Fakes for the call sites ──────────────────────────────────────────────


class _Resp:
    def __init__(self, text):
        msg = type("M", (), {"content": text, "tool_calls": None})()
        self.choices = [type("C", (), {"message": msg})()]


def _sync_client(behaviour, calls, label):
    class _Completions:
        def create(self, **kwargs):
            calls.append((label, kwargs))
            return behaviour(kwargs)

    class _Client:
        def __init__(self, **kwargs):
            calls.append((label + ":init", kwargs))
            self.chat = type("Chat", (), {"completions": _Completions()})()

    return _Client


def _raise(exc):
    def _b(_kwargs):
        raise exc

    return _b


# ── brief_parser — the call that failed at the demo ───────────────────────


def test_brief_parser_fails_over_on_load_failure(azure_env, monkeypatch):
    from web.backend import brief_parser

    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://stub:1234/v1")
    monkeypatch.setenv("AGENT_MODEL", "google/gemma-4-e4b")
    calls: list = []
    monkeypatch.setattr(openai, "OpenAI", _sync_client(_raise(load_failed_400()), calls, "local"))
    reply = '{"genre": "healing", "duration_min": 90, "mood": "calm"}'
    monkeypatch.setattr(openai, "AzureOpenAI", _sync_client(lambda k: _Resp(reply), calls, "azure"))

    parsed = brief_parser.parse("90 minutes of healing music, calm")

    assert parsed["genre"] == "healing"
    assert parsed["duration_min"] == 90
    azure_call = next(k for label, k in calls if label == "azure")
    assert azure_call["model"] == "gpt-4o"  # never the LM Studio name


def test_brief_parser_without_failover_still_degrades_to_null(monkeypatch):
    # APOLLO_LLM_FAILOVER=0 (root conftest): the old contract, all-null.
    from web.backend import brief_parser

    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://stub:1234/v1")
    calls: list = []
    monkeypatch.setattr(openai, "OpenAI", _sync_client(_raise(load_failed_400()), calls, "local"))

    assert brief_parser.parse("90 minutes of healing")["genre"] is None


# ── critique ──────────────────────────────────────────────────────────────


def test_critique_fails_over(azure_env, monkeypatch):
    from web.backend import generator

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://stub:1234/v1")
    calls: list = []
    monkeypatch.setattr(
        openai, "OpenAI", _sync_client(_raise(openai.APIConnectionError(request=REQ)), calls, "local"),
    )
    monkeypatch.setattr(openai, "AzureOpenAI", _sync_client(lambda k: _Resp("A warm take."), calls, "azure"))

    assert generator._llm_paragraph("sys", "user", "ollama") == "A warm take."
    assert next(k for label, k in calls if label == "azure")["model"] == "gpt-4o"


def test_critique_on_litellm_does_not_fail_over(azure_env, monkeypatch):
    # The failover is for the LOCAL model; the LiteLLM proxy is not ours.
    from web.backend import generator

    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy/v1")
    calls: list = []
    monkeypatch.setattr(
        openai, "OpenAI", _sync_client(_raise(openai.APIConnectionError(request=REQ)), calls, "local"),
    )
    with pytest.raises(openai.APIConnectionError):
        generator._llm_paragraph("sys", "user", "litellm")


# ── pipeline streaming — planner, critic and the live DJ ──────────────────


class _Delta:
    def __init__(self, content=None):
        self.content = content
        self.tool_calls = None


class _Chunk:
    def __init__(self, text):
        self.choices = [type("C", (), {"delta": _Delta(text)})()]


class _Stream:
    def __init__(self, texts):
        self._chunks = [_Chunk(t) for t in texts]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _async_client(behaviour, calls, label):
    class _Completions:
        async def create(self, **kwargs):
            calls.append((label, kwargs))
            return behaviour(kwargs)

    class _Client:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    return _Client


def _drive(pl, tool_fns=()):
    emitted: list = []

    async def emit(ev):
        emitted.append(ev)

    final = asyncio.run(
        pl._run_openai_streaming(
            "system", list(tool_fns), [{"role": "user", "content": "hi"}], {}, emit, 3,
            base_url="http://stub:1234/v1", failover=True,
        )
    )
    return final, emitted


def test_pipeline_stream_fails_over_before_anything_is_said(azure_env, monkeypatch):
    from web.backend import pipeline as pl

    calls: list = []
    monkeypatch.setattr(openai, "AsyncOpenAI", _async_client(_raise(load_failed_400()), calls, "local"))
    monkeypatch.setattr(
        openai, "AsyncAzureOpenAI",
        _async_client(lambda k: _Stream(["Keeping ", "it calm."]), calls, "azure"),
    )

    final, emitted = _drive(pl)

    assert final == "Keeping it calm."
    assert [e["content"] for e in emitted if e["type"] == "text_delta"] == ["Keeping ", "it calm."]
    azure_kwargs = next(k for label, k in calls if label == "azure")
    assert azure_kwargs["model"] == "gpt-4o"
    # An empty tools array is a 400 on Azure; it must be omitted.
    assert "tools" not in azure_kwargs


def test_pipeline_stream_healthy_local_is_unchanged(azure_env, monkeypatch):
    from web.backend import pipeline as pl

    calls: list = []
    monkeypatch.setattr(openai, "AsyncOpenAI", _async_client(lambda k: _Stream(["gemma here"]), calls, "local"))

    def _no_azure(**_):
        raise AssertionError("Azure must not be built")

    monkeypatch.setattr(openai, "AsyncAzureOpenAI", _no_azure)
    final, _ = _drive(pl)
    assert final == "gemma here"


def test_pipeline_stream_non_outage_propagates(azure_env, monkeypatch):
    from web.backend import pipeline as pl

    calls: list = []
    bad = _status_error(openai.BadRequestError, 400, "messages: field required")
    monkeypatch.setattr(openai, "AsyncOpenAI", _async_client(_raise(bad), calls, "local"))
    with pytest.raises(openai.BadRequestError):
        _drive(pl)


def test_pipeline_dispatcher_only_fails_over_on_the_local_provider(monkeypatch):
    from web.backend import pipeline as pl

    seen = {}

    async def fake(*args, **kwargs):
        seen.update(kwargs)
        return ""

    monkeypatch.setattr(pl, "_run_openai_streaming", fake)
    monkeypatch.setattr(pl, "_PROVIDER", "ollama")
    asyncio.run(pl.run_agent_streaming("s", [], [], {}, lambda e: None))
    assert seen["failover"] is True

    monkeypatch.setattr(pl, "_PROVIDER", "litellm")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy/v1")
    asyncio.run(pl.run_agent_streaming("s", [], [], {}, lambda e: None))
    assert seen["failover"] is False


# ── CLI runner (agent/run.py) ─────────────────────────────────────────────


def test_cli_agent_fails_over(azure_env, monkeypatch):
    from agent import run

    monkeypatch.setattr(run, "_PROVIDER", "ollama")
    calls: list = []
    monkeypatch.setattr(openai, "OpenAI", _sync_client(_raise(load_failed_400()), calls, "local"))
    monkeypatch.setattr(openai, "AzureOpenAI", _sync_client(lambda k: _Resp("Done."), calls, "azure"))

    out = run.run_agent("sys", [], [{"role": "user", "content": "hi"}], {})

    assert out == "Done."
    assert next(k for label, k in calls if label == "azure")["model"] == "gpt-4o"
