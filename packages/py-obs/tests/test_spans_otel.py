"""What actually lands on a span, once the SDK is there.

Runs only with the [otel] extra. The provider is installed once for the module
and pointed at a closed port: ``set_tracer_provider`` is set-once per process,
so there is exactly one chance to install, and nothing here should depend on a
collector being up. An in-memory exporter is attached alongside the real one to
read the spans back.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from conftest import HAS_OTEL

pytestmark = pytest.mark.skipif(not HAS_OTEL, reason="needs the [otel] extra")

import deus_obs  # noqa: E402
from deus_obs import runtime  # noqa: E402


@pytest.fixture(scope="module")
def exporter():
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    cfg = deus_obs.install("http://127.0.0.1:9", project="deus-obs-tests", service="deus-obs")
    assert cfg.enabled, cfg
    memory = InMemorySpanExporter()
    runtime._PROVIDER.add_span_processor(SimpleSpanProcessor(memory))
    yield memory


@pytest.fixture(autouse=True)
def clean(exporter):
    exporter.clear()
    yield
    exporter.clear()


@pytest.fixture
def capture(monkeypatch):
    """Swap the capture level without reinstalling — it is read per call."""

    def _set(level: str):
        monkeypatch.setattr(
            runtime, "_CONFIG", dataclasses.replace(runtime.config(), capture=level)
        )

    return _set


def only(exporter):
    spans = exporter.get_finished_spans()
    assert len(spans) == 1, [s.name for s in spans]
    return spans[0]


def test_span_carries_its_name_and_attributes(exporter):
    with deus_obs.span("build_playlist", kind="CHAIN", genre="techno", count=3):
        pass
    span = only(exporter)
    assert span.name == "build_playlist"
    assert span.attributes["openinference.span.kind"] == "CHAIN"
    assert span.attributes["genre"] == "techno"
    assert span.attributes["count"] == 3


def test_resource_carries_the_project_name(exporter):
    with deus_obs.span("x"):
        pass
    resource = only(exporter).resource.attributes
    assert resource["openinference.project.name"] == "deus-obs-tests"
    assert resource["service.name"] == "deus-obs"


def test_tool_decorator_records_kind_and_tool_name(exporter):
    @deus_obs.tool
    def pick_track(genre: str) -> str:
        return genre

    pick_track("lofi")
    span = only(exporter)
    assert span.name == "pick_track"
    assert span.attributes["openinference.span.kind"] == "TOOL"
    assert span.attributes["tool.name"] == "pick_track"


def test_metadata_capture_records_argument_names_and_no_values(exporter, capture):
    capture("metadata")

    @deus_obs.tool
    def pick_track(genre: str, context_variables: dict) -> str:
        return "picked"

    pick_track("lofi", {"api_key": "sk-secret"})
    span = only(exporter)
    assert list(span.attributes["deus_obs.input.args"]) == ["genre", "context_variables"]
    assert "input.value" not in span.attributes
    assert span.attributes["deus_obs.output.type"] == "str"
    assert "sk-secret" not in str(span.attributes)


def test_off_capture_records_neither(exporter, capture):
    capture("off")

    @deus_obs.tool
    def pick_track(genre: str) -> str:
        return "picked"

    pick_track("lofi")
    attrs = only(exporter).attributes
    assert "deus_obs.input.args" not in attrs
    assert "deus_obs.output.type" not in attrs


def test_preview_capture_records_values_but_redacts_the_dangerous_ones(exporter, capture):
    capture("preview")

    @deus_obs.tool
    def pick_track(genre: str, context_variables: dict) -> str:
        return "picked"

    pick_track("lofi", {"api_key": "sk-secret"})
    attrs = only(exporter).attributes
    assert "lofi" in attrs["input.value"]
    assert "<redacted>" in attrs["input.value"]
    assert "sk-secret" not in attrs["input.value"]
    assert attrs["output.value"] == "picked"


def test_preview_capture_truncates(exporter, capture):
    capture("preview")

    @deus_obs.tool
    def echo(blob: str) -> str:
        return blob

    echo("x" * 5_000)
    value = only(exporter).attributes["output.value"]
    assert len(value) < 400 and value.endswith("<5000 chars>")


def test_session_scope_is_stamped_on_every_span_inside(exporter):
    with deus_obs.session_scope("sess-42", user_id="pablo", genre="techno"):
        with deus_obs.span("outer"):
            with deus_obs.span("inner"):
                pass
    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} == {"outer", "inner"}
    for span in spans:
        assert span.attributes["session.id"] == "sess-42"
        assert span.attributes["user.id"] == "pablo"
        assert span.attributes["metadata"] == '{"genre": "techno"}'


def test_session_scope_does_not_leak_out_of_its_block(exporter):
    with deus_obs.session_scope("sess-42"):
        pass
    with deus_obs.span("after"):
        pass
    assert "session.id" not in only(exporter).attributes


def test_exceptions_are_recorded_and_re_raised(exporter):
    @deus_obs.tool
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        boom()
    span = only(exporter)
    assert span.status.status_code.name == "ERROR"
    assert [e.name for e in span.events] == ["exception"]


def test_current_trace_id_matches_the_open_span(exporter):
    assert deus_obs.current_trace_id() is None  # nothing open
    with deus_obs.span("x"):
        trace_id = deus_obs.current_trace_id()
        assert trace_id is not None and len(trace_id) == 32
    assert trace_id == format(only(exporter).context.trace_id, "032x")


def test_suppress_silences_everything_inside_it(exporter):
    from deus_obs.api import suppress

    @deus_obs.tool
    def pick(x):
        return x

    with suppress():
        with deus_obs.span("outer"):
            assert pick(1) == 1
    assert exporter.get_finished_spans() == ()
    pick(2)
    assert only(exporter).name == "pick"


def test_async_tools_open_a_span(exporter):
    @deus_obs.tool
    async def fetch(track_id: str) -> str:
        return track_id

    # asyncio.run rather than pytest-asyncio: the package's test suite must
    # install from `deus-obs[otel]` alone, with no plugin of its own.
    assert asyncio.run(fetch("abc")) == "abc"
    assert only(exporter).name == "fetch"
