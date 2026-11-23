"""Apollo's one door to ``deus_obs`` — spans that cost nothing when unconfigured.

Every instrumented call site in ``agent/`` and ``web/backend/`` imports THIS
module, never ``deus_obs`` directly, for one reason: the ``obs`` dependency
group is deliberately not in ``default-groups``, so CI and every plain
``uv sync`` run with the package ABSENT. An unguarded ``import deus_obs`` in
``generator.py`` would break the backend for everyone who has not opted in.
The guard lives here once instead of at every call site.

What this module records, and what it never does
------------------------------------------------
Only METADATA, whatever ``OBS_CAPTURE`` says: model names, providers, token
counts, durations, sizes, outcomes, the NAMES of a tool's arguments. Never a
prompt, a completion, a tool's argument values or its result. Apollo hands
``context_variables`` (API keys among it) to every tool, prompts carry viewers'
chat messages, and the Phoenix on jarvis is shared with two other projects. A
content-capturing LLM span is a decision for its own change — the call sites
below are written so that adding one is a single ``set_attribute`` behind the
capture level, not a re-plumb.

Attribute names follow OpenInference (``llm.model_name``,
``llm.token_count.*``, ``openinference.span.kind``) so Phoenix renders LLM
spans with its own model and token columns. Apollo's own attributes are
prefixed ``apollo.``.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
from typing import Any, Callable, Iterator, Mapping, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    import deus_obs
except ModuleNotFoundError:  # pragma: no cover - the uninstrumented install
    # See the module docstring. This guard must stay.
    deus_obs = None


# --- OpenInference attribute names -------------------------------------------
LLM_MODEL = "llm.model_name"
LLM_PROVIDER = "llm.provider"
LLM_SYSTEM = "llm.system"
TOKENS_PROMPT = "llm.token_count.prompt"
TOKENS_COMPLETION = "llm.token_count.completion"
TOKENS_TOTAL = "llm.token_count.total"

#: Apollo's provider words -> OpenInference's ``llm.provider`` / ``llm.system``.
#: Phoenix groups and costs LLM spans by these. A provider not in the map is
#: passed through as-is: a wrong-looking label beats a missing one.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "anthropic": ("anthropic", "anthropic"),
    "azure": ("azure", "openai"),
    "openai": ("openai", "openai"),
    "ollama": ("lmstudio", "openai"),  # Apollo's name for the local LM Studio
    "lmstudio": ("lmstudio", "openai"),
    "litellm": ("litellm", "openai"),
}


class _NullSpan:
    """What a call site holds when nothing is installed. Remembers nothing."""

    __slots__ = ()

    def set_attribute(self, key: Any, value: Any) -> None:
        return None

    def set_attributes(self, attributes: Any) -> None:
        return None

    def add_event(self, name: Any, attributes: Any = None, timestamp: Any = None) -> None:
        return None

    def is_recording(self) -> bool:
        return False


NULL_SPAN = _NullSpan()


def enabled() -> bool:
    """True when spans are actually being recorded in this process."""
    if deus_obs is None:
        return False
    from deus_obs import runtime  # noqa: PLC0415 — stdlib-only module

    return runtime.active_tracer() is not None


def _clean(attrs: Mapping[str, Any]) -> dict[str, Any]:
    # OTel rejects None outright (and logs about it); a missing attribute is
    # the honest spelling of "unknown".
    return {k: v for k, v in attrs.items() if v is not None}


@contextlib.contextmanager
def span(name: str, *, kind: str = "CHAIN", **attrs: Any) -> Iterator[Any]:
    """A span around a block. Yields an object with ``set_attribute``.

    ``kind`` is the OpenInference span kind: CHAIN for a composed step, LLM
    for one model call, TOOL for one tool execution. Pass dotted attribute
    names through a dict: ``span("x", **{"apollo.genre": g})``.

    An exception inside the block is recorded on the span (status ERROR) and
    re-raised untouched — that is ``deus_obs.span``'s behaviour.
    """
    if deus_obs is None:
        yield NULL_SPAN
        return
    with deus_obs.span(name, kind=kind, **_clean(attrs)) as sp:
        yield sp


def provider_labels(provider: str | None) -> tuple[str | None, str | None]:
    """Apollo's provider word -> (``llm.provider``, ``llm.system``)."""
    if not provider:
        return None, None
    return _PROVIDERS.get(provider.lower(), (provider, None))


def llm_span(
    name: str,
    *,
    provider: str | None,
    model: str | None,
    **attrs: Any,
) -> contextlib.AbstractContextManager[Any]:
    """A span around ONE model call, labelled the way Phoenix reads LLM spans."""
    llm_provider, llm_system = provider_labels(provider)
    return span(
        name,
        kind="LLM",
        **{
            LLM_MODEL: model,
            LLM_PROVIDER: llm_provider,
            LLM_SYSTEM: llm_system,
            "apollo.provider": provider,
        },
        **attrs,
    )


def usage_attributes(usage: Any) -> dict[str, int]:
    """Token counts from either SDK's ``usage`` object, as span attributes.

    OpenAI-shaped (``prompt_tokens`` / ``completion_tokens`` /
    ``total_tokens``) and Anthropic-shaped (``input_tokens`` /
    ``output_tokens``) both work; a dict works too. Anything missing is left
    out rather than guessed. Pure: testable without the SDK.
    """
    if usage is None:
        return {}

    def _read(*names: str) -> int | None:
        for n in names:
            value = usage.get(n) if isinstance(usage, Mapping) else getattr(usage, n, None)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    prompt = _read("prompt_tokens", "input_tokens")
    completion = _read("completion_tokens", "output_tokens")
    total = _read("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    out: dict[str, int] = {}
    if prompt is not None:
        out[TOKENS_PROMPT] = prompt
    if completion is not None:
        out[TOKENS_COMPLETION] = completion
    if total is not None:
        out[TOKENS_TOTAL] = total
    return out


def record_usage(sp: Any, response: Any) -> None:
    """Copy a response's token counts onto ``sp``. Never raises."""
    try:
        for key, value in usage_attributes(getattr(response, "usage", None)).items():
            sp.set_attribute(key, value)
    except Exception:  # noqa: BLE001 — telemetry must not break the call it observes
        pass


def tool_span(name: str, inputs: Mapping[str, Any] | None) -> contextlib.AbstractContextManager[Any]:
    """A span around one agent tool execution: its name and argument NAMES.

    Values are never recorded — see the module docstring. The names alone say
    which branch of a tool the model asked for (``pick_next_track(bpm_min,
    bpm_max, key)``), which is the question a trace is opened to answer.
    """
    arg_names = sorted(str(k) for k in (inputs or {}))
    return span(
        name,
        kind="TOOL",
        **{"tool.name": name, "deus_obs.input.args": arg_names or None},
    )


def set_attrs(sp: Any, **attrs: Any) -> None:
    """``set_attribute`` for several values, skipping ``None``. Never raises."""
    try:
        for key, value in _clean(attrs).items():
            sp.set_attribute(key, value)
    except Exception:  # noqa: BLE001
        pass


def mark_error(sp: Any, exc: BaseException | str) -> None:
    """Flag ``sp`` as failed for an error the caller handles and does not raise.

    ``deus_obs.span`` sets ERROR only for an exception that LEAVES the block;
    Apollo swallows most of its errors on purpose (a poll never 5xx, a
    critique degrades to ``null``), and those spans would otherwise read
    green in Phoenix. Never raises.
    """
    if not getattr(sp, "is_recording", lambda: False)():
        return
    try:
        from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415 — only when recording

        if isinstance(exc, BaseException):
            sp.record_exception(exc)
            description = f"{type(exc).__name__}: {exc}"
        else:
            description = str(exc)
        sp.set_attribute("apollo.error", description[:256])
        sp.set_status(Status(StatusCode.ERROR, description[:256]))
    except Exception:  # noqa: BLE001
        pass


def current_span() -> Any:
    """The span the calling code is inside, or the null span. Never ``None``."""
    if not enabled():
        return NULL_SPAN
    from opentelemetry import trace as otel_trace  # noqa: PLC0415 — only when recording

    return otel_trace.get_current_span()


def annotate(**attrs: Any) -> None:
    """Add attributes to the CURRENT span — for code under :func:`traced`.

    Free when nothing is recording: one ``is None`` test and a return.
    """
    if not enabled():
        return
    set_attrs(current_span(), **attrs)


def _note_exception(sp: Any, exc: BaseException) -> None:
    # A FastAPI HTTPException (or anything shaped like one) carries the
    # answer the client got. Duck-typed so this module never imports FastAPI.
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        set_attrs(sp, **{"http.status_code": code})


def traced(name: str, *, kind: str = "CHAIN", **static: Any) -> Callable[[F], F]:
    """Decorate a function (sync or async) with a span named ``name``.

    For FastAPI handlers whose bodies are too long to re-indent under a
    ``with``: ``functools.wraps`` sets ``__wrapped__``, and FastAPI reads
    the handler's parameters through ``inspect.signature``, which follows
    it, so the route's dependencies and body model are untouched. Put it
    UNDER ``@router.post(...)``. Inside, :func:`annotate` adds to the span.

    An exception that leaves the function is recorded (status ERROR) and
    re-raised; an ``HTTPException``'s status code is put on the span first,
    so a 409 VRAM refusal and a 502 from ACE are told apart in Phoenix.
    Generator functions are returned unchanged — a span around one would
    time its creation, not its work (``deus_obs``'s rule).
    """

    def decorator(fn: F) -> F:
        if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
            return fn
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if deus_obs is None:
                    return await fn(*args, **kwargs)
                with span(name, kind=kind, **static) as sp:
                    try:
                        return await fn(*args, **kwargs)
                    except BaseException as exc:
                        _note_exception(sp, exc)
                        raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if deus_obs is None:
                return fn(*args, **kwargs)
            with span(name, kind=kind, **static) as sp:
                try:
                    return fn(*args, **kwargs)
                except BaseException as exc:
                    _note_exception(sp, exc)
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator
