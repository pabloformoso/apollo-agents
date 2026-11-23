"""What Apollo's spans look like once the OpenTelemetry SDK is there.

Skipped in CI, by design: the ``obs`` group is not in ``default-groups`` and
CI never syncs it (``tests/test_tracing.py`` covers that state). Run locally
with ``uv sync --group obs`` first.

The spans are read back from an in-memory exporter on a provider this module
installs. ``deus_obs.install()`` then ADOPTS that provider instead of building
its own, so no OTLP exporter is ever attached and no test opens a socket
toward a collector. ``set_tracer_provider`` is set-once per process, so the
fixture is module-scoped and leaves ``deus_obs`` uninstalled on the way out —
the rest of the suite runs with nothing recording.

Two properties matter more than the span tree, and are asserted on every
test through ``assert_no_secrets``: no API key from ``context_variables``,
no prompt and no tool payload ever lands on a span. The Phoenix on jarvis is
shared with two other projects.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("opentelemetry.sdk", reason="needs `uv sync --group obs`")
deus_obs = pytest.importorskip("deus_obs", reason="needs `uv sync --group obs`")

from agent import tracing  # noqa: E402
from web.backend import brief_parser, covers, generator, pipeline  # noqa: E402

from .test_generator_tasks import _BODY, _box, _entry, _install_ace  # noqa: E402

SECRET = "sk-SECRET-do-not-trace"
PROMPT_MARKER = "PROMPT-TEXT-do-not-trace"


@pytest.fixture(scope="module")
def exporter():
    from deus_obs import runtime
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    memory = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        otel_trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(memory))

    runtime._reset_for_tests()
    cfg = deus_obs.install("http://127.0.0.1:9", project="apollo-tests", service="apollo-tests")
    assert cfg.enabled, cfg.status_line()
    assert cfg.capture == "metadata"  # the default this whole module relies on
    assert tracing.enabled()
    yield memory
    runtime._reset_for_tests()
    memory.clear()


@pytest.fixture(autouse=True)
def spans(exporter):
    exporter.clear()
    yield exporter
    exporter.clear()


def by_name(exporter, name):
    found = [s for s in exporter.get_finished_spans() if s.name == name]
    assert found, [s.name for s in exporter.get_finished_spans()]
    return found


def assert_no_secrets(exporter):
    for sp in exporter.get_finished_spans():
        for key, value in (sp.attributes or {}).items():
            text = str(value)
            assert SECRET not in text, (sp.name, key)
            assert PROMPT_MARKER not in text, (sp.name, key)


# ── The DJ's streaming runner: AGENT → LLM per turn → TOOL ───────────


def _chunk(content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _tool_call(name, arguments):
    return SimpleNamespace(
        index=0, id="call-1", function=SimpleNamespace(name=name, arguments=arguments)
    )


class _FakeAsyncOpenAI:
    """Turn 1 asks for a tool, turn 2 answers in prose with a usage chunk."""

    calls = 0

    def __init__(self, **_kw):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_kw):
        type(self).calls += 1
        if type(self).calls == 1:
            chunks = [_chunk(tool_calls=[_tool_call("pick_next_track", '{"genre": "techno"}')])]
        else:
            chunks = [
                _chunk(content=f"Next up {PROMPT_MARKER}"),
                _chunk(usage=SimpleNamespace(prompt_tokens=90, completion_tokens=7, total_tokens=97)),
            ]

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


def pick_next_track(genre: str, context_variables: dict) -> str:
    """Pick the next track."""
    return f"picked {PROMPT_MARKER} {context_variables['api_key']}"


def test_streaming_run_is_one_agent_span_with_llm_turns_and_a_tool(spans, monkeypatch):
    import openai

    _FakeAsyncOpenAI.calls = 0
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(pipeline, "_PROVIDER", "ollama")
    ctx = {"api_key": SECRET}
    sent: list[dict] = []

    async def emit(event):
        sent.append(event)

    async def run():
        with pipeline._agent_span("live_dj"):
            return await pipeline._run_openai_streaming(
                "system " + PROMPT_MARKER,
                [pick_next_track],
                [{"role": "user", "content": PROMPT_MARKER}],
                ctx,
                emit,
                5,
                base_url="http://lmstudio.test/v1",
            )

    assert "Next up" in asyncio.run(run())

    (agent,) = by_name(spans, "agent.live_dj")
    assert agent.attributes["openinference.span.kind"] == "AGENT"
    assert agent.attributes["apollo.lane"] == "live_dj"

    turns = by_name(spans, "llm.stream")
    assert len(turns) == 2
    for turn in turns:
        assert turn.parent.span_id == agent.context.span_id
        assert turn.attributes["openinference.span.kind"] == "LLM"
        assert turn.attributes["llm.provider"] == "lmstudio"
        assert turn.attributes["llm.model_name"] == (
            pipeline.main_llm.persisted_model() or pipeline._MODEL
        )
    first, second = sorted(turns, key=lambda s: s.attributes["apollo.turn"])
    assert first.attributes["apollo.tool_calls"] == 1
    assert second.attributes["llm.token_count.total"] == 97

    (tool,) = by_name(spans, "pick_next_track")
    assert tool.attributes["openinference.span.kind"] == "TOOL"
    assert tool.attributes["deus_obs.input.args"] == ("genre",)  # names, never values
    assert tool.attributes["apollo.tool.error"] is False
    assert tool.parent.span_id == agent.context.span_id
    assert_no_secrets(spans)


def test_a_raising_tool_is_flagged_on_its_span(spans):
    def broken(context_variables: dict) -> str:
        raise RuntimeError("nope")

    out = pipeline._run_tool_traced("broken", {}, {}, {"broken": broken})
    assert out.startswith("Tool error:")
    (tool,) = by_name(spans, "broken")
    assert tool.attributes["apollo.tool.error"] is True


# ── brief_parser ─────────────────────────────────────────────────────


class _FakeOpenAI:
    def __init__(self, content='{"genre": "techno"}'):
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=20, total_tokens=320),
        )


def test_brief_parse_has_a_chain_and_an_llm_span(spans, monkeypatch):
    monkeypatch.setattr(brief_parser, "detect_provider", lambda: "ollama")
    monkeypatch.setattr(brief_parser, "_build_openai_client", lambda p: (_FakeOpenAI(), "gemma-test"))

    brief_parser.parse(f"a techno set {PROMPT_MARKER}")

    (parse,) = by_name(spans, "brief_parser.parse")
    (llm,) = by_name(spans, "llm.brief_parser")
    assert llm.parent.span_id == parse.context.span_id
    assert llm.attributes["llm.model_name"] == "gemma-test"
    assert llm.attributes["llm.token_count.prompt"] == 300
    assert llm.attributes["apollo.finish_reason"] == "stop"
    assert parse.attributes["apollo.brief.fields"] >= 1
    assert_no_secrets(spans)


def test_a_failed_brief_parse_is_an_error_span_and_still_all_null(spans, monkeypatch):
    def boom(_p):
        raise ConnectionError("LM Studio is down")

    monkeypatch.setattr(brief_parser, "detect_provider", lambda: "ollama")
    monkeypatch.setattr(brief_parser, "_build_openai_client", boom)

    assert all(v is None for v in brief_parser.parse("techno").values())
    (parse,) = by_name(spans, "brief_parser.parse")
    assert parse.status.status_code.name == "ERROR"
    assert "ConnectionError" in parse.attributes["apollo.error"]


# ── covers' art direction ────────────────────────────────────────────


def test_cover_art_direction_is_an_llm_span(spans, monkeypatch):
    import openai

    monkeypatch.setattr(openai, "AzureOpenAI", lambda **_kw: _FakeOpenAI("a long enough cover prompt here"))
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://azure.test")

    covers._ask_art_direction("gpt-4o-mini", "system", PROMPT_MARKER)

    (llm,) = by_name(spans, "llm.cover_art_direction")
    assert llm.attributes["llm.provider"] == "azure"
    assert llm.attributes["llm.model_name"] == "gpt-4o-mini"
    assert llm.attributes["llm.token_count.total"] == 320
    assert_no_secrets(spans)


# ── The generator lane ───────────────────────────────────────────────


@pytest.fixture
def ace_on(monkeypatch):
    from web.backend import acestep_client as ac

    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)
    monkeypatch.setattr(generator, "_catalog_genres", lambda: set())


def test_release_is_a_generator_span_over_the_ace_call(spans, auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/tasks", json={**_BODY, "prompt": PROMPT_MARKER})
    assert r.status_code == 200, r.text

    (release,) = by_name(spans, "generator.release")
    (ace,) = by_name(spans, "ace.release_task")
    assert ace.parent.span_id == release.context.span_id
    assert ace.attributes["apollo.ace.upload"] is False
    assert release.attributes["apollo.genre"] == "techno"
    assert release.attributes["apollo.task_id"] == "task-1"
    assert release.attributes["apollo.queue_position"] == 4
    assert isinstance(release.attributes["apollo.bpm"], int)
    assert_no_secrets(spans)


def test_a_refused_release_carries_its_http_status(spans, auth_client, ace_on, monkeypatch):
    monkeypatch.setattr(generator, "live_session_active", lambda *a, **k: True)

    r = auth_client.post("/api/generator/tasks", json=_BODY)
    assert r.status_code == 409

    (release,) = by_name(spans, "generator.release")
    assert release.attributes["http.status_code"] == 409


def test_the_done_poll_spans_the_take_copy(spans, auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box(results=[_entry()]))

    r = auth_client.get("/api/generator/tasks/task-1")
    assert r.json()["status"] == "done"

    (done,) = by_name(spans, "generator.takes_done")
    (copy,) = by_name(spans, "generator.take_copy")
    assert copy.parent.span_id == done.context.span_id
    assert done.attributes["apollo.takes"] == 1
    assert copy.attributes["apollo.take.bytes"] > 0
    assert copy.status.status_code.name != "ERROR"

    # A re-poll finds the copy in place: no second copy span, by design.
    spans.clear()
    auth_client.get("/api/generator/tasks/task-1")
    assert not [s for s in spans.get_finished_spans() if s.name == "generator.take_copy"]


def test_a_pending_poll_emits_no_span(spans, auth_client, ace_on, monkeypatch):
    """Polls fire every 3 s per open wizard; each would be a root trace."""
    _install_ace(monkeypatch, _box(results=[_entry(status=0, result="[]")]))

    auth_client.get("/api/generator/tasks/task-1")
    assert [s.name for s in spans.get_finished_spans()] == []


def test_the_critique_read_is_an_llm_span(spans, monkeypatch):
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **_kw: _FakeOpenAI("Warm, a little dark."))
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.test")
    monkeypatch.setenv("LITELLM_API_KEY", SECRET)
    monkeypatch.setenv("GENERATIVE_MODEL", "critic-test")

    assert generator._llm_paragraph("system", PROMPT_MARKER, "litellm") == "Warm, a little dark."

    (llm,) = by_name(spans, "llm.critique")
    assert llm.attributes["llm.provider"] == "litellm"
    assert llm.attributes["llm.model_name"] == "critic-test"
    assert llm.attributes["llm.token_count.completion"] == 20
    assert_no_secrets(spans)


def test_fastapi_traces_nothing_of_its_own(spans, client):
    """FastAPI 0.163+ would span every request once a provider exists.

    Its ``url.query`` redaction does not know ``?token=``, which the audio
    proxy and cover routes take, so a JWT would land in the shared store.
    ``app.py`` turns that telemetry off; this pins it.
    """
    client.get(f"/api/generator/audio?path=x&token={SECRET}")
    client.get("/api/generator/health")
    assert [s.name for s in spans.get_finished_spans()] == []
