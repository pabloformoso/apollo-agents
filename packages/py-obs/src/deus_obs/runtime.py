"""Process-level state, and the only module in this package that imports the SDK.

THE RULE THIS FILE EXISTS TO ENFORCE
Every ``opentelemetry`` import in ``deus_obs`` is inside a function body here,
BELOW the endpoint check. "Unconfigured" therefore means the SDK was never
imported, not that a no-op object was returned by one. The difference, measured
on this machine over 7 fresh interpreters: 25 ms for ``import deus_obs`` plus
an unconfigured ``install()``, 107 ms for a configured one. That ~80 ms is paid
by every pytest collection and every CLI run in a repo where most processes
will never emit a span. If you are editing this file and reaching for an import
at module scope, that is the thing you are about to undo.

IDEMPOTENCE, AND WHY A MODULE SENTINEL IS NOT ENOUGH
``set_tracer_provider`` is set-once: a second call does not replace the global,
it logs a warning and returns. So a second ``install()`` cannot overwrite a bad
provider — but it CAN stack a second ``BatchSpanProcessor`` on the good one, and
then every span is exported twice, forever, to a shared trace store. Two things
guard it: ``_INSTALLED``, which catches a repeat call inside one module
generation, and an ``isinstance(get_tracer_provider(), SDKTracerProvider)``
check, which catches the case the sentinel cannot see — modules re-imported
into a process that has already been running (uvicorn --reload), where the
sentinel is fresh and the provider is not.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from .config import ObsConfig

#: Instrumentation scope name — what Phoenix shows as the span's library.
TRACER_NAME = "deus_obs"

#: Stamped on a provider we installed, so a later install() can tell "mine,
#: live" from "mine, already drained" from "somebody else's".
_MARKER = "_deus_obs_state"

_INSTALLED = False
_PROVIDER: Any | None = None
_TRACER: Any | None = None
_CONFIG: ObsConfig | None = None

#: Bound by api.session_scope(); read by the span processor at on_start. A
#: ContextVar is stdlib, so this works — and stays empty — in a process that
#: never installs anything.
SESSION: ContextVar[dict | None] = ContextVar("deus_obs_session", default=None)
SUPPRESS: ContextVar[bool] = ContextVar("deus_obs_suppress", default=False)


def active_tracer() -> Any | None:
    """The real tracer, or ``None`` when nothing is installed.

    ``None`` rather than the no-op tracer on purpose: it is the fast path the
    decorators branch on, and identity against ``None`` is the cheapest test
    Python has.
    """
    return _TRACER


def get_tracer(name: str | None = None) -> Any | None:
    if _PROVIDER is None or name is None:
        return _TRACER
    return _PROVIDER.get_tracer(name)


def config() -> ObsConfig:
    """The config of the last install(), or a never-installed placeholder."""
    if _CONFIG is not None:
        return _CONFIG
    return ObsConfig(endpoint=None, project="", service="", reason="install() has not run")


def install(
    endpoint: str | None = None,
    *,
    project: str | None = None,
    service: str | None = None,
    env: Any | None = None,
) -> ObsConfig:
    """Configure tracing for this process and return what was actually done.

    Returns the EFFECTIVE config, not a tracer: the caller needs to print one
    honest line at startup, and a tracer cannot say whether it is wired to a
    collector, whether the SDK was even importable, or which project the spans
    will land in. ``tracer()`` is a separate call for the separate need.

    Never raises and never prints. A telemetry bootstrap that can take down the
    application it observes is a liability, and a library that writes to stdout
    takes that decision away from its host — the returned config carries the
    outcome and the host decides what to do with it. In particular, with the
    ``[otel]`` extra not installed this returns a disabled config in silence,
    which is the whole reason ``import deus_obs`` is safe to put in a CLI.
    """
    global _CONFIG

    cfg = ObsConfig.from_env(endpoint, project=project, service=service, env=env)
    if not cfg.enabled:
        # NOTHING above this line imported opentelemetry, and nothing below it
        # runs. This early return is the package's central promise.
        _CONFIG = cfg
        return cfg

    if _INSTALLED:
        return _CONFIG if _CONFIG is not None else cfg

    try:
        cfg = _install_sdk(cfg)
    except ImportError:
        cfg = cfg.disabled("opentelemetry is not installed (pip install deus-obs[otel])")
    except Exception as exc:  # exporter construction, a malformed URL, ...
        cfg = cfg.disabled(f"{type(exc).__name__}: {exc}")

    _CONFIG = cfg
    return cfg


def _install_sdk(cfg: ObsConfig) -> ObsConfig:
    """Build and register the provider. Only reached with an endpoint in hand."""
    global _INSTALLED, _PROVIDER, _TRACER

    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    existing = otel_trace.get_tracer_provider()
    if isinstance(existing, SDKTracerProvider):
        return _adopt(existing, cfg)

    resource = Resource.create(
        {
            "service.name": cfg.service,
            # This one attribute is the entire reason the vendor's own
            # bootstrap package exists. It is a string on a Resource; it does
            # not justify a dependency named after a company in a package whose
            # premise is that it moves between projects.
            "openinference.project.name": cfg.project,
        }
    )
    provider = SDKTracerProvider(resource=resource, sampler=_sampler(cfg))
    # Added first so it stamps on_start, before anything can export.
    provider.add_span_processor(_scope_processor())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.endpoint)))
    if cfg.console:
        provider.add_span_processor(_console_processor())

    setattr(provider, _MARKER, "live")
    otel_trace.set_tracer_provider(provider)

    _PROVIDER = provider
    _TRACER = provider.get_tracer(TRACER_NAME)
    _INSTALLED = True
    return cfg


def _adopt(provider: Any, cfg: ObsConfig) -> ObsConfig:
    """Reuse a TracerProvider that is already global, instead of stacking on it.

    Three ways to get here, and they need different endings:

    * ours and live — a reload, or a second lifespan in one process. Attach
      nothing: the processors from the first install are still running, and a
      second BatchSpanProcessor would double every span.
    * ours and drained — install() after shutdown(), which happens when a test
      builds several apps. The provider is still the global one and cannot be
      replaced, so re-arm it with fresh processors; a shut-down processor
      accepts spans and drops them, which would be silent loss.
    * somebody else's — another bootstrap got here first. Ride along rather
      than fight over a set-once global, and say so in the status line: the
      spans will carry THEIR resource, so they will land in their project, and
      an operator staring at an empty project needs that sentence.
    """
    global _INSTALLED, _PROVIDER, _TRACER

    state = getattr(provider, _MARKER, None)
    reason = ""
    if state == "shutdown":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.endpoint)))
        setattr(provider, _MARKER, "live")
        reason = "re-armed the existing provider (resource fixed at first install)"
    elif state is None:
        reason = "attached to a TracerProvider installed by something else"

    _PROVIDER = provider
    _TRACER = provider.get_tracer(TRACER_NAME)
    _INSTALLED = True
    return replace(cfg, reason=reason)


def _sampler(cfg: ObsConfig) -> Any | None:
    if cfg.sample_ratio >= 1.0:
        return None  # the SDK's own default, which also reads OTEL_TRACES_SAMPLER
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    # ParentBased so a sampled parent keeps its children: independently
    # sampling each span would shred traces into unreadable fragments.
    return ParentBased(TraceIdRatioBased(cfg.sample_ratio))


def _console_processor() -> Any:
    """Console debugging, and the one place SimpleSpanProcessor is correct.

    The rule against SimpleSpanProcessor is about the network exporter: it puts
    an HTTP round-trip in the caller's thread on every span, so a tool call
    pays for the collector's latency. Writing to stdout has no round-trip, and
    batching it would defeat the only reason OBS_CONSOLE exists — seeing the
    span when it happens, not five seconds later.
    """
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    return SimpleSpanProcessor(ConsoleSpanExporter())


def _scope_processor() -> Any:
    """Stamp the session scope on every span, from context, never from call sites.

    A contract enforced at every call site is a contract that will eventually
    be forgotten, and a span written without its ``session.id`` cannot be
    repaired afterwards — it is simply lost from its session. Doing it in a
    processor also covers spans this package did not open: the LLM
    instrumentors of the ``[llm]`` extra emit their own, and those are exactly
    the ones an operator wants filtered by session.
    """
    from opentelemetry.sdk.trace import SpanProcessor

    class _ScopeProcessor(SpanProcessor):
        def on_start(self, span: Any, parent_context: Any = None) -> None:
            try:
                scope = SESSION.get()
                if scope:
                    span.set_attributes(scope)
            except Exception:
                # A telemetry fault must never become an application fault.
                pass

        def on_end(self, span: Any) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            return True

    return _ScopeProcessor()


def flush(timeout_millis: int = 5_000) -> bool:
    """Push whatever the batch processor still buffers to the collector, now.

    Returns True if a provider was asked to flush. Imports nothing when nothing
    was installed, which is what makes it safe to call unconditionally.

    The batch exporter ships on a five-second schedule, so the spans of a
    process's last seconds sit in the buffer when the signal arrives. The
    provider's own atexit hook is supposed to cover that and observably does
    not under uvicorn's exit path — the eOS broker's rehearsal of 2026-08-27
    delivered every span except the last two, every time. A trace store that
    holds everything except the end of the session is worse than an empty one:
    it looks like coverage.
    """
    provider = _PROVIDER
    if provider is None:
        return False
    force = getattr(provider, "force_flush", None)
    if not callable(force):
        return False
    try:
        force(timeout_millis)
    except Exception:
        return False
    return True


def shutdown(timeout_millis: int = 5_000) -> None:
    """Flush and stop. Safe to call when install() never ran, or ran disabled.

    Marks the provider drained rather than forgetting it, because the global
    TracerProvider cannot be replaced: a later install() in the same process
    has to be able to tell a provider it can re-arm from one it must leave
    alone. See ``_adopt``.
    """
    global _INSTALLED, _PROVIDER, _TRACER

    provider = _PROVIDER
    if provider is None:
        return
    flush(timeout_millis)
    try:
        provider.shutdown()
    except Exception:
        pass
    setattr(provider, _MARKER, "shutdown")
    _PROVIDER = None
    _TRACER = None
    _INSTALLED = False


def _reset_for_tests() -> None:
    """Forget this module's state. Tests only — the global provider survives."""
    global _INSTALLED, _PROVIDER, _TRACER, _CONFIG
    _INSTALLED = False
    _PROVIDER = None
    _TRACER = None
    _CONFIG = None
