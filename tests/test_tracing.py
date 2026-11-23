"""``agent/tracing.py`` without the OpenTelemetry SDK — the state CI runs in.

The ``obs`` group is not in ``default-groups`` and CI never installs it, so
everything here must pass with ``deus_obs`` absent. The "absent" state is
forced with ``monkeypatch`` rather than trusted to the environment, so the
same assertions also hold on a box that has the group synced. What spans
look like once the SDK IS there: ``tests/web/test_tracing_spans.py``.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from agent import tracing


@pytest.fixture
def no_deus_obs(monkeypatch):
    monkeypatch.setattr(tracing, "deus_obs", None)


# ── usage_attributes: pure ───────────────────────────────────────────


def test_usage_reads_the_openai_shape():
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    assert tracing.usage_attributes(usage) == {
        "llm.token_count.prompt": 120,
        "llm.token_count.completion": 30,
        "llm.token_count.total": 150,
    }


def test_usage_reads_the_anthropic_shape_and_derives_the_total():
    usage = SimpleNamespace(input_tokens=200, output_tokens=12)
    assert tracing.usage_attributes(usage) == {
        "llm.token_count.prompt": 200,
        "llm.token_count.completion": 12,
        "llm.token_count.total": 212,
    }


def test_usage_reads_a_dict():
    assert tracing.usage_attributes({"prompt_tokens": 5}) == {"llm.token_count.prompt": 5}


@pytest.mark.parametrize("usage", [None, SimpleNamespace(), {"prompt_tokens": "5"}])
def test_usage_leaves_out_what_it_cannot_read(usage):
    assert tracing.usage_attributes(usage) == {}


def test_usage_ignores_booleans():
    # bool is an int subclass; a True token count is a bug, not a 1.
    assert tracing.usage_attributes({"prompt_tokens": True}) == {}


def test_record_usage_never_raises_on_a_response_without_usage():
    tracing.record_usage(tracing.NULL_SPAN, object())


# ── provider labels ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("ollama", ("lmstudio", "openai")),  # Apollo's word for local LM Studio
        ("azure", ("azure", "openai")),
        ("anthropic", ("anthropic", "anthropic")),
        ("litellm", ("litellm", "openai")),
        ("something-new", ("something-new", None)),
        (None, (None, None)),
    ],
)
def test_provider_labels(provider, expected):
    assert tracing.provider_labels(provider) == expected


# ── the absent state ─────────────────────────────────────────────────


def test_span_yields_the_null_span_without_the_package(no_deus_obs):
    with tracing.span("x", **{"apollo.a": 1}) as sp:
        sp.set_attribute("k", "v")
        assert sp is tracing.NULL_SPAN
    assert tracing.enabled() is False


def test_llm_and_tool_spans_are_null_without_the_package(no_deus_obs):
    with tracing.llm_span("llm.x", provider="ollama", model="m") as sp:
        tracing.record_usage(sp, SimpleNamespace(usage={"prompt_tokens": 1}))
        tracing.mark_error(sp, RuntimeError("boom"))
    with tracing.tool_span("pick", {"genre": "techno"}) as sp:
        assert sp is tracing.NULL_SPAN


def test_span_reraises_without_the_package(no_deus_obs):
    with pytest.raises(ValueError):
        with tracing.span("x"):
            raise ValueError("untouched")


def test_annotate_and_current_span_are_free_without_the_package(no_deus_obs):
    tracing.annotate(**{"apollo.a": 1})
    assert tracing.current_span() is tracing.NULL_SPAN


def test_traced_runs_sync_and_async_without_the_package(no_deus_obs):
    @tracing.traced("sync")
    def double(x: int) -> int:
        return 2 * x

    @tracing.traced("async")
    async def triple(x: int) -> int:
        return 3 * x

    assert double(2) == 4
    assert asyncio.run(triple(2)) == 6


def test_traced_reraises_without_the_package(no_deus_obs):
    @tracing.traced("sync")
    def fail():
        raise KeyError("k")

    with pytest.raises(KeyError):
        fail()


# ── transparency: what FastAPI and the schema builders read ──────────


def test_traced_keeps_the_signature_name_and_doc():
    async def handler(req: int, *, user: str = "x") -> dict:
        """Docstring."""
        return {}

    wrapped = tracing.traced("h")(handler)
    assert inspect.signature(wrapped) == inspect.signature(handler)
    assert wrapped.__name__ == "handler"
    assert wrapped.__doc__ == "Docstring."
    assert inspect.iscoroutinefunction(wrapped)


def test_traced_returns_generators_unchanged():
    def gen():
        yield 1

    async def agen():
        yield 1

    assert tracing.traced("g")(gen) is gen
    assert tracing.traced("g")(agen) is agen


def test_the_instrumented_routes_keep_their_parameters():
    """FastAPI builds each route from ``inspect.signature`` of the handler.

    A wrapper that lost it would register a route with no body model and no
    auth dependency — and raise nothing.
    """
    from web.backend import generator

    for handler, first in [
        (generator.create_generation_task, "req"),
        (generator.publish_take, "req"),
        (generator.edit_take, "req"),
        (generator.critique_take, "req"),
    ]:
        params = list(inspect.signature(handler).parameters)
        assert params[0] == first, (handler.__name__, params)
        assert "current_user" in params, handler.__name__
