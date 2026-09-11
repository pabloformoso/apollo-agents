"""The helpers application code actually calls. Imports no opentelemetry.

Everything here works identically whether or not the SDK exists in the
environment: it asks ``runtime`` for a tracer and, when there is none, takes a
branch that allocates nothing. That is what lets ``@tool`` sit on a function at
module-import time in a process that will never configure telemetry.

WHY THE DECORATORS WRAP EVEN WHEN DISABLED
The obvious reading of "no-op" is to return the function unchanged. It is the
wrong one here, and the reason is ordering: Apollo decorates its tool functions
when ``agent/tools.py`` is imported, and calls ``install()`` later, inside the
FastAPI lifespan. A decorator that decided at import time would decide "never"
for every tool in the process, and the traces an operator went to the trouble
of configuring would silently never appear. So the decision is made per call,
behind one ``is None`` test against a module global — and the wrapper is
transparent in every way a caller can observe, including the one Apollo depends
on. ``agent/run.py`` builds its LLM tool schemas by reflecting over
``inspect.signature``, ``__name__`` and ``__doc__``; ``functools.wraps`` sets
``__wrapped__``, which ``inspect.signature`` follows, so the reflected schema is
byte-for-byte what it was. Losing that would not raise anything — it would
quietly hand every model a tool with no parameters.
"""

from __future__ import annotations

import contextlib
import functools
from typing import Any, Callable, Iterator

from . import _noop, runtime

# What ``inspect.iscoroutinefunction`` and friends read, without importing
# ``inspect`` — 12 of the 21 ms that ``import deus_obs`` would otherwise cost,
# in a package whose first claim is that importing it costs nothing. These are
# the CPython code-object flags and they are what those helpers check.
_CO_GENERATOR = 0x20
_CO_COROUTINE = 0x80
_CO_ASYNC_GENERATOR = 0x200

# --- OpenInference attribute names ------------------------------------------
# Literal strings, not a semantic-conventions dependency. They are four names
# from a published spec, and a zero-dependency package does not take on a
# dependency to spell four constants it could get wrong in exactly one place.
SPAN_KIND = "openinference.span.kind"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"
TOOL_NAME = "tool.name"
SESSION_ID = "session.id"
USER_ID = "user.id"
METADATA = "metadata"

#: How much of a value ``preview`` keeps, and the hard ceiling ``full`` obeys.
#: ``full`` still has one: a tool that returns decoded audio would otherwise
#: put megabytes per span on the wire and take the collector down with it.
PREVIEW_LIMIT = 256
FULL_LIMIT = 32_768

#: Substrings that redact an argument's VALUE at preview/full. Apollo passes
#: ``context_variables`` — which carries API keys — into every agent tool, so
#: this is not hypothetical. Deliberately does not include a bare "key":
#: ``camelot_key`` is the interesting half of a transition and redacting it
#: would make the traces useless to avoid a leak that is not there.
_REDACT_MARKERS = (
    "context_variables",
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "credential",
    "private",
)


def _redacted(name: str) -> bool:
    lower = name.lower()
    return any(marker in lower for marker in _REDACT_MARKERS)


def _describe(value: Any, limit: int) -> str:
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:
        return "<unrepresentable>"
    if len(text) > limit:
        return f"{text[:limit]}...<{len(text)} chars>"
    return text


def _coerce(value: Any) -> Any:
    """OTel accepts str/bool/int/float and homogeneous sequences of those."""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(v, (str, bool, int, float)) for v in value
    ):
        return list(value)
    return _describe(value, PREVIEW_LIMIT)


def _param_names(fn: Callable[..., Any]) -> tuple[str, ...]:
    """Positional parameter names, without paying for inspect.signature.

    ``signature()`` builds Parameter objects and is the expensive call in
    ``inspect``; this runs at decoration time on every decorated function in a
    module, so it reads the code object directly. Missing ``__code__`` (a
    builtin, a callable object) simply means no names — never an error.

    Note this is about what the decorator RECORDS. What the decorated function
    reports to ``inspect.signature`` is untouched: ``functools.wraps`` sets
    ``__wrapped__`` and ``signature()`` follows it to the original.
    """
    code = getattr(fn, "__code__", None)
    if code is None:
        return ()
    return tuple(code.co_varnames[: code.co_argcount])


def _co_flags(fn: Callable[..., Any]) -> int:
    code = getattr(fn, "__code__", None)
    return getattr(code, "co_flags", 0)


# --- suppression ------------------------------------------------------------


@contextlib.contextmanager
def suppress() -> Iterator[None]:
    """Silence span creation for this context (and anything it awaits).

    For the loops that would otherwise dominate a trace and say nothing: a
    per-frame audio callback, a poll, a retry storm. Not part of the ten-name
    public API — reach for it as ``deus_obs.api.suppress`` and think about why
    the spans are noise before you hide them.
    """
    token = runtime.SUPPRESS.set(True)
    try:
        yield
    finally:
        runtime.SUPPRESS.reset(token)


def _off() -> bool:
    """True when nothing should be recorded right now, as cheaply as possible."""
    return runtime.active_tracer() is None or runtime.SUPPRESS.get()


# --- tracer / span ----------------------------------------------------------


def tracer(name: str | None = None) -> Any:
    """The tracer to open spans on — the real one, or one that records nothing.

    Never returns ``None``, so call sites do not branch. The no-op is this
    package's own (see ``_noop``) and not OpenTelemetry's, because reaching
    OpenTelemetry's would mean importing OpenTelemetry.
    """
    found = runtime.get_tracer(name)
    return found if found is not None else _noop.NOOP_TRACER


def span(name: str, *, kind: str | None = None, **attributes: Any) -> Any:
    """Open a span as a context manager. A no-op when unconfigured.

    ``with deus_obs.span("build_playlist", genre=genre) as sp: ...``

    Exceptions keep OpenTelemetry's defaults: recorded on the span and the
    status set to ERROR, then re-raised untouched.
    """
    if _off():
        return _noop.noop_span()
    attrs: dict[str, Any] = {k: _coerce(v) for k, v in attributes.items()}
    if kind:
        attrs[SPAN_KIND] = kind
    return runtime.active_tracer().start_as_current_span(name, attributes=attrs)


# --- decorators -------------------------------------------------------------


def _wrap(
    fn: Callable[..., Any],
    kind: str,
    span_name: str | None,
    attributes: dict[str, Any],
) -> Callable[..., Any]:
    flags = _co_flags(fn)
    if flags & (_CO_GENERATOR | _CO_ASYNC_GENERATOR):
        return _noop.passthrough(fn)

    name = span_name or getattr(fn, "__name__", "anonymous")
    static: dict[str, Any] = {SPAN_KIND: kind}
    if kind == "TOOL":
        static[TOOL_NAME] = name
    static.update({k: _coerce(v) for k, v in attributes.items()})
    params = _param_names(fn)

    def _attrs(args: tuple, kwargs: dict) -> dict[str, Any]:
        capture = runtime.config().capture
        attrs = dict(static)
        if capture == "off":
            return attrs
        names = list(params[: len(args)]) + list(kwargs)
        if capture == "metadata":
            # Names, never values. Enough to see WHICH arguments a call was
            # given without putting any of them in a shared trace store.
            if names:
                attrs["deus_obs.input.args"] = names
            return attrs
        limit = PREVIEW_LIMIT if capture == "preview" else FULL_LIMIT
        bound = {
            key: "<redacted>" if _redacted(key) else _describe(value, limit)
            for key, value in list(zip(params, args)) + list(kwargs.items())
        }
        attrs[INPUT_VALUE] = _describe(bound, limit)
        return attrs

    def _output(sp: Any, result: Any) -> None:
        capture = runtime.config().capture
        if capture in ("off", "metadata"):
            if capture == "metadata":
                sp.set_attribute("deus_obs.output.type", type(result).__name__)
            return
        limit = PREVIEW_LIMIT if capture == "preview" else FULL_LIMIT
        sp.set_attribute(OUTPUT_VALUE, _describe(result, limit))

    if flags & _CO_COROUTINE:

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _off():
                return await fn(*args, **kwargs)
            with runtime.active_tracer().start_as_current_span(
                name, attributes=_attrs(args, kwargs)
            ) as sp:
                result = await fn(*args, **kwargs)
                _output(sp, result)
                return result

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if _off():
            return fn(*args, **kwargs)
        with runtime.active_tracer().start_as_current_span(
            name, attributes=_attrs(args, kwargs)
        ) as sp:
            result = fn(*args, **kwargs)
            _output(sp, result)
            return result

    return wrapper


def _decorator(kind: str) -> Callable[..., Any]:
    def decorator(fn: Any = None, *, name: str | None = None, **attributes: Any) -> Any:
        # Bare (@tool), named positionally (@tool("pick_track")) and by keyword
        # (@tool(name=...)) all reach the same place. Supported because the
        # bare form is the one that gets typed and the parenthesised form is
        # the one that silently produces a decorator object when it is not.
        if isinstance(fn, str):
            name, fn = fn, None
        if fn is None:
            return lambda target: _wrap(target, kind, name, attributes)
        return _wrap(fn, kind, name, attributes)

    return decorator


#: A leaf: one function call, one external effect. Apollo's agent tools.
tool = _decorator("TOOL")
#: A composed step: several calls that mean one thing together.
chain = _decorator("CHAIN")
#: A loop that decides what to do next — the orchestrator, not its steps.
agent = _decorator("AGENT")


# --- session ----------------------------------------------------------------


@contextlib.contextmanager
def session_scope(
    session_id: str, *, user_id: str | None = None, **metadata: Any
) -> Iterator[dict]:
    """Bind a session for the duration of a block; spans inside carry it.

    Works with or without the SDK — the binding is a stdlib ContextVar, and an
    uninstalled process simply has nothing reading it. Stamping happens in a
    span processor rather than here, so it also reaches spans this package did
    not open (the LLM instrumentors', for one). Because it is a ContextVar it
    follows ``await`` and ``asyncio.create_task`` into the work a request
    spawns, which is the only way a live session's spans stay together.
    """
    scope: dict[str, Any] = {SESSION_ID: str(session_id)}
    if user_id:
        scope[USER_ID] = str(user_id)
    if metadata:
        import json  # only this one call site needs it

        try:
            scope[METADATA] = json.dumps({k: _coerce(v) for k, v in metadata.items()})
        except Exception:
            scope[METADATA] = _describe(metadata, PREVIEW_LIMIT)
    token = runtime.SESSION.set(scope)
    try:
        yield scope
    finally:
        runtime.SESSION.reset(token)


def current_trace_id() -> str | None:
    """The active trace id as 32 hex chars, or ``None``.

    For putting a "find this in the trace store" handle into a log line or an
    error response. Returns ``None`` — importing nothing — whenever tracing is
    not installed, so a caller can log it unconditionally.
    """
    if runtime.active_tracer() is None:
        return None
    from opentelemetry import trace as otel_trace

    ctx = otel_trace.get_current_span().get_span_context()
    if ctx is None or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")
