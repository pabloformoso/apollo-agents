"""Apollo G0 — async client for the ACE-Step 1.5 generation API.

Wraps the HTTP surface specified in ``docs/ACE-STEP-API-SPEC.md`` (the
ACE-Step repo is NOT modified; everything on the Apollo side is built
against that contract). Integration plan: ``docs/acestep-wizard-plan.md``.

Design rules this module exists to enforce
------------------------------------------

* **The generator may be OFF and that is a normal state.** The GPU is
  16 GB shared with the live DJ's LM Studio (the VRAM protocol), so the
  ACE-Step box is routinely down. ``ACESTEP_BASE_URL`` unset ⇒ the whole
  feature is disabled; :func:`enabled` says so without any network, and
  :meth:`AceStepClient.health` answers ``False`` instead of raising.
  Callers must render "generator unavailable", never an error page.
* **Env is read at CALL time, not import time.** Same lesson as
  ``brief_parser`` (see ``web/CLAUDE.md``): the backend runs under
  ``uvicorn --reload`` with a late-loaded ``.env``, so an import-time
  snapshot of ``os.environ`` silently pins the wrong value forever.
  There is deliberately **no** ``load_dotenv`` call at module scope.
* **The envelope is unwrapped here, once.** Every ACE-Step response is
  ``{data, code, error, timestamp, extra}``; callers get ``data``.
* **``429`` is a queue-full backpressure signal, not a crash.** It
  surfaces as :class:`AceStepQueueFull` with ``retryable = True`` so the
  G1 polling/submit loop can back off instead of failing the wizard.

HTTP is spoken through :mod:`httpx`. Every method builds a short-lived
``AsyncClient`` so there is no cross-request state to leak across a
``--reload`` cycle; an ``httpx.BaseTransport`` can be injected via
``transport=`` (that is the seam the tests use — no real socket is ever
opened in the suite).
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx


# ── Env ──────────────────────────────────────────────────────────────

#: Base URL of the ACE-Step FastAPI server, e.g. ``http://192.168.1.40:8001``.
ENV_BASE_URL = "ACESTEP_BASE_URL"
#: Optional bearer token; sent as ``Authorization: Bearer <key>`` when set.
ENV_API_KEY = "ACESTEP_API_KEY"

#: Generous default for generation calls — ``/release_task`` enqueues and
#: returns quickly, but the LM 5 Hz planner can make it think first.
DEFAULT_TIMEOUT_SEC = 30.0

#: ``health()`` is the feature flag behind a UI render. When the box is
#: off the TCP connect is what hangs, so cap it hard: an unreachable LAN
#: host must cost ~1 s, not the default 5 s+ that would stall the wizard.
HEALTH_CONNECT_TIMEOUT_SEC = 1.5
HEALTH_TIMEOUT_SEC = 3.0


def base_url() -> str | None:
    """``ACESTEP_BASE_URL`` (trailing slash stripped) or ``None`` if unset.

    Read at call time — see the module docstring.
    """
    raw = (os.getenv(ENV_BASE_URL) or "").strip()
    return raw.rstrip("/") or None


def api_key() -> str | None:
    """``ACESTEP_API_KEY`` or ``None``. Auth is optional server-side."""
    raw = (os.getenv(ENV_API_KEY) or "").strip()
    return raw or None


def enabled() -> bool:
    """True when a base URL is configured. No network, no import-time cache."""
    return base_url() is not None


# ── Typed errors ─────────────────────────────────────────────────────


class AceStepError(RuntimeError):
    """Base class for every failure this client reports.

    ``retryable`` tells a caller whether backing off and trying again is
    meaningful (queue full, box unreachable) as opposed to a request the
    server will reject identically forever (bad payload, bad key).
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.payload = payload


class AceStepDisabled(AceStepError):
    """``ACESTEP_BASE_URL`` is unset — the generator feature is off.

    Not an outage: this is the documented default state of the install.
    """


class AceStepUnavailable(AceStepError):
    """Could not reach the server (connect refused, timeout, DNS).

    Retryable because the usual cause is "the box is off right now" per
    the VRAM protocol, which a later attempt may find resolved.
    """

    retryable = True


class AceStepProtocolError(AceStepError):
    """The server answered, but not with the documented envelope/shape."""


class AceStepBadRequest(AceStepError):
    """``400`` — invalid request (also the fallback for other 4xx)."""


class AceStepAuthError(AceStepError):
    """``401`` / ``403`` — missing or wrong ``ACESTEP_API_KEY``."""


class AceStepUnsupportedMedia(AceStepError):
    """``415`` — wrong ``Content-Type`` (JSON vs multipart mix-up)."""


class AceStepQueueFull(AceStepError):
    """``429`` — ``ACESTEP_QUEUE_MAXSIZE`` reached. Back off and retry."""

    retryable = True


class AceStepServerError(AceStepError):
    """``500`` (and other 5xx) — internal error on the ACE-Step side."""


#: HTTP status → exception. Anything else falls back by class of status.
_STATUS_ERRORS: dict[int, type[AceStepError]] = {
    400: AceStepBadRequest,
    401: AceStepAuthError,
    403: AceStepAuthError,
    415: AceStepUnsupportedMedia,
    429: AceStepQueueFull,
    500: AceStepServerError,
}


def _error_for_status(status: int) -> type[AceStepError]:
    exc = _STATUS_ERRORS.get(status)
    if exc is not None:
        return exc
    if status >= 500:
        return AceStepServerError
    return AceStepBadRequest


# ── Result shapes ────────────────────────────────────────────────────


@dataclass
class ReleaseTaskResult:
    """What ``POST /release_task`` hands back once the job is queued."""

    task_id: str
    status: str | None = None
    queue_position: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Take:
    """One generated take (a ``batch_size`` request yields several).

    ``metas`` carries the FINAL generation values — the publisher (G2)
    must use ``metas.bpm`` / ``metas.keyscale`` rather than re-detecting
    them, because poisoned catalog BPMs have already caused live genre
    drift.
    """

    file: str | None = None
    status: int | None = None
    prompt: str = ""
    lyrics: str = ""
    metas: dict[str, Any] = field(default_factory=dict)
    seed_value: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # ── metas convenience (the fields G2's ingest needs) ──
    @property
    def bpm(self) -> Any:
        return self.metas.get("bpm")

    @property
    def duration(self) -> Any:
        return self.metas.get("duration")

    @property
    def genres(self) -> Any:
        return self.metas.get("genres")

    @property
    def keyscale(self) -> Any:
        return self.metas.get("keyscale")

    @property
    def timesignature(self) -> Any:
        return self.metas.get("timesignature")

    @property
    def ok(self) -> bool:
        """Take finished successfully (``status == 1``)."""
        return self.status == 1


@dataclass
class TaskResult:
    """One entry of a ``POST /query_result`` batch response.

    ``status``: ``0`` running · ``1`` ok · ``2`` failed.

    ``result_parse_error`` is set (instead of raising) when the
    string-encoded ``result`` field cannot be decoded. A polling loop
    must not die on one malformed payload; the caller can log it and
    keep the remaining task ids alive.
    """

    task_id: str
    status: int | None = None
    takes: list[Take] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    result_parse_error: str | None = None

    @property
    def running(self) -> bool:
        return self.status == 0

    @property
    def ok(self) -> bool:
        return self.status == 1

    @property
    def failed(self) -> bool:
        return self.status == 2

    @property
    def done(self) -> bool:
        """Terminal — stop polling this id."""
        return self.status in (1, 2)


def _parse_result_field(result: Any) -> tuple[list[Take], str | None]:
    """Decode ``query_result``'s ``result`` field into :class:`Take` objects.

    The spec says ``result`` is a **JSON string** holding a list with one
    element per take. Reality is defended against on three axes:

    * empty/``None`` (job still running) → no takes, no error;
    * already-decoded ``list``/``dict`` (a server that stops
      string-encoding) → accepted as-is;
    * a bare object instead of a list → wrapped into a one-take list.

    Returns ``(takes, parse_error)``; ``parse_error`` non-None means the
    payload was undecodable and the caller should surface it, not crash.
    """
    if result is None or result == "":
        return [], None

    decoded: Any = result
    if isinstance(result, (str, bytes)):
        try:
            decoded = json.loads(result)
        except (ValueError, TypeError) as exc:
            return [], f"result is not valid JSON: {exc}"

    if isinstance(decoded, dict):
        decoded = [decoded]
    if not isinstance(decoded, list):
        return [], f"result decoded to {type(decoded).__name__}, expected list"

    takes: list[Take] = []
    for entry in decoded:
        if not isinstance(entry, dict):
            continue
        metas = entry.get("metas")
        if not isinstance(metas, dict):
            metas = {}
        seed = entry.get("seed_value")
        takes.append(
            Take(
                file=entry.get("file"),
                status=entry.get("status"),
                prompt=entry.get("prompt") or "",
                lyrics=entry.get("lyrics") or "",
                metas=metas,
                seed_value=None if seed is None else str(seed),
                raw=entry,
            )
        )
    return takes, None


# ── Client ───────────────────────────────────────────────────────────


class AceStepClient:
    """Async wrapper over the ACE-Step HTTP API.

    Construct freely — it holds no connection. ``base_url`` / ``api_key``
    default to ``None``, meaning "resolve from the environment on every
    call"; pass explicit values only in tests or one-off tooling.

    ``transport`` is injected straight into ``httpx.AsyncClient`` so a
    test can hand over ``httpx.MockTransport`` and guarantee no socket
    is opened.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout

    # ── config resolution (call time) ──

    def base_url(self) -> str | None:
        """Explicit override, else the env var — resolved per call."""
        return self._base_url or base_url()

    def api_key(self) -> str | None:
        return self._api_key or api_key()

    def enabled(self) -> bool:
        return self.base_url() is not None

    def _require_base_url(self) -> str:
        url = self.base_url()
        if url is None:
            raise AceStepDisabled(
                f"{ENV_BASE_URL} is not set — the ACE-Step generator is disabled"
            )
        return url

    def _headers(self) -> dict[str, str]:
        """Auth header present **iff** an API key is configured."""
        key = self.api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    # ── transport ──

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> Any:
        """Issue one request and return the unwrapped ``data`` payload.

        Two encodings, never mixed (httpx refuses ``json=`` alongside
        ``data=``): JSON by default, ``multipart/form-data`` when
        ``files`` is present — then ``json_body`` becomes the form
        fields, flattened by :func:`_form_value`. The API spec (§3)
        documents both for ``/release_task``; multipart exists solely
        for G3's degradation lane (upload the source audio when the box
        refuses to read it off its own disk).
        """
        base = self._require_base_url()
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout if timeout is not None else self._timeout,
            transport=self._transport,
            headers=self._headers(),
        ) as client:
            try:
                if files is not None:
                    resp = await client.request(
                        method,
                        path,
                        data={k: _form_value(v) for k, v in (json_body or {}).items()},
                        files=files,
                    )
                else:
                    resp = await client.request(method, path, json=json_body)
            except httpx.HTTPError as exc:
                raise AceStepUnavailable(
                    f"ACE-Step unreachable at {base}{path}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return _unwrap(resp)

    # ── API surface ──

    async def health(self) -> bool:
        """``GET /health`` — the generator feature flag.

        Total function by design: returns ``False`` for "disabled" (no
        base URL), "unreachable" (box off) and "answered badly" alike,
        because every one of those means the same thing to the UI. It
        never raises, and it is bounded by
        :data:`HEALTH_CONNECT_TIMEOUT_SEC` so a dead LAN host cannot
        stall the endpoint that renders the wizard.
        """
        if not self.enabled():
            return False
        timeout = httpx.Timeout(
            HEALTH_TIMEOUT_SEC, connect=HEALTH_CONNECT_TIMEOUT_SEC
        )
        try:
            await self._request("GET", "/health", timeout=timeout)
        except AceStepError:
            return False
        return True

    async def engine_state(self) -> dict[str, Any] | None:
        """``GET /health``'s BODY — what the box currently HOLDS.

        `health()` answers "can I reach it"; this answers "is it holding the
        GPU". They are different questions and today they were confused twice:
        a box that answers /health while `models_initialized` is false is up and
        weighing nothing, which is the whole point of starting it with
        `--no-init`. Without this the panel can only say "reachable", which is
        exactly the half that was never in doubt.

        Total like `health()`: `None` for disabled, unreachable or malformed,
        because a status panel must never be the thing that breaks.
        """
        if not self.enabled():
            return None
        timeout = httpx.Timeout(
            HEALTH_TIMEOUT_SEC, connect=HEALTH_CONNECT_TIMEOUT_SEC
        )
        try:
            data = await self._request("GET", "/health", timeout=timeout)
        except AceStepError:
            return None
        return data if isinstance(data, dict) else None

    async def stats(self) -> dict[str, Any]:
        """``GET /v1/stats`` — queue depth + ``avg_job_seconds`` (ETA source)."""
        data = await self._request("GET", "/v1/stats")
        return data if isinstance(data, dict) else {"value": data}

    async def release_task(
        self,
        payload: dict[str, Any],
        *,
        files: dict[str, Any] | None = None,
    ) -> ReleaseTaskResult:
        """``POST /release_task`` — enqueue a generation, return its handle.

        ``payload`` is passed through verbatim (the API accepts both
        snake_case and camelCase, so this client does not second-guess
        the caller's field names). ``429`` raises
        :class:`AceStepQueueFull`, which is ``retryable``.

        ``files`` switches the request to ``multipart/form-data`` with
        ``payload`` as the form fields — httpx's ``{name: (filename,
        fileobj_or_bytes, content_type)}`` shape, e.g.
        ``{"src_audio": ("take.wav", handle, "audio/wav")}``. That is the
        spec's upload lane (§3.3), and G3's *only* use for it: when ACE
        refuses an absolute ``src_audio_path`` because its process
        ``TMPDIR`` points somewhere else, the edit re-releases with the
        downloaded take attached instead. The default stays JSON, so no
        existing caller changes shape.
        """
        data = await self._request(
            "POST", "/release_task", json_body=payload, files=files
        )
        if not isinstance(data, dict):
            raise AceStepProtocolError(
                f"release_task returned {type(data).__name__}, expected object",
                payload=data,
            )
        task_id = data.get("task_id")
        if not task_id:
            raise AceStepProtocolError(
                "release_task response carried no task_id", payload=data
            )
        pos = data.get("queue_position")
        try:
            queue_position = None if pos is None else int(pos)
        except (TypeError, ValueError):
            queue_position = None
        return ReleaseTaskResult(
            task_id=str(task_id),
            status=data.get("status"),
            queue_position=queue_position,
            raw=data,
        )

    async def query_result(self, task_ids: list[str] | str) -> list[TaskResult]:
        """``POST /query_result`` — poll a batch of task ids.

        Accepts a single id for convenience. Each entry's string-encoded
        ``result`` is decoded here (see :func:`_parse_result_field`) so
        callers never touch raw JSON strings.
        """
        ids = [task_ids] if isinstance(task_ids, str) else list(task_ids)
        data = await self._request(
            "POST", "/query_result", json_body={"task_id_list": ids}
        )

        # The batch may arrive as a bare list, or wrapped under a key.
        entries: Any = data
        if isinstance(data, dict):
            for key in ("results", "result_list", "tasks", "data"):
                if isinstance(data.get(key), list):
                    entries = data[key]
                    break
            else:
                entries = [data] if "task_id" in data else []
        if not isinstance(entries, list):
            raise AceStepProtocolError(
                f"query_result returned {type(entries).__name__}, expected list",
                payload=data,
            )

        out: list[TaskResult] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            takes, parse_error = _parse_result_field(entry.get("result"))
            status = entry.get("status")
            try:
                status = None if status is None else int(status)
            except (TypeError, ValueError):
                status = None
            out.append(
                TaskResult(
                    task_id=str(entry.get("task_id") or ""),
                    status=status,
                    takes=takes,
                    raw=entry,
                    result_parse_error=parse_error,
                )
            )
        return out

    @asynccontextmanager
    async def stream_audio(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[httpx.Response]:
        """Open a streaming ``GET`` on a take's audio (G1's proxy).

        Yields an **open** ``httpx.Response``; the caller iterates
        ``aiter_bytes()`` and the context manager closes both the
        response and the underlying client on exit. A 3-minute 48 kHz
        WAV is ~35 MB, so the backend must never buffer it whole.

        ``headers`` is merged over the client's own (that is how the
        proxy forwards ``Range``). Error statuses are raised as the
        usual typed errors — with the body drained first, since a
        streaming response has not read one yet. No envelope unwrapping
        happens here: the payload is audio, not JSON.

        This exists because the proxy has to speak through the SAME
        injected transport and auth headers as every other call
        (:meth:`audio_url` alone would force the endpoint to open its
        own socket, which the test suite must never do).
        """
        url = self.audio_url(path)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers=self._headers(),
        ) as client:
            request = client.build_request("GET", url, headers=headers or None)
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise AceStepUnavailable(
                    f"ACE-Step unreachable at {url}: {type(exc).__name__}: {exc}"
                ) from exc
            try:
                if response.status_code >= 400:
                    await response.aread()
                    detail = (response.text or "").strip()[:200] or response.reason_phrase
                    raise _error_for_status(response.status_code)(
                        f"ACE-Step returned HTTP {response.status_code} for "
                        f"the take audio: {detail}",
                        status_code=response.status_code,
                    )
                yield response
            finally:
                await response.aclose()

    def audio_url(self, path: str) -> str:
        """Absolute URL for a take's audio (G1 proxies this, G2 downloads it).

        A result's ``file`` field is a relative ``/v1/audio?path=...``
        URL, so the common case is just "prepend the base". Two other
        shapes are handled: an already-absolute URL passes through, and
        a bare server-side file path is wrapped into a ``/v1/audio``
        query (URL-encoded).
        """
        base = self._require_base_url()
        raw = (path or "").strip()
        if not raw:
            raise ValueError("audio_url() requires a non-empty path")
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("/"):
            return f"{base}{raw}"
        return f"{base}/v1/audio?path={quote(raw, safe='')}"


def _form_value(value: Any) -> str:
    """One JSON payload field as a ``multipart/form-data`` scalar.

    Multipart carries text, so every value has to be flattened. The
    encodings are chosen to survive ACE's FastAPI ``Form(...)`` coercion:
    booleans go out lower-case (``true``/``false``, which pydantic reads
    as a bool while ``"True"`` also works but ``"None"`` would not),
    ``None`` becomes an empty string, numbers and strings go verbatim,
    and anything structured falls back to JSON — the only lossless
    option for a nested ``experimental`` block.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value)


def _unwrap(resp: httpx.Response) -> Any:
    """Validate one response and return the envelope's ``data`` field.

    Order matters: the HTTP status decides the exception TYPE (that is
    the documented error table), while the envelope's ``error`` string
    supplies the message when the body is parseable. A non-JSON body on
    an error status must still produce the right typed error, so parsing
    failures never mask the status.
    """
    status = resp.status_code
    body: Any
    try:
        body = resp.json()
    except ValueError:
        body = None

    if status >= 400:
        exc_cls = _error_for_status(status)
        detail = None
        code = None
        if isinstance(body, dict):
            code = body.get("code")
            detail = body.get("error") or body.get("detail") or body.get("message")
        if detail is None:
            detail = (resp.text or "").strip()[:200] or resp.reason_phrase
        raise exc_cls(
            f"ACE-Step returned HTTP {status}: {detail}",
            status_code=status,
            code=code if isinstance(code, int) else None,
            payload=body,
        )

    if not isinstance(body, dict):
        raise AceStepProtocolError(
            f"ACE-Step returned a non-object body (HTTP {status})",
            status_code=status,
            payload=body,
        )

    # An in-band failure: HTTP 200 with an envelope that says otherwise.
    env_code = body.get("code")
    env_error = body.get("error")
    if env_error or (isinstance(env_code, int) and env_code >= 400):
        exc_cls = _error_for_status(env_code if isinstance(env_code, int) else 500)
        raise exc_cls(
            f"ACE-Step envelope error (code {env_code}): {env_error}",
            status_code=status,
            code=env_code if isinstance(env_code, int) else None,
            payload=body,
        )

    if "data" not in body:
        raise AceStepProtocolError(
            "ACE-Step response carried no 'data' field",
            status_code=status,
            payload=body,
        )
    return body["data"]
