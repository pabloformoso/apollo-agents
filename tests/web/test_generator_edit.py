"""G3 — ``POST /api/generator/edit`` (repaint · cover · complete).

An edit is a second release whose source is an earlier take, so this
suite pins three things the audio alone would never reveal:

1. **The mode owns its parameters.** A ``repainting_start`` sent with
   ``mode: "cover"`` is a 422, not a silently dropped field — the caller
   believes something untrue about the request, and the only other
   evidence would be three minutes of wrong music.
2. **What lands on the wire.** ``task_type``, ``src_audio_path`` and
   ``chunk_mask_mode: "explicit"`` are asserted on the actual
   ``/release_task`` body, because "explicit" is the difference between
   an exact mask and a hint (API spec §3.3).
3. **The TMPDIR degradation.** ACE validates ``src_audio_path`` against
   its own process tmpdir, which a foreign ``TMPDIR`` moves — so the box
   can 400 the paths it just handed out. That one 400 downloads the take
   and re-releases it as multipart; every other 400 stays a 502.

Every byte toward ACE-Step is served by ``httpx.MockTransport`` through
the ``generator._client`` seam (the G0/G1/G2b convention). No socket is
ever opened toward a real generation box.

Contract: ``docs/acestep-wizard-plan.md`` §"G3 contract" and
``docs/ACE-STEP-API-SPEC.md`` §3.3.
"""
from __future__ import annotations

import json
import re

import httpx
import pytest

from web.backend import acestep_client as ac
from web.backend import generator
from web.backend.ws_manager import ws_manager


# ── Helpers ──────────────────────────────────────────────────────────

ACE_ROOT = generator.DEFAULT_AUDIO_ROOTS[0]
ACE_FILE = f"{ACE_ROOT}/6f1c2b7e-9d4a-4c11-b0a3-2e5f8d7c1a90_0.wav"

#: queued 2 · running 1 · 41 s per job — the ETA math's inputs, shared
#: with ``test_generator_tasks`` so the two endpoints cannot drift.
_STATS = {
    "queued": 2, "running": 1, "avg_job_seconds": 41.0, "queue_maxsize": 200,
}

_RELEASED = {"task_id": "edit-1", "status": "queued", "queue_position": 4}

#: Deliberately free of CR/LF so the multipart splitter below can strip
#: part boundaries without eating payload bytes.
_SOURCE_BYTES = b"RIFF....WAVEmock-source-pcm"

#: ACE's refusal when its process tmpdir does not match where its own
#: result files live (the plan's TMPDIR caveat).
TMPDIR_REFUSAL = "absolute audio file paths are not allowed"


def _envelope(data, *, code: int = 200, error=None) -> dict:
    return {
        "data": data, "code": code, "error": error,
        "timestamp": 1700000000000, "extra": None,
    }


def _box(*, release=_RELEASED, stats=_STATS, audio=_SOURCE_BYTES, release_hook=None):
    """A responder for a healthy box; each surface overridable per test.

    ``release_hook(request, n)`` may return a Response to take over the
    nth (1-based) ``/release_task`` call — that is how the degradation
    tests make the first release fail and the second succeed.
    """
    seen = {"release": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json=_envelope({"status": "ok"}))
        if path == "/v1/stats":
            if stats is None:
                return httpx.Response(
                    500, json=_envelope(None, code=500, error="no stats")
                )
            return httpx.Response(200, json=_envelope(stats))
        if path == "/release_task":
            seen["release"] += 1
            if release_hook is not None:
                taken = release_hook(request, seen["release"])
                if taken is not None:
                    return taken
            return httpx.Response(200, json=_envelope(release))
        if path == "/v1/audio":
            if audio is None:
                return httpx.Response(
                    404, json=_envelope(None, code=404, error="no such file")
                )
            return httpx.Response(
                200, content=audio, headers={"content-type": "audio/wav"}
            )
        return httpx.Response(404, json=_envelope(None, code=404, error="nope"))

    return responder


def _install_ace(monkeypatch, responder):
    """Point ``generator._client`` at a MockTransport; return the call log."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responder(request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        generator, "_client", lambda: ac.AceStepClient(transport=transport)
    )
    return calls


def _releases(calls) -> list[httpx.Request]:
    return [c for c in calls if c.url.path == "/release_task"]


def _released_payload(calls, index: int = 0) -> dict:
    """The JSON body of the nth ``/release_task`` call."""
    releases = _releases(calls)
    assert len(releases) > index, [c.url.path for c in calls]
    return json.loads(releases[index].content)


_NAME_RE = re.compile(r'name="([^"]*)"')
_FILENAME_RE = re.compile(r'filename="([^"]*)"')


def _multipart(request: httpx.Request) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """Split a ``multipart/form-data`` body into (fields, files).

    Hand-rolled rather than pulled from a library: the point of the
    assertion is the exact wire shape ACE's ``-F`` example documents, so
    the test must read the bytes, not a re-serialisation of them.
    """
    ctype = request.headers.get("content-type", "")
    assert ctype.startswith("multipart/form-data"), ctype
    boundary = ctype.split("boundary=", 1)[1].strip('"')

    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for chunk in request.content.split(b"--" + boundary.encode()):
        part = chunk.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, payload = part.partition(b"\r\n\r\n")
        head_text = head.decode("utf-8", "replace")
        name_match = _NAME_RE.search(head_text)
        if not name_match:
            continue
        name = name_match.group(1)
        file_match = _FILENAME_RE.search(head_text)
        if file_match:
            files[name] = (file_match.group(1), payload)
        else:
            fields[name] = payload.decode("utf-8")
    return fields, files


def _body(**over) -> dict:
    body = {"file": ACE_FILE, "mode": "complete"}
    body.update(over)
    return body


def _repaint(**over) -> dict:
    return _body(mode="repaint", repainting_start=10, repainting_end=20, **over)


class _FakeWS:
    """Stand-in for the WebSocket object the live handler registers."""


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_live_registry():
    saved = dict(ws_manager._connections)
    ws_manager._connections.clear()
    yield ws_manager._connections
    ws_manager._connections.clear()
    ws_manager._connections.update(saved)


@pytest.fixture(autouse=True)
def no_catalog_reads(monkeypatch):
    """No test touches the developer's real tracks.json by accident."""
    monkeypatch.setattr(generator, "_catalog_genres", lambda: set())


@pytest.fixture
def ace_off(monkeypatch):
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


@pytest.fixture
def ace_on(monkeypatch):
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)
    monkeypatch.delenv(generator.ENV_AUDIO_ROOT, raising=False)


# ══ Auth ═════════════════════════════════════════════════════════════


def test_edit_requires_auth(client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())
    assert client.post("/api/generator/edit", json=_body()).status_code == 401
    assert calls == []


def test_edit_rejects_a_bad_token(client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box())
    r = client.post(
        "/api/generator/edit",
        json=_body(),
        headers={"Authorization": "Bearer garbage"},
    )
    assert r.status_code == 401


# ══ Refusal ladder ═══════════════════════════════════════════════════


def test_edit_503_when_the_generator_is_disabled(auth_client, ace_off, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body())

    assert r.status_code == 503
    assert ac.ENV_BASE_URL in r.json()["detail"]
    assert calls == []


def test_edit_503_when_the_box_is_unreachable(auth_client, ace_on, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    _install_ace(monkeypatch, refuse)

    assert auth_client.post("/api/generator/edit", json=_body()).status_code == 503


def test_edit_409_while_a_live_session_is_on_air(
    auth_client, ace_on, monkeypatch, clean_live_registry
):
    """An edit RELEASES GPU work, so the VRAM guard applies exactly as on
    ``POST /tasks`` — unlike publish, which only touches the disk."""
    calls = _install_ace(monkeypatch, _box())
    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 409
    assert r.json()["detail"] == generator.VRAM_CONFLICT_MESSAGE
    # Refused before the GPU was ever asked for anything.
    assert calls == []


def test_edit_resumes_once_the_live_session_ends(
    auth_client, ace_on, monkeypatch, clean_live_registry
):
    _install_ace(monkeypatch, _box())
    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()
    assert auth_client.post("/api/generator/edit", json=_body()).status_code == 409

    clean_live_registry.pop(("sess-live", generator.LIVE_WS_CHANNEL))
    assert auth_client.post("/api/generator/edit", json=_body()).status_code == 200


def test_edit_429_when_the_ace_queue_is_full(auth_client, ace_on, monkeypatch):
    def full(request, n):
        return httpx.Response(429, json=_envelope(None, code=429, error="queue full"))

    _install_ace(monkeypatch, _box(release_hook=full))

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 429
    assert "queue is full" in r.json()["detail"]


def test_edit_502_when_ace_breaks(auth_client, ace_on, monkeypatch):
    def boom(request, n):
        return httpx.Response(500, json=_envelope(None, code=500, error="cuda oom"))

    _install_ace(monkeypatch, _box(release_hook=boom))

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 502
    assert "cuda oom" in r.json()["detail"]


# ══ The source path goes through THE validator ═══════════════════════


def test_edit_422_on_a_file_outside_the_root(auth_client, ace_on, monkeypatch):
    """``file`` becomes ``src_audio_path`` on ACE's disk — root-checked."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(file="/tmp/x.wav"))

    assert r.status_code == 422
    assert ACE_ROOT in r.json()["detail"]
    assert calls == []


def test_edit_422_on_a_relative_path(auth_client, ace_on, monkeypatch):
    """A relative path cannot be root-checked, and this one is sent on."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(file="api_audio/x.wav"))

    assert r.status_code == 422
    assert "decoded ACE-Step path" in r.json()["detail"]
    assert calls == []


@pytest.mark.parametrize("bad", [
    "http://evil.test/v1/audio?path=x",
    "//evil.test/v1/audio",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "/v1/audio?path=%2Fhome%2Fpablo%2F..%2F..%2Fetc%2Fpasswd",
])
def test_edit_422_on_a_hostile_file(auth_client, ace_on, monkeypatch, bad):
    calls = _install_ace(monkeypatch, _box())
    r = auth_client.post("/api/generator/edit", json=_body(file=bad))
    assert r.status_code == 422
    assert calls == []


def test_edit_accepts_the_encoded_endpoint_shape(auth_client, ace_on, monkeypatch):
    """A page that persisted ACE's ``file`` verbatim still edits."""
    from urllib.parse import quote

    calls = _install_ace(monkeypatch, _box())
    encoded = f"/v1/audio?path={quote(ACE_FILE, safe='')}"

    r = auth_client.post("/api/generator/edit", json=_body(file=encoded))

    assert r.status_code == 200, r.text
    # Unwrapped back to the decoded path ACE reads off its own disk.
    assert _released_payload(calls)["src_audio_path"] == ACE_FILE


# ══ Mode validation matrix ═══════════════════════════════════════════


def test_edit_422_on_an_unknown_mode(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())
    r = auth_client.post("/api/generator/edit", json=_body(mode="extract"))
    assert r.status_code == 422
    assert calls == []


def test_edit_422_without_a_mode(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box())
    r = auth_client.post("/api/generator/edit", json={"file": ACE_FILE})
    assert r.status_code == 422


def test_edit_422_on_an_unknown_body_field(auth_client, ace_on, monkeypatch):
    """``extra="forbid"`` — and ``task_id`` is the one that must never fly.

    ACE's job records expire; its result files do not. The whole
    persistence rule is that the page carries the path, so a body that
    tries to name a task is a contract violation, not a nicety.
    """
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(task_id="task-1"))

    assert r.status_code == 422
    assert "task_id" in r.text
    assert calls == []


@pytest.mark.parametrize("missing", ["repainting_start", "repainting_end"])
def test_repaint_422_without_its_range(auth_client, ace_on, monkeypatch, missing):
    calls = _install_ace(monkeypatch, _box())
    body = _repaint()
    body.pop(missing)

    r = auth_client.post("/api/generator/edit", json=body)

    assert r.status_code == 422
    assert "repainting_start and repainting_end" in r.text
    assert calls == []


def test_repaint_422_when_the_range_runs_backwards(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="repaint", repainting_start=30, repainting_end=20),
    )

    assert r.status_code == 422
    assert "must be before" in r.text
    assert calls == []


def test_repaint_422_on_an_empty_range(auth_client, ace_on, monkeypatch):
    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="repaint", repainting_start=20, repainting_end=20),
    )
    assert r.status_code == 422


def test_repaint_422_on_a_negative_start(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box())
    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="repaint", repainting_start=-5, repainting_end=20),
    )
    assert r.status_code == 422


@pytest.mark.parametrize("end", [-0.5, -2, -100])
def test_repaint_422_on_a_negative_end_that_is_not_the_sentinel(
    auth_client, ace_on, monkeypatch, end
):
    """Only ``-1`` means "to the end"; anything else negative is a typo."""
    _install_ace(monkeypatch, _box())
    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="repaint", repainting_start=10, repainting_end=end),
    )
    assert r.status_code == 422


def test_repaint_accepts_minus_one_as_to_the_end(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="repaint", repainting_start=90, repainting_end=-1),
    )

    assert r.status_code == 200, r.text
    payload = _released_payload(calls)
    assert payload["repainting_start"] == 90.0
    assert payload["repainting_end"] == -1.0


def test_repaint_422_with_a_cover_strength(auth_client, ace_on, monkeypatch):
    """Wrong-mode parameters are refused, never ignored."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_repaint(audio_cover_strength=0.3))

    assert r.status_code == 422
    assert "audio_cover_strength belongs to mode 'cover'" in r.text
    assert calls == []


@pytest.mark.parametrize("field", ["repainting_start", "repainting_end"])
def test_cover_422_with_a_repaint_range(auth_client, ace_on, monkeypatch, field):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(mode="cover", **{field: 10}))

    assert r.status_code == 422
    assert "belong to mode 'repaint'" in r.text
    assert calls == []


@pytest.mark.parametrize("strength", [-0.1, 1.1, 42])
def test_cover_422_on_a_strength_outside_0_to_1(
    auth_client, ace_on, monkeypatch, strength
):
    _install_ace(monkeypatch, _box())
    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="cover", audio_cover_strength=strength),
    )
    assert r.status_code == 422


@pytest.mark.parametrize("field,value", [
    ("repainting_start", 10),
    ("repainting_end", 20),
    ("audio_cover_strength", 0.4),
])
def test_complete_422_with_any_other_mode_parameter(
    auth_client, ace_on, monkeypatch, field, value
):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(**{field: value}))

    assert r.status_code == 422
    assert "no range and no strength" in r.text
    assert calls == []


# ══ What lands on the wire ═══════════════════════════════════════════


def test_repaint_release_body(auth_client, ace_on, monkeypatch):
    """The whole point of the endpoint, asserted on the actual request."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post(
        "/api/generator/edit",
        json=_repaint(prompt="same style, more energy"),
    )

    assert r.status_code == 200, r.text
    payload = _released_payload(calls)
    assert payload["task_type"] == "repaint"
    assert payload["src_audio_path"] == ACE_FILE
    # "explicit" is the difference between an exact mask and a hint.
    assert payload["chunk_mask_mode"] == generator.REPAINT_CHUNK_MASK_MODE == "explicit"
    assert payload["repainting_start"] == 10.0
    assert payload["repainting_end"] == 20.0
    assert payload["prompt"] == "same style, more energy"
    # The catalog contract travels with every release, edit included.
    assert payload["audio_format"] == "wav"
    assert payload["thinking"] is True
    # No task id, ever.
    assert "task_id" not in payload
    assert "audio_cover_strength" not in payload


def test_cover_pins_the_default_strength(auth_client, ace_on, monkeypatch):
    """Spec §3.5's style-transfer hint, pinned rather than left to the LM."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(mode="cover"))

    assert r.status_code == 200, r.text
    payload = _released_payload(calls)
    assert payload["task_type"] == "cover"
    assert payload["audio_cover_strength"] == generator.DEFAULT_COVER_STRENGTH == 0.2
    assert "chunk_mask_mode" not in payload
    assert "repainting_start" not in payload


def test_cover_honours_an_explicit_strength(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    auth_client.post(
        "/api/generator/edit",
        json=_body(mode="cover", audio_cover_strength=0.75),
    )

    assert _released_payload(calls)["audio_cover_strength"] == 0.75


def test_complete_sends_only_the_task_type_and_the_source(
    auth_client, ace_on, monkeypatch
):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body())

    assert r.status_code == 200, r.text
    payload = _released_payload(calls)
    assert payload["task_type"] == "complete"
    assert payload["src_audio_path"] == ACE_FILE
    for absent in ("repainting_start", "repainting_end", "audio_cover_strength",
                   "chunk_mask_mode"):
        assert absent not in payload


def test_edit_without_a_prompt_sends_none(auth_client, ace_on, monkeypatch):
    """Empty = the page reuses the take's own prompt; nothing is invented."""
    calls = _install_ace(monkeypatch, _box())

    auth_client.post("/api/generator/edit", json=_body(prompt="   "))

    assert "prompt" not in _released_payload(calls)


def test_edit_pins_the_genre_bpm_when_a_genre_is_given(
    auth_client, ace_on, monkeypatch
):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(genre_folder="techno"))

    assert r.status_code == 200, r.text
    lo, hi = generator._genre_bpm_windows()["techno"]
    assert _released_payload(calls)["bpm"] == round((lo + hi) / 2)


def test_edit_without_a_genre_sends_no_bpm(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())
    auth_client.post("/api/generator/edit", json=_body())
    assert "bpm" not in _released_payload(calls)


def test_edit_422_on_an_unknown_genre_folder(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_body(genre_folder="polka"))

    assert r.status_code == 422
    assert "polka" in r.json()["detail"]
    assert calls == []


def test_edit_forwards_experimental_verbatim(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post(
        "/api/generator/edit",
        json=_repaint(experimental={"inference_steps": 16, "seed": 4242}),
    )

    assert r.status_code == 200, r.text
    payload = _released_payload(calls)
    assert payload["inference_steps"] == 16
    assert payload["seed"] == 4242


@pytest.mark.parametrize("key", [
    "task_type", "src_audio_path", "chunk_mask_mode", "repainting_start",
    "audio_cover_strength", "audio_format", "thinking",
])
def test_edit_422_when_experimental_shadows_a_server_field(
    auth_client, ace_on, monkeypatch, key
):
    """An ``experimental.task_type`` would turn a repaint into something
    else without the wizard ever saying so."""
    calls = _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_repaint(experimental={key: "x"}))

    assert r.status_code == 422
    assert key in r.text
    assert calls == []


def test_edit_forwards_the_api_key(auth_client, ace_on, monkeypatch):
    monkeypatch.setenv(ac.ENV_API_KEY, "sk-ace-edit")
    calls = _install_ace(monkeypatch, _box())

    auth_client.post("/api/generator/edit", json=_repaint())

    assert _releases(calls)[0].headers["authorization"] == "Bearer sk-ace-edit"


# ══ ETA — the same maths as POST /tasks ══════════════════════════════


def test_edit_returns_the_task_handle_and_eta(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch, _box())

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["task_id"] == "edit-1"
    assert payload["queue_position"] == 4
    # avg_job_seconds 41 × (queue_position 4 + running 1) = 205.
    assert payload["eta_seconds"] == 205
    # The shape POST /tasks returns, so the SAME poller serves both.
    assert set(payload) == {"task_id", "queue_position", "eta_seconds"}


def test_edit_eta_is_none_without_stats(auth_client, ace_on, monkeypatch):
    """A dead /v1/stats costs the countdown, never the edit."""
    _install_ace(monkeypatch, _box(stats=None))

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 200
    assert r.json()["eta_seconds"] is None


# ══ The TMPDIR degradation: JSON → multipart ═════════════════════════


def _refuse_absolute_once(detail=TMPDIR_REFUSAL):
    """First release 400s with ACE's TMPDIR complaint; the rest succeed."""

    def hook(request, n):
        if n == 1:
            return httpx.Response(400, json=_envelope(None, code=400, error=detail))
        return None

    return hook


def test_edit_degrades_to_a_multipart_upload(auth_client, ace_on, monkeypatch):
    """End to end: 400 → download the take → re-release as multipart."""
    calls = _install_ace(monkeypatch, _box(release_hook=_refuse_absolute_once()))

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 200, r.text
    # Same response shape as the direct path — the degradation is a
    # detail of how the take got there, not of what the wizard sees.
    assert r.json() == {"task_id": "edit-1", "queue_position": 4, "eta_seconds": 205}

    releases = _releases(calls)
    assert len(releases) == 2

    # 1st: the fast path, a path on ACE's own disk.
    assert json.loads(releases[0].content)["src_audio_path"] == ACE_FILE

    # In between: the take came back across the LAN, through the proxy's
    # canonical encoded form.
    audio = [c for c in calls if c.url.path == "/v1/audio"]
    assert len(audio) == 1
    assert audio[0].url.params.get("path") == ACE_FILE

    # 2nd: multipart, with the file attached under the spec's field name
    # and the path field GONE (it is what the box refused).
    fields, files = _multipart(releases[1])
    assert set(files) == {"src_audio"}
    filename, content = files["src_audio"]
    assert filename == "6f1c2b7e-9d4a-4c11-b0a3-2e5f8d7c1a90_0.wav"
    assert content == _SOURCE_BYTES
    assert "src_audio_path" not in fields

    # Every other field survived the encoding, flattened to text.
    assert fields["task_type"] == "repaint"
    assert fields["chunk_mask_mode"] == "explicit"
    assert fields["repainting_start"] == "10.0"
    assert fields["repainting_end"] == "20.0"
    assert fields["audio_format"] == "wav"
    assert fields["thinking"] == "true"


def test_the_degraded_upload_carries_the_api_key(auth_client, ace_on, monkeypatch):
    monkeypatch.setenv(ac.ENV_API_KEY, "sk-ace-edit")
    calls = _install_ace(monkeypatch, _box(release_hook=_refuse_absolute_once()))

    auth_client.post("/api/generator/edit", json=_repaint())

    assert _releases(calls)[1].headers["authorization"] == "Bearer sk-ace-edit"


@pytest.mark.parametrize("detail", [
    "absolute audio file paths are not allowed",
    "Absolute audio file paths are NOT allowed for security reasons",
    "400: absolute  audio   file   path is not allowed (use multipart)",
    "Error: the absolute audio file path given is not allowed",
])
def test_the_refusal_is_matched_tolerantly(auth_client, ace_on, monkeypatch, detail):
    """The sentence is ACE's to reword; a fatal error costs the operator
    the edit, so the match is a marker set, not an equality."""
    calls = _install_ace(
        monkeypatch, _box(release_hook=_refuse_absolute_once(detail=detail))
    )

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 200, r.text
    assert len(_releases(calls)) == 2


@pytest.mark.parametrize("detail", [
    "unknown task_type 'repaintt'",
    "repainting_end must be greater than repainting_start",
    "src_audio_path does not exist",
    "batch_size must be between 1 and 8",
])
def test_another_400_does_not_degrade(auth_client, ace_on, monkeypatch, detail):
    """A real bad request must not be answered by uploading 35 MB and
    failing the same way — it stays a 502 per the existing taxonomy."""
    calls = _install_ace(
        monkeypatch, _box(release_hook=_refuse_absolute_once(detail=detail))
    )

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 502
    assert detail in r.json()["detail"]
    # One release attempt, and the take never left ACE's disk.
    assert len(_releases(calls)) == 1
    assert [c for c in calls if c.url.path == "/v1/audio"] == []


def test_the_degraded_download_404_surfaces_as_404(auth_client, ace_on, monkeypatch):
    """The result file is gone — say so instead of a blank 502."""
    calls = _install_ace(
        monkeypatch, _box(release_hook=_refuse_absolute_once(), audio=None)
    )

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 404
    assert len(_releases(calls)) == 1


def test_a_degraded_release_that_fails_again_is_a_502(
    auth_client, ace_on, monkeypatch
):
    def refuse_twice(request, n):
        return httpx.Response(
            400, json=_envelope(None, code=400, error=TMPDIR_REFUSAL)
        )

    calls = _install_ace(monkeypatch, _box(release_hook=refuse_twice))

    r = auth_client.post("/api/generator/edit", json=_repaint())

    assert r.status_code == 502
    # Degraded once, not in a loop.
    assert len(_releases(calls)) == 2


def test_the_cover_degradation_keeps_its_strength(auth_client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch, _box(release_hook=_refuse_absolute_once()))

    r = auth_client.post(
        "/api/generator/edit",
        json=_body(mode="cover", audio_cover_strength=0.35),
    )

    assert r.status_code == 200, r.text
    fields, files = _multipart(_releases(calls)[1])
    assert fields["task_type"] == "cover"
    assert fields["audio_cover_strength"] == "0.35"
    assert "src_audio" in files


# ══ The client's multipart lane, as a unit ═══════════════════════════


async def test_release_task_multipart_shape(monkeypatch):
    """The minimal capability added to the client for the lane above."""
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_envelope(_RELEASED))

    client = ac.AceStepClient(transport=httpx.MockTransport(handler))
    got = await client.release_task(
        {
            "task_type": "cover",
            "thinking": True,
            "bpm": 138,
            "audio_cover_strength": 0.2,
            "nothing": None,
            "nested": {"a": 1},
        },
        files={"src_audio": ("take.wav", _SOURCE_BYTES, "audio/wav")},
    )

    assert got.task_id == "edit-1"
    fields, files = _multipart(seen[0])
    assert files["src_audio"] == ("take.wav", _SOURCE_BYTES)
    assert fields["task_type"] == "cover"
    # Booleans go out lower-case (pydantic reads those); None is empty;
    # anything structured falls back to JSON.
    assert fields["thinking"] == "true"
    assert fields["bpm"] == "138"
    assert fields["audio_cover_strength"] == "0.2"
    assert fields["nothing"] == ""
    assert json.loads(fields["nested"]) == {"a": 1}


async def test_release_task_stays_json_without_files(monkeypatch):
    """The default shape is untouched — no existing caller changes."""
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_envelope(_RELEASED))

    client = ac.AceStepClient(transport=httpx.MockTransport(handler))
    await client.release_task({"prompt": "x", "thinking": True})

    assert seen[0].headers["content-type"] == "application/json"
    assert json.loads(seen[0].content) == {"prompt": "x", "thinking": True}
