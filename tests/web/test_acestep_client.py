"""Unit tests for the ACE-Step HTTP client (G0).

Every request is served by an ``httpx.MockTransport`` — the suite never
opens a socket toward a real ACE-Step server (it is off most of the time
by design, per the VRAM protocol, and CI has no LAN box at all).

Contract under test: ``docs/acestep-wizard-plan.md`` §"G0 contract" and
the API spec in ``docs/ACE-STEP-API-SPEC.md``.
"""
from __future__ import annotations

import json

import httpx
import pytest

from web.backend import acestep_client as ac


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data, *, code: int = 200, error=None) -> dict:
    """The wrapper every ACE-Step response carries."""
    return {
        "data": data,
        "code": code,
        "error": error,
        "timestamp": 1700000000000,
        "extra": None,
    }


def _recorder(responder):
    """MockTransport + the list of requests it saw.

    ``responder`` may return an ``httpx.Response`` or raise (to simulate
    a connect refusal / timeout).
    """
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responder(request)

    return httpx.MockTransport(handler), calls


def _ok(payload):
    """Responder returning ``payload`` wrapped in a 200 envelope."""
    return lambda request: httpx.Response(200, json=_envelope(payload))


@pytest.fixture
def no_env(monkeypatch):
    """Neither env var set — the disabled (default) install."""
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


@pytest.fixture
def base_env(monkeypatch):
    """Base URL configured, no API key."""
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


# ── Env handling (read at CALL time, never at import) ────────────────


def test_disabled_when_base_url_unset(no_env):
    assert ac.base_url() is None
    assert ac.api_key() is None
    assert ac.enabled() is False
    assert ac.AceStepClient().enabled() is False


def test_enabled_when_base_url_set(base_env):
    assert ac.enabled() is True
    assert ac.base_url() == "http://ace.test:8001"


def test_env_is_read_at_call_time_not_import_time(monkeypatch, no_env):
    """The module was imported with no env; a late ``.env`` must still win.

    This is the ``brief_parser`` lesson (web/CLAUDE.md): an import-time
    snapshot pins the wrong value under ``uvicorn --reload``.
    """
    client = ac.AceStepClient()
    assert client.enabled() is False

    monkeypatch.setenv(ac.ENV_BASE_URL, "http://late.test:8001")
    assert client.enabled() is True
    assert client.base_url() == "http://late.test:8001"

    monkeypatch.setenv(ac.ENV_BASE_URL, "http://changed.test:8001")
    assert client.base_url() == "http://changed.test:8001"


def test_base_url_strips_trailing_slash_and_blanks(monkeypatch):
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001/")
    assert ac.base_url() == "http://ace.test:8001"
    monkeypatch.setenv(ac.ENV_BASE_URL, "   ")
    assert ac.base_url() is None
    assert ac.enabled() is False


def test_the_module_does_not_load_dotenv_at_import_time():
    """A stray ``.env`` must never quietly point the client somewhere.

    Same guard as ``tests/test_algorave_playground.py``: checked as the
    call and the import, not the bare word — the module docstring
    explains why it abstains, and that sentence is not a call.
    """
    from pathlib import Path

    source = Path(ac.__file__).read_text(encoding="utf-8")
    assert "load_dotenv(" not in source
    assert "import load_dotenv" not in source and "import dotenv" not in source


def test_explicit_base_url_overrides_env(monkeypatch):
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://env.test:8001")
    client = ac.AceStepClient(base_url="http://explicit.test:8001/")
    assert client.base_url() == "http://explicit.test:8001"


# ── health(): the feature flag ───────────────────────────────────────


async def test_health_false_when_disabled_and_makes_no_request(no_env):
    transport, calls = _recorder(_ok({"status": "ok"}))
    client = ac.AceStepClient(transport=transport)

    assert await client.health() is False
    assert calls == []  # env unset ⇒ not a single byte on the wire


async def test_health_false_when_server_down(base_env):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    transport, calls = _recorder(refuse)
    client = ac.AceStepClient(transport=transport)

    assert await client.health() is False
    assert len(calls) == 1
    assert calls[0].url.path == "/health"


async def test_health_false_on_connect_timeout(base_env):
    def timeout(request):
        raise httpx.ConnectTimeout("timed out")

    transport, _ = _recorder(timeout)
    assert await ac.AceStepClient(transport=transport).health() is False


async def test_health_false_on_server_error(base_env):
    transport, _ = _recorder(lambda r: httpx.Response(500, json=_envelope(None)))
    assert await ac.AceStepClient(transport=transport).health() is False


async def test_health_false_on_garbage_body(base_env):
    transport, _ = _recorder(lambda r: httpx.Response(200, text="<html>nope"))
    assert await ac.AceStepClient(transport=transport).health() is False


async def test_health_true_when_up(base_env):
    transport, calls = _recorder(_ok({"status": "ok"}))
    assert await ac.AceStepClient(transport=transport).health() is True
    assert calls[0].url.path == "/health"
    assert calls[0].method == "GET"


async def test_health_uses_a_short_connect_timeout(base_env):
    """A dead LAN host must not stall the wizard's flag."""
    transport, calls = _recorder(_ok({"status": "ok"}))
    await ac.AceStepClient(transport=transport, timeout=300.0).health()

    timeout = calls[0].extensions["timeout"]
    assert timeout["connect"] == ac.HEALTH_CONNECT_TIMEOUT_SEC
    assert timeout["read"] == ac.HEALTH_TIMEOUT_SEC
    assert ac.HEALTH_CONNECT_TIMEOUT_SEC < ac.DEFAULT_TIMEOUT_SEC


# ── Auth header: present iff ACESTEP_API_KEY is set ──────────────────


async def test_no_auth_header_without_api_key(base_env):
    transport, calls = _recorder(_ok({"queued": 0}))
    await ac.AceStepClient(transport=transport).stats()
    assert "authorization" not in calls[0].headers


async def test_bearer_header_when_api_key_set(monkeypatch, base_env):
    monkeypatch.setenv(ac.ENV_API_KEY, "sk-ace-123")
    transport, calls = _recorder(_ok({"queued": 0}))
    await ac.AceStepClient(transport=transport).stats()
    assert calls[0].headers["authorization"] == "Bearer sk-ace-123"


async def test_api_key_read_at_call_time(monkeypatch, base_env):
    transport, calls = _recorder(_ok({"queued": 0}))
    client = ac.AceStepClient(transport=transport)

    await client.stats()
    assert "authorization" not in calls[0].headers

    monkeypatch.setenv(ac.ENV_API_KEY, "sk-late")
    await client.stats()
    assert calls[1].headers["authorization"] == "Bearer sk-late"


# ── Envelope unwrapping ──────────────────────────────────────────────


async def test_stats_unwraps_the_envelope(base_env):
    payload = {
        "queued": 3, "running": 1, "avg_job_seconds": 42.5,
        "queue_maxsize": 200,
    }
    transport, calls = _recorder(_ok(payload))

    got = await ac.AceStepClient(transport=transport).stats()

    assert got == payload  # data only — no code/timestamp/extra leakage
    assert calls[0].url.path == "/v1/stats"


async def test_missing_data_field_is_a_protocol_error(base_env):
    transport, _ = _recorder(
        lambda r: httpx.Response(200, json={"code": 200, "error": None})
    )
    with pytest.raises(ac.AceStepProtocolError):
        await ac.AceStepClient(transport=transport).stats()


async def test_non_object_body_is_a_protocol_error(base_env):
    transport, _ = _recorder(lambda r: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(ac.AceStepProtocolError):
        await ac.AceStepClient(transport=transport).stats()


async def test_in_band_envelope_error_on_http_200(base_env):
    """HTTP 200 but ``error`` set — trust the envelope, not the status."""
    transport, _ = _recorder(
        lambda r: httpx.Response(
            200, json=_envelope(None, code=500, error="model not loaded")
        )
    )
    with pytest.raises(ac.AceStepServerError) as excinfo:
        await ac.AceStepClient(transport=transport).stats()
    assert "model not loaded" in str(excinfo.value)


# ── Error table (spec §2) ────────────────────────────────────────────


@pytest.mark.parametrize(
    "status, exc_cls, retryable",
    [
        (400, ac.AceStepBadRequest, False),
        (401, ac.AceStepAuthError, False),
        (415, ac.AceStepUnsupportedMedia, False),
        (429, ac.AceStepQueueFull, True),
        (500, ac.AceStepServerError, False),
    ],
)
async def test_error_table_maps_to_typed_outcomes(
    base_env, status, exc_cls, retryable
):
    transport, _ = _recorder(
        lambda r: httpx.Response(
            status, json=_envelope(None, code=status, error="boom")
        )
    )
    with pytest.raises(exc_cls) as excinfo:
        await ac.AceStepClient(transport=transport).stats()

    err = excinfo.value
    assert isinstance(err, ac.AceStepError)
    assert err.status_code == status
    assert err.retryable is retryable
    assert "boom" in str(err)


async def test_queue_full_is_the_retryable_signal(base_env):
    """429 must be backpressure the caller can honour, never a crash."""
    transport, _ = _recorder(
        lambda r: httpx.Response(429, json=_envelope(None, code=429, error="queue full"))
    )
    with pytest.raises(ac.AceStepQueueFull) as excinfo:
        await ac.AceStepClient(transport=transport).release_task({"prompt": "x"})
    assert excinfo.value.retryable is True


async def test_error_status_with_non_json_body_still_typed(base_env):
    transport, _ = _recorder(lambda r: httpx.Response(401, text="Unauthorized"))
    with pytest.raises(ac.AceStepAuthError):
        await ac.AceStepClient(transport=transport).stats()


async def test_transport_failure_is_retryable_unavailable(base_env):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    transport, _ = _recorder(refuse)
    with pytest.raises(ac.AceStepUnavailable) as excinfo:
        await ac.AceStepClient(transport=transport).stats()
    assert excinfo.value.retryable is True


async def test_calls_raise_disabled_when_env_unset(no_env):
    transport, calls = _recorder(_ok({}))
    client = ac.AceStepClient(transport=transport)

    with pytest.raises(ac.AceStepDisabled):
        await client.stats()
    with pytest.raises(ac.AceStepDisabled):
        await client.release_task({"prompt": "x"})
    with pytest.raises(ac.AceStepDisabled):
        await client.query_result(["t1"])
    assert calls == []


# ── release_task ─────────────────────────────────────────────────────


async def test_release_task_returns_task_id_and_queue_position(base_env):
    transport, calls = _recorder(
        _ok({"task_id": "abc123", "status": "queued", "queue_position": 4})
    )
    payload = {
        "prompt": "dark melodic techno, hypnotic",
        "bpm": 126, "audio_duration": 180, "batch_size": 2,
        "audio_format": "wav", "thinking": True,
    }

    got = await ac.AceStepClient(transport=transport).release_task(payload)

    assert got.task_id == "abc123"
    assert got.status == "queued"
    assert got.queue_position == 4
    assert got.raw["task_id"] == "abc123"

    assert calls[0].method == "POST"
    assert calls[0].url.path == "/release_task"
    # Payload forwarded verbatim — the client does not rewrite fields.
    assert json.loads(calls[0].content) == payload


async def test_release_task_tolerates_missing_queue_position(base_env):
    transport, _ = _recorder(_ok({"task_id": "abc", "status": "queued"}))
    got = await ac.AceStepClient(transport=transport).release_task({})
    assert got.task_id == "abc"
    assert got.queue_position is None


async def test_release_task_without_task_id_is_a_protocol_error(base_env):
    transport, _ = _recorder(_ok({"status": "queued"}))
    with pytest.raises(ac.AceStepProtocolError):
        await ac.AceStepClient(transport=transport).release_task({})


# ── query_result: the string-encoded ``result`` field ────────────────


_TAKE_ONE = {
    "file": "/v1/audio?path=%2Ftmp%2Fout%2Ftake0.wav",
    "status": 1,
    "prompt": "dark melodic techno, hypnotic, driving",
    "lyrics": "[Verse]\nneon rain",
    "metas": {
        "bpm": 126,
        "duration": 183.4,
        "genres": "techno, melodic techno",
        "keyscale": "A Minor",
        "timesignature": "4",
    },
    "seed_value": "12345",
    "lm_model": "lm-5hz",
    "dit_model": "turbo",
}
_TAKE_TWO = {
    "file": "/v1/audio?path=%2Ftmp%2Fout%2Ftake1.wav",
    "status": 1,
    "prompt": "dark melodic techno, hypnotic, driving",
    "lyrics": "",
    "metas": {
        "bpm": 128,
        "duration": 181.0,
        "genres": "techno",
        "keyscale": "F Minor",
        "timesignature": "4",
    },
    "seed_value": "67890",
}


async def test_query_result_parses_string_encoded_result(base_env):
    entry = {
        "task_id": "abc123",
        "status": 1,
        "result": json.dumps([_TAKE_ONE, _TAKE_TWO]),  # ← a JSON *string*
    }
    transport, calls = _recorder(_ok([entry]))

    results = await ac.AceStepClient(transport=transport).query_result(
        ["abc123"]
    )

    assert calls[0].url.path == "/query_result"
    assert json.loads(calls[0].content) == {"task_id_list": ["abc123"]}

    assert len(results) == 1
    task = results[0]
    assert task.task_id == "abc123"
    assert task.status == 1
    assert task.ok is True and task.done is True and task.running is False
    assert task.result_parse_error is None
    assert len(task.takes) == 2

    first = task.takes[0]
    assert first.file == "/v1/audio?path=%2Ftmp%2Fout%2Ftake0.wav"
    assert first.status == 1 and first.ok is True
    assert first.prompt == "dark melodic techno, hypnotic, driving"
    assert first.lyrics == "[Verse]\nneon rain"
    assert first.seed_value == "12345"
    # metas — the FINAL generation values G2 ingests (never re-detected).
    assert first.metas["bpm"] == 126
    assert first.bpm == 126
    assert first.duration == 183.4
    assert first.genres == "techno, melodic techno"
    assert first.keyscale == "A Minor"
    assert first.timesignature == "4"

    assert task.takes[1].bpm == 128
    assert task.takes[1].keyscale == "F Minor"
    assert task.takes[1].lyrics == ""


async def test_query_result_accepts_a_bare_task_id(base_env):
    entry = {"task_id": "solo", "status": 0, "result": ""}
    transport, calls = _recorder(_ok([entry]))

    results = await ac.AceStepClient(transport=transport).query_result("solo")

    assert json.loads(calls[0].content) == {"task_id_list": ["solo"]}
    assert results[0].task_id == "solo"


async def test_query_result_running_task_has_no_takes(base_env):
    entry = {"task_id": "abc", "status": 0, "result": ""}
    transport, _ = _recorder(_ok([entry]))

    task = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0]

    assert task.status == 0
    assert task.running is True and task.done is False
    assert task.takes == []
    assert task.result_parse_error is None


async def test_query_result_failed_task(base_env):
    entry = {"task_id": "abc", "status": 2, "result": None}
    transport, _ = _recorder(_ok([entry]))

    task = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0]

    assert task.failed is True and task.done is True and task.ok is False


async def test_query_result_batch_keeps_every_id(base_env):
    entries = [
        {"task_id": "a", "status": 1, "result": json.dumps([_TAKE_ONE])},
        {"task_id": "b", "status": 0, "result": ""},
    ]
    transport, calls = _recorder(_ok(entries))

    results = await ac.AceStepClient(transport=transport).query_result(["a", "b"])

    assert json.loads(calls[0].content) == {"task_id_list": ["a", "b"]}
    assert [r.task_id for r in results] == ["a", "b"]
    assert len(results[0].takes) == 1 and results[1].takes == []


async def test_query_result_malformed_result_does_not_raise(base_env):
    """A polling loop must survive one undecodable payload."""
    entry = {"task_id": "abc", "status": 1, "result": "{not json at all"}
    transport, _ = _recorder(_ok([entry]))

    task = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0]

    assert task.takes == []
    assert task.result_parse_error is not None
    assert "not valid JSON" in task.result_parse_error


async def test_query_result_accepts_already_decoded_result(base_env):
    """Defensive: a server that stops string-encoding must not break us."""
    entry = {"task_id": "abc", "status": 1, "result": [_TAKE_ONE]}
    transport, _ = _recorder(_ok([entry]))

    task = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0]

    assert len(task.takes) == 1
    assert task.takes[0].bpm == 126


async def test_query_result_wraps_a_single_take_object(base_env):
    entry = {"task_id": "abc", "status": 1, "result": json.dumps(_TAKE_ONE)}
    transport, _ = _recorder(_ok([entry]))

    task = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0]

    assert len(task.takes) == 1
    assert task.takes[0].keyscale == "A Minor"


async def test_query_result_take_without_metas_is_safe(base_env):
    entry = {
        "task_id": "abc", "status": 1,
        "result": json.dumps([{"file": "/v1/audio?path=x", "status": 1}]),
    }
    transport, _ = _recorder(_ok([entry]))

    take = (await ac.AceStepClient(transport=transport).query_result(["abc"]))[0].takes[0]

    assert take.metas == {}
    assert take.bpm is None and take.keyscale is None
    assert take.prompt == "" and take.lyrics == ""
    assert take.seed_value is None


async def test_query_result_wrapped_batch_shape(base_env):
    """Some builds nest the batch under a key rather than returning a list."""
    entry = {"task_id": "abc", "status": 1, "result": json.dumps([_TAKE_ONE])}
    transport, _ = _recorder(_ok({"results": [entry]}))

    results = await ac.AceStepClient(transport=transport).query_result(["abc"])

    assert len(results) == 1 and results[0].task_id == "abc"


async def test_query_result_unexpected_shape_is_a_protocol_error(base_env):
    transport, _ = _recorder(_ok("nonsense"))
    with pytest.raises(ac.AceStepProtocolError):
        await ac.AceStepClient(transport=transport).query_result(["abc"])


# ── audio_url ────────────────────────────────────────────────────────


def test_audio_url_prepends_base_to_a_relative_file(base_env):
    client = ac.AceStepClient()
    assert client.audio_url("/v1/audio?path=%2Ftmp%2Ftake0.wav") == (
        "http://ace.test:8001/v1/audio?path=%2Ftmp%2Ftake0.wav"
    )


def test_audio_url_passes_absolute_urls_through(base_env):
    client = ac.AceStepClient()
    url = "http://other.host:8001/v1/audio?path=x"
    assert client.audio_url(url) == url


def test_audio_url_wraps_a_bare_server_path(base_env):
    client = ac.AceStepClient()
    assert client.audio_url("/srv/out/take 0.wav".lstrip("/")) == (
        "http://ace.test:8001/v1/audio?path=srv%2Fout%2Ftake%200.wav"
    )


def test_audio_url_requires_a_path(base_env):
    with pytest.raises(ValueError):
        ac.AceStepClient().audio_url("")


def test_audio_url_raises_when_disabled(no_env):
    with pytest.raises(ac.AceStepDisabled):
        ac.AceStepClient().audio_url("/v1/audio?path=x")
