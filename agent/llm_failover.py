"""Failover from the local LLM (gemma on LM Studio) to Azure OpenAI.

Why
---
The local model lives on a GPU shared with ACE-Step, and it is loaded,
unloaded and swapped from Settings. Every one of those moments is a
window in which LM Studio answers ``400 Failed to load model`` — or does
not answer at all — while ``/v1/models`` still lists the model. On the
2026-09-24 demo that left the brief parser returning all-null twice in a
minute (11:25/11:26 UTC) after a few model swaps. The OpenAI SDK retries
connection errors and 5xx, but never a 400, so nothing recovered.

What
----
A call that goes to the LOCAL endpoint and fails with an *outage*
(``is_local_outage``) is re-issued once against the Azure deployment
(``APOLLO_LLM_FAILOVER_DEPLOYMENT``, default ``AZURE_OPENAI_DEPLOYMENT`` —
``gpt-4o`` in prod). A request the local model *understood and refused*
is not an outage and is not re-sent: it would fail the same way on Azure,
and cost money doing it.

A failure also trips a process-wide breaker for
``APOLLO_LLM_FAILOVER_COOLDOWN_SEC`` (120 s): until it expires every call
goes straight to Azure. Without it the live DJ would pay the local
timeout on every turn of a set while LM Studio reloads. When the cooldown
ends the next call tries local again, and the log says when it is back.

Scope and switches
------------------
- Configured only when the Azure key, endpoint and a deployment are all
  set. ``APOLLO_LLM_FAILOVER=0`` turns it off (the test suite pins that;
  a test opts in).
- The model name is NEVER carried across: the local name
  (``google/gemma-4-e4b``) means nothing to Azure, and the Azure call
  always uses the deployment. Same rule as ``main_llm.persisted_model()``
  refusing to name an LM Studio model to a cloud provider.
- LM Studio-only request fields (``extra_body``) must not be forwarded;
  callers build the Azure request themselves.
- A stream that fails AFTER it started is not failed over — its text has
  already reached the audience. Only the call that opens it is.

Every failover is paid Azure usage. The log line names the deployment so
the cost is never invisible.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

#: Providers whose calls go to the local OpenAI-compatible endpoint.
LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio"})

DEFAULT_COOLDOWN_SEC = 120.0

#: Local calls get a short CONNECT timeout when a fallback exists, so a
#: dead LM Studio costs seconds rather than the SDK's 10 minutes. The read
#: budget stays generous: a healthy model may take a while to stream.
LOCAL_CONNECT_TIMEOUT_SEC = 5.0
LOCAL_READ_TIMEOUT_SEC = 90.0


def configured() -> bool:
    """True when a failover target exists and the switch is not off."""
    if os.getenv("APOLLO_LLM_FAILOVER", "1").strip().lower() in ("0", "false", "off", "no"):
        return False
    return bool(
        os.getenv("AZURE_OPENAI_API_KEY")
        and os.getenv("AZURE_OPENAI_ENDPOINT")
        and deployment()
    )


def deployment() -> str:
    """The Azure deployment a failed-over call uses."""
    return (
        os.getenv("APOLLO_LLM_FAILOVER_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()


def cooldown_sec() -> float:
    try:
        return max(0.0, float(os.getenv("APOLLO_LLM_FAILOVER_COOLDOWN_SEC", DEFAULT_COOLDOWN_SEC)))
    except ValueError:
        return DEFAULT_COOLDOWN_SEC


def local_timeout() -> Any:
    """Timeout for LOCAL clients while a fallback exists (else the SDK default)."""
    import httpx  # noqa: PLC0415 — already a dependency of openai

    return httpx.Timeout(LOCAL_READ_TIMEOUT_SEC, connect=LOCAL_CONNECT_TIMEOUT_SEC)


# ---------------------------------------------------------------------------
# What counts as "the local model is down"
# ---------------------------------------------------------------------------

#: Substrings of a 400/422 body that mean "the model is not there", as
#: opposed to "your request is wrong". LM Studio's wording, observed.
_MODEL_DOWN_MARKERS = (
    "failed to load model",
    "no models loaded",
    "model not found",
    "model is not loaded",
    "not a valid model",
    "model_not_found",
)


def is_local_outage(exc: BaseException) -> bool:
    """True if ``exc`` means the local LLM is unavailable, not the request bad.

    Outage: cannot connect / timed out, any 5xx, 404 (unknown model or
    route), 429, and a 400/422 whose message says the model will not load.
    Everything else — a malformed request, a schema the model rejected —
    propagates as before.
    """
    try:
        import openai  # noqa: PLC0415
    except ImportError:  # pragma: no cover — the SDK is a hard dependency
        return False

    if isinstance(exc, openai.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        if status >= 500 or status in (404, 429):
            return True
        if status in (400, 422):
            text = str(exc).lower()
            return any(m in text for m in _MODEL_DOWN_MARKERS)
    return False


def _describe(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    head = f"{type(exc).__name__}" + (f" {status}" if status else "")
    msg = " ".join(str(exc).split())
    return f"{head}: {msg[:140]}"


# ---------------------------------------------------------------------------
# Breaker — process-wide, so the live DJ, the planner and the critic agree
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_down_until = 0.0
_tripped = False


def local_down() -> bool:
    """True while the breaker holds calls on Azure."""
    with _lock:
        return time.monotonic() < _down_until


def trip(exc: BaseException, where: str) -> None:
    """Record a local outage; start (or extend) the cooldown."""
    global _down_until, _tripped
    cd = cooldown_sec()
    with _lock:
        first = not _tripped
        _tripped = True
        _down_until = time.monotonic() + cd
    verb = "failing over" if first else "still down"
    print(
        f"[llm-failover] {where}: local LLM {verb} ({_describe(exc)}) — "
        f"using Azure '{deployment()}' for the next {cd:g}s",
        flush=True,
    )


def note_local_ok(where: str) -> None:
    """A local call succeeded; say so once if we had failed over."""
    global _tripped
    with _lock:
        was = _tripped
        _tripped = False
    if was:
        print(f"[llm-failover] {where}: local LLM answering again — back on it", flush=True)


def reset() -> None:
    """Forget any outage (tests; a manual 'try local now')."""
    global _down_until, _tripped
    with _lock:
        _down_until = 0.0
        _tripped = False


# ---------------------------------------------------------------------------
# Clients and the one-shot wrappers
# ---------------------------------------------------------------------------

def azure_client(timeout: Any = None):
    from openai import AzureOpenAI  # noqa: PLC0415

    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        **kwargs,
    )


def async_azure_client(timeout: Any = None):
    from openai import AsyncAzureOpenAI  # noqa: PLC0415

    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        **kwargs,
    )


def call(where: str, local: Callable[[], T], azure: Callable[[], T]) -> T:
    """Run ``local``; on an outage (or while tripped) run ``azure`` instead.

    Callers pass this only for calls bound for the LOCAL endpoint and only
    when ``configured()``; ``azure`` must build its own request with
    ``deployment()`` as the model.
    """
    if local_down():
        return azure()
    try:
        result = local()
    except Exception as exc:
        if not is_local_outage(exc):
            raise
        trip(exc, where)
        return azure()
    note_local_ok(where)
    return result


async def acall(where: str, local: Callable[[], Any], azure: Callable[[], Any]) -> Any:
    """Async twin of ``call``: both arguments return awaitables."""
    if local_down():
        return await azure()
    try:
        result = await local()
    except Exception as exc:
        if not is_local_outage(exc):
            raise
        trip(exc, where)
        return await azure()
    note_local_ok(where)
    return result
