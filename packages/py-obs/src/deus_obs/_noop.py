"""What every helper collapses to when nothing is configured.

OpenTelemetry ships its own no-op tracer, and it is genuinely free — AFTER you
have paid for ``import opentelemetry.sdk`` and the protobuf runtime behind it.
Measured on this machine (median of 7 fresh interpreters, warm caches): 9.7 ms
for ``python -c pass``, 101.6 ms once the SDK and the OTLP/HTTP exporter are
imported. That ~90 ms lands on every pytest collection and every ``python
main.py --build-catalog``, neither of which asked for telemetry. So the no-op
here is ours: eighty lines of stdlib that answer the same calls and import
nothing.

The objects are singletons and the methods return ``None`` without touching an
argument. Nothing is allocated on the disabled path, which is the path a
library like this one spends almost all of its life on.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class NoOpSpan:
    """Answers the span API and remembers nothing.

    Doubles as its own context manager so ``start_as_current_span`` can hand
    the singleton straight back without building a generator-based one.
    """

    __slots__ = ()

    def set_attribute(self, key: Any, value: Any) -> None:
        return None

    def set_attributes(self, attributes: Any) -> None:
        return None

    def add_event(self, name: Any, attributes: Any = None, timestamp: Any = None) -> None:
        return None

    def record_exception(self, exception: Any, **kwargs: Any) -> None:
        return None

    def set_status(self, status: Any, description: Any = None) -> None:
        return None

    def update_name(self, name: Any) -> None:
        return None

    def end(self, end_time: Any = None) -> None:
        return None

    def is_recording(self) -> bool:
        return False

    def get_span_context(self) -> None:
        return None

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False


class NoOpTracer:
    """Answers the tracer API with the no-op span, for any arguments."""

    __slots__ = ()

    def start_span(self, name: Any, *args: Any, **kwargs: Any) -> NoOpSpan:
        return NOOP_SPAN

    def start_as_current_span(self, name: Any, *args: Any, **kwargs: Any) -> NoOpSpan:
        return NOOP_SPAN


NOOP_SPAN = NoOpSpan()
NOOP_TRACER = NoOpTracer()


def noop_span() -> NoOpSpan:
    """The context manager ``span()`` returns when there is nothing to record."""
    return NOOP_SPAN


def passthrough(fn: F) -> F:
    """Return the function unchanged — the decorator that adds nothing.

    Used for generator and async-generator functions. A span wrapped around
    one of those would open when the generator is *created* and close on the
    first ``next()``, so it would time the setup and attribute none of the
    work — a span that is present, plausible and wrong, which is worse than
    absent. Wrapping them properly means owning the generator protocol
    (throw/close/asend), and that is not a decision to make silently inside a
    decorator that Apollo applies at module-import time.
    """
    return fn
