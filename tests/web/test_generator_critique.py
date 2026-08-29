"""G4 — ``POST /api/generator/critique``: the bench scores, the LLM reads.

Three halves, in the order they can fail:

1. **The score.** A MockTransport ACE box serves a REAL synthetic WAV and
   the handler runs the REAL ``bench_wav`` over it. Bands are never
   guessed: every case measures the very bytes the box will serve
   (``load_wav_mono`` + ``analyze_wav``, exactly what the bench does) and
   then writes a references file whose ranges sit around those numbers
   (pass) or far outside them (fail). The fail bands clear the bench's
   own margins — 2.5x on centroid, ±8 dB/oct on tilt — on purpose, the
   ``tests/test_quality_bench_wav.py`` (#127) pattern: a band that merely
   *looks* disjoint gets widened back into a pass.
2. **The read.** The LLM layer is exercised only through a monkeypatched
   ``_llm_paragraph`` seam, and the autouse fixture below pins
   ``AGENT_PROVIDER=mock`` so a test that forgets to opt in cannot reach
   the tunnelled gateway. Present → a paragraph; absent, timed out,
   raising or garbage → ``critique: null``, never an error.
3. **The refusals.** Auth, path validation, 503, and the reference-less
   genre that answers 200 with a note rather than a status code.

No socket is ever opened toward a real ACE box or a real LLM.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

from agent.generative.bench import load_wav_mono
from agent.generative.quality import NORM_TARGET_LUFS, analyze_wav
from agent.generative.render_audio import SR
from web.backend import acestep_client as ac
from web.backend import generator
from web.backend.ws_manager import ws_manager


# ── Helpers ──────────────────────────────────────────────────────────

ACE_ROOT = generator.DEFAULT_AUDIO_ROOTS[0]
ACE_FILE = f"{ACE_ROOT}/9d0f4a21-77c3-4a55-9a10-5f2b7c8e3d61_0.wav"

#: The references file this suite writes is keyed by the genre the folder
#: resolves to — ``deep house`` scores against the bench's ``deep``.
GENRE_FOLDER = "deep house"
REFERENCE_GENRE = "deep"

#: Every LLM env the provider detection looks at, so an ambient ``.env``
#: (this dev box exports one) can never steer a test at a real endpoint.
_PROVIDER_ENV = (
    "AGENT_PROVIDER",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "LITELLM_BASE_URL",
    "LITELLM_API_KEY",
    "OLLAMA_BASE_URL",
    "AGENT_MODEL",
    "GENERATIVE_MODEL",
)


def _write_wav(path: Path, seconds: float = 2.0, freq: float = 220.0,
               amp: float = 0.3, seed: int = 7) -> Path:
    """A tone with a little noise — loud enough for LUFS, tilted enough for slope.

    Written at the bench's own rate so ``load_wav_mono`` never reaches for
    librosa: this suite is about the endpoint, not about resampling.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    mono = amp * np.sin(2 * np.pi * freq * t) + 0.02 * rng.standard_normal(t.size)
    sf.write(str(path), mono.astype(np.float32), SR)
    return path


def _bands_around(metrics: dict, *, matching: bool) -> dict:
    """Reference ranges built around what the audio MEASURED (#127 pattern)."""
    ri = metrics["reference_informed"]
    c, t = ri["centroid_hz"], ri["tilt_db_per_oct"]
    if matching:
        return {
            "centroid_hz": {"min": round(c * 0.95, 1), "max": round(c * 1.05, 1)},
            "tilt_db_per_oct": {"min": round(t - 0.5, 2), "max": round(t + 0.5, 2)},
        }
    # Clear of the bench's margins (2.5x / ±8) so the fail cannot be
    # widened back into a pass.
    return {
        "centroid_hz": {"min": round(c * 10, 1), "max": round(c * 20, 1)},
        "tilt_db_per_oct": {"min": round(t + 30, 2), "max": round(t + 40, 2)},
    }


def _write_references(path: Path, metrics: dict, *, matching: bool = True,
                      genre: str = REFERENCE_GENRE) -> Path:
    payload = {
        genre: {
            "files": ["synthetic.wav"],
            "norm_target_lufs": NORM_TARGET_LUFS,
            **_bands_around(metrics, matching=matching),
            "advisory_lufs": {"min": -20.0, "max": -16.0},
        }
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _envelope(data, *, code: int = 200, error=None) -> dict:
    return {
        "data": data, "code": code, "error": error,
        "timestamp": 1700000000000, "extra": None,
    }


def _install_ace(monkeypatch, audio: bytes | None = None, audio_status: int = 200):
    """Point ``generator._client`` at a MockTransport; return the call log."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/audio":
            if audio_status >= 400:
                return httpx.Response(
                    audio_status,
                    json=_envelope(None, code=audio_status, error="no such file"),
                )
            return httpx.Response(
                200, content=audio or b"", headers={"content-type": "audio/wav"}
            )
        if request.url.path == "/health":
            return httpx.Response(200, json=_envelope({"status": "ok"}))
        return httpx.Response(404, json=_envelope(None, code=404, error="nope"))

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        generator, "_client", lambda: ac.AceStepClient(transport=transport)
    )
    return calls


def _body(**over) -> dict:
    body = {
        "file": ACE_FILE,
        "metas": {"bpm": 122, "keyscale": "A Minor", "duration": 181.4},
        "prompt": "warm deep house, dusty rhodes, patient groove",
        "genre_folder": GENRE_FOLDER,
    }
    body.update(over)
    return body


class _FakeWS:
    """Stand-in for the WebSocket object the live handler registers."""


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """No test reaches a real provider unless it opts in, loudly.

    ``mock`` short-circuits ``_critique_paragraph`` before any SDK
    import, which is the same switch the E2E runs use.
    """
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")


@pytest.fixture(autouse=True)
def clean_live_registry():
    saved = dict(ws_manager._connections)
    ws_manager._connections.clear()
    yield ws_manager._connections
    ws_manager._connections.clear()
    ws_manager._connections.update(saved)


@pytest.fixture
def ace_off(monkeypatch):
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)


@pytest.fixture
def ace_on(monkeypatch):
    monkeypatch.setenv(ac.ENV_BASE_URL, "http://ace.test:8001")
    monkeypatch.delenv(ac.ENV_API_KEY, raising=False)
    monkeypatch.delenv(generator.ENV_AUDIO_ROOT, raising=False)


@pytest.fixture
def take(tmp_path) -> tuple[bytes, dict]:
    """(the bytes ACE will serve, what the bench measures in them)."""
    wav = _write_wav(tmp_path / "take.wav")
    return wav.read_bytes(), analyze_wav(load_wav_mono(wav)[0], SR)


@pytest.fixture
def in_band(tmp_path, take, monkeypatch) -> dict:
    """References built to PASS this take; returns its measurements."""
    audio, metrics = take
    refs = _write_references(tmp_path / "refs.json", metrics, matching=True)
    monkeypatch.setenv(generator.ENV_BENCH_REFERENCES, str(refs))
    return metrics


@pytest.fixture
def out_of_band(tmp_path, take, monkeypatch) -> dict:
    """References built to FAIL this take; returns its measurements."""
    audio, metrics = take
    refs = _write_references(tmp_path / "refs.json", metrics, matching=False)
    monkeypatch.setenv(generator.ENV_BENCH_REFERENCES, str(refs))
    return metrics


def _stub_llm(monkeypatch, fn):
    """Wire the ONE seam that talks to a provider, and turn the gate on."""
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    monkeypatch.setattr(generator, "_llm_paragraph", fn)


# ══ Auth ═════════════════════════════════════════════════════════════


def test_critique_requires_auth(client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch)
    assert client.post("/api/generator/critique", json=_body()).status_code == 401
    assert calls == []


def test_critique_rejects_a_bad_token(client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    r = client.post(
        "/api/generator/critique",
        json=_body(),
        headers={"Authorization": "Bearer garbage"},
    )
    assert r.status_code == 401


# ══ The score ════════════════════════════════════════════════════════


def test_critique_scores_an_in_band_take(
    auth_client, ace_on, monkeypatch, take, in_band
):
    audio, _ = take
    calls = _install_ace(monkeypatch, audio=audio)

    r = auth_client.post("/api/generator/critique", json=_body())

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["passed"] is True
    assert payload["failures"] == []
    assert payload["note"] is None
    assert payload["reference_genre"] == REFERENCE_GENRE

    # The measured numbers travel, not just the verdict.
    ri = payload["reference_informed"]
    assert ri["centroid_hz"] == pytest.approx(
        in_band["reference_informed"]["centroid_hz"]
    )
    assert ri["tilt_db_per_oct"] == pytest.approx(
        in_band["reference_informed"]["tilt_db_per_oct"]
    )
    adv = payload["advisory"]
    assert set(adv) == {"lufs", "lra", "crest_db"}
    assert adv["lufs"] == pytest.approx(in_band["advisory"]["lufs"])

    # …and each one sits inside the band the response reports.
    for key in ("centroid_hz", "tilt_db_per_oct"):
        band = payload["bands"][key]
        assert band["min"] <= ri[key] <= band["max"]

    # The download went through the proxy's canonical form.
    audio_calls = [c for c in calls if c.url.path == "/v1/audio"]
    assert len(audio_calls) == 1
    assert audio_calls[0].url.params.get("path") == ACE_FILE


def test_critique_bands_widen_the_reference_range_by_the_bench_margins(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """The chip's band must be the band that decides ``passed``.

    Reporting the raw catalog range would make a chip read "out of band"
    for a value the bench happily passed — a UI contradicting the verdict
    printed next to it. The raw range still travels, alongside.
    """
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    bands = auth_client.post("/api/generator/critique", json=_body()).json()["bands"]

    centroid = bands["centroid_hz"]
    assert centroid["min"] == pytest.approx(centroid["reference_min"] / 2.5, rel=1e-3)
    assert centroid["max"] == pytest.approx(centroid["reference_max"] * 2.5, rel=1e-3)
    tilt = bands["tilt_db_per_oct"]
    assert tilt["min"] == pytest.approx(tilt["reference_min"] - 8.0, abs=0.01)
    assert tilt["max"] == pytest.approx(tilt["reference_max"] + 8.0, abs=0.01)
    # Nothing advisory can fail, so its band IS the reference range.
    lufs = bands["advisory_lufs"]
    assert (lufs["min"], lufs["max"]) == (lufs["reference_min"], lufs["reference_max"])


def test_critique_renders_an_out_of_band_take(
    auth_client, ace_on, monkeypatch, take, out_of_band
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    assert payload["passed"] is False
    joined = " ".join(payload["failures"])
    assert "centroid" in joined and "tilt" in joined
    # The value really is outside the band the response reports, so the
    # chips and the failure list cannot disagree.
    ri, bands = payload["reference_informed"], payload["bands"]
    for key in ("centroid_hz", "tilt_db_per_oct"):
        assert not bands[key]["min"] <= ri[key] <= bands[key]["max"]


def test_critique_is_allowed_during_a_live_session(
    auth_client, ace_on, monkeypatch, take, in_band, clean_live_registry
):
    """No 409: the bench runs on the CPU and parks no VRAM."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()

    r = auth_client.post("/api/generator/critique", json=_body())

    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True


def test_critique_accepts_the_raw_file_field_shape(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """A page that persisted ACE's ``file`` verbatim still scores."""
    from urllib.parse import quote

    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    encoded = f"/v1/audio?path={quote(ACE_FILE, safe='')}"

    r = auth_client.post("/api/generator/critique", json=_body(file=encoded))

    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True


# ══ No verdict: a genre nobody has references for ════════════════════


def test_critique_without_references_answers_a_note_not_an_error(
    auth_client, ace_on, monkeypatch, take, in_band
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    r = auth_client.post("/api/generator/critique", json=_body(genre_folder="techno"))

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["passed"] is None
    assert payload["reference_informed"] is None
    assert payload["advisory"] is None
    assert payload["bands"] is None
    assert payload["critique"] is None
    assert payload["failures"] == []
    # The bench's OWN words, naming the genre and what IS available.
    assert "no references for genre 'techno'" in payload["note"]
    assert f"has: {REFERENCE_GENRE}" in payload["note"]


def test_critique_without_references_never_calls_the_llm(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """Nothing to read means nothing to ask about."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    called: list[str] = []
    _stub_llm(monkeypatch, lambda s, u, p: called.append(u) or "should not happen")

    r = auth_client.post("/api/generator/critique", json=_body(genre_folder="techno"))

    assert r.json()["critique"] is None
    assert called == []


def test_critique_keeps_every_key_present_without_a_verdict(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """The poll endpoint's rule: a UI must never feature-detect."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    scored = auth_client.post("/api/generator/critique", json=_body()).json()
    unscored = auth_client.post(
        "/api/generator/critique", json=_body(genre_folder="techno")
    ).json()

    assert set(scored) == set(unscored)


# ══ The LLM read ═════════════════════════════════════════════════════


def test_critique_carries_the_llm_paragraph(
    auth_client, ace_on, monkeypatch, take, in_band
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    seen: dict = {}

    def fake(system: str, user: str, provider: str) -> str:
        seen.update(system=system, user=user, provider=provider)
        return "  It matches the brief.\nThe top end could open up.  "

    _stub_llm(monkeypatch, fake)

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    # Collapsed to one line of prose, verbatim otherwise.
    assert payload["critique"] == "It matches the brief. The top end could open up."
    assert payload["passed"] is True
    # The model is briefed with what was ASKED and what was MEASURED —
    # both halves of "does this take match?".
    assert "warm deep house, dusty rhodes" in seen["user"]
    assert "spectral centroid" in seen["user"] and "band " in seen["user"]
    assert "122 BPM" in seen["user"] and "key A Minor" in seen["user"]
    assert "Bench verdict: PASS" in seen["user"]
    # …and never with a filesystem path.
    assert ACE_FILE not in seen["user"]
    assert seen["provider"] == "ollama"


def test_critique_llm_off_degrades_to_null(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """``AGENT_PROVIDER=mock`` (the offline switch) — score, no read."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    assert payload["passed"] is True
    assert payload["critique"] is None


def test_critique_llm_timeout_degrades_to_null(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """A slow gateway costs the read, never the score."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    monkeypatch.setattr(generator, "CRITIQUE_TIMEOUT_SEC", 0.05)
    _stub_llm(monkeypatch, lambda s, u, p: time.sleep(0.3) or "too late to matter")

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    assert payload["critique"] is None
    assert payload["passed"] is True          # the score is unaffected


def test_critique_paragraph_returns_at_the_deadline(monkeypatch):
    """The bound is hard: the await comes back, the thread is abandoned.

    Timed INSIDE the loop on purpose — an abandoned worker still delays
    ``asyncio.run``'s own shutdown, which is an artifact of tearing a loop
    down per call and not something the wizard ever waits for.
    """
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    monkeypatch.setattr(generator, "CRITIQUE_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(
        generator, "_llm_paragraph", lambda s, u, p: time.sleep(2.0) or "late"
    )
    req = generator.CritiqueRequest(file=ACE_FILE, genre_folder=GENRE_FOLDER)

    async def timed():
        started = time.monotonic()
        out = await generator._critique_paragraph(req, {}, None)
        return out, time.monotonic() - started

    critique, elapsed = asyncio.run(timed())

    assert critique is None
    assert elapsed < 1.0


def test_critique_llm_failure_degrades_to_null(
    auth_client, ace_on, monkeypatch, take, in_band
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)

    def boom(system: str, user: str, provider: str) -> str:
        raise RuntimeError("connection refused")

    _stub_llm(monkeypatch, boom)

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    assert payload["critique"] is None
    assert payload["passed"] is True


def test_critique_llm_is_called_exactly_once(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """No retry: a second wait for the least important thing on the panel."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    calls: list[int] = []

    def boom(system: str, user: str, provider: str) -> str:
        calls.append(1)
        raise RuntimeError("nope")

    _stub_llm(monkeypatch, boom)

    auth_client.post("/api/generator/critique", json=_body())

    assert len(calls) == 1


@pytest.mark.parametrize(
    "reply", ["", "   ", "<think>only thinking, no answer</think>   "]
)
def test_critique_garbage_reply_degrades_to_null(
    auth_client, ace_on, monkeypatch, take, in_band, reply
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    _stub_llm(monkeypatch, lambda s, u, p: reply)

    assert auth_client.post(
        "/api/generator/critique", json=_body()
    ).json()["critique"] is None


def test_critique_llm_sees_the_failures_when_the_bench_fails(
    auth_client, ace_on, monkeypatch, take, out_of_band
):
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    seen: dict = {}
    _stub_llm(
        monkeypatch,
        lambda s, u, p: seen.update(user=u) or "Too bright for the genre.",
    )

    payload = auth_client.post("/api/generator/critique", json=_body()).json()

    assert payload["critique"] == "Too bright for the genre."
    assert "Bench verdict: FAIL" in seen["user"]
    assert "centroid" in seen["user"]


# ══ Refusals ═════════════════════════════════════════════════════════


def test_critique_503_when_the_generator_is_disabled(auth_client, ace_off):
    r = auth_client.post("/api/generator/critique", json=_body())
    assert r.status_code == 503
    assert "not available" in r.json()["detail"]


@pytest.mark.parametrize(
    "bad",
    [
        "http://evil.test/v1/audio?path=x",          # a host: SSRF hop
        "//evil.test/x.wav",
        "C:\\Users\\pablo\\secrets.wav",             # a local file
        "api_audio/relative.wav",                    # never enough to download
        "/etc/passwd",                               # outside the ACE root
        f"{ACE_ROOT}/../../etc/passwd",              # traversal
    ],
)
def test_critique_refuses_a_bad_path(auth_client, ace_on, monkeypatch, bad):
    calls = _install_ace(monkeypatch)
    r = auth_client.post("/api/generator/critique", json=_body(file=bad))
    assert r.status_code == 422, r.text
    # Refused before a single byte crossed the LAN.
    assert [c for c in calls if c.url.path == "/v1/audio"] == []


def test_critique_missing_audio_is_a_404(auth_client, ace_on, monkeypatch, in_band):
    _install_ace(monkeypatch, audio_status=404)
    r = auth_client.post("/api/generator/critique", json=_body())
    assert r.status_code == 404


def test_critique_forbids_unknown_body_fields(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    r = auth_client.post("/api/generator/critique", json=_body(task_id="t-1"))
    assert r.status_code == 422
    # The persistence rule: there is no task_id in this contract.
    assert "task_id" in r.text


def test_critique_metas_ignores_unknown_fields(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """``metas`` belongs to ACE — an added field must not 422 a score."""
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    metas = {
        "bpm": 122, "keyscale": "A Minor", "duration": 181.4,
        "genres": "deep house", "timesignature": "4", "loudness_lufs": -9.1,
    }

    r = auth_client.post("/api/generator/critique", json=_body(metas=metas))

    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True


def test_critique_scores_a_take_whose_metas_never_parsed(
    auth_client, ace_on, monkeypatch, take, in_band
):
    """Weaker than publish on purpose: scoring writes nothing.

    A take with no bpm and no key is exactly the one an operator most
    wants a second opinion on, so it is scored — the missing facts are
    simply missing from the LLM's brief.
    """
    audio, _ = take
    _install_ace(monkeypatch, audio=audio)
    seen: dict = {}
    _stub_llm(monkeypatch, lambda s, u, p: seen.update(user=u) or "Fine.")

    r = auth_client.post("/api/generator/critique", json=_body(metas={}))

    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True
    assert "Reported metadata: none reported" in seen["user"]


def test_critique_rejects_an_out_of_range_bpm(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    r = auth_client.post(
        "/api/generator/critique",
        json=_body(metas={"bpm": 9000, "keyscale": "A Minor"}),
    )
    assert r.status_code == 422


def test_critique_requires_a_genre_folder(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    body = _body()
    body.pop("genre_folder")
    assert auth_client.post("/api/generator/critique", json=body).status_code == 422


# ══ Units: the pure halves ═══════════════════════════════════════════

FOLDERS = {
    "lofi": "lofi - ambient",
    "ambient": "lofi - ambient",
    "deep": "deep house",
}


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("deep house", "deep"),
        ("Deep House", "deep"),
        ("  deep house  ", "deep"),
        # Two genres share this folder; the folder's leading text decides,
        # so it scores as lofi rather than as sorted-first ambient.
        ("lofi - ambient", "lofi"),
        # A folder no genre claims passes through, so the bench's own
        # refusal is what names it.
        ("techno", "techno"),
        ("", ""),
    ],
)
def test_reference_genre_mapping(folder, expected):
    assert generator._reference_genre(folder, FOLDERS) == expected


def test_reference_genre_is_deterministic_without_a_prefix_match():
    """Ambiguity resolves by sort order, not by dict iteration order."""
    folders = {"zulu": "shared folder", "alpha": "shared folder"}
    assert generator._reference_genre("shared folder", folders) == "alpha"
    assert generator._reference_genre("shared folder", dict(reversed(list(
        folders.items())))) == "alpha"


def test_reference_bands_are_none_without_a_reference():
    assert generator._reference_bands({}, centroid_ratio=2.5, tilt_delta=8.0) is None


def test_reference_bands_drop_a_metric_with_no_usable_range():
    """A half-written references entry costs that chip, not the response."""
    bands = generator._reference_bands(
        {"centroid_hz": {"min": 100.0, "max": None},
         "tilt_db_per_oct": {"min": -4.0, "max": -3.0}},
        centroid_ratio=2.5, tilt_delta=8.0,
    )
    assert set(bands) == {"tilt_db_per_oct"}


def test_reference_bands_reject_booleans_as_numbers():
    """``True`` is an ``int`` — a band of [True, True] would be nonsense."""
    assert generator._reference_bands(
        {"centroid_hz": {"min": True, "max": True}},
        centroid_ratio=2.5, tilt_delta=8.0,
    ) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   \n  ", None),
        ("<think>hmm</think>", None),
        ("one\n\ntwo   three", "one two three"),
        ("<think>plan</think>\nThe verdict.", "The verdict."),
        ("```\nfenced prose\n```", "fenced prose"),
    ],
)
def test_clean_paragraph(raw, expected):
    assert generator._clean_paragraph(raw) == expected


def test_clean_paragraph_caps_a_runaway_reply():
    """A model that ignores "one paragraph" cannot flood the take row."""
    capped = generator._clean_paragraph("word " * 5000)
    # ``<=``, not ``==``: the cut can land mid-word and the trailing
    # space is stripped afterwards.
    assert generator.CRITIQUE_MAX_CHARS - 8 <= len(capped) <= generator.CRITIQUE_MAX_CHARS


def test_resolve_critique_model_precedence(monkeypatch):
    """GENERATIVE_MODEL > AGENT_MODEL > the provider default (#123)."""
    monkeypatch.delenv("GENERATIVE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert generator._resolve_critique_model("ollama") == "gemma4:4b"

    monkeypatch.setenv("AGENT_MODEL", "the-dj-model")
    assert generator._resolve_critique_model("ollama") == "the-dj-model"

    monkeypatch.setenv("GENERATIVE_MODEL", "the-critic-model")
    assert generator._resolve_critique_model("ollama") == "the-critic-model"


def test_resolve_critique_model_uses_the_azure_deployment(monkeypatch):
    monkeypatch.delenv("GENERATIVE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-deployment")
    assert generator._resolve_critique_model("azure") == "gpt-deployment"


def test_llm_paragraph_refuses_a_provider_with_no_model(monkeypatch):
    """No model configured is a refusal, not a call at a default URL."""
    monkeypatch.delenv("GENERATIVE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="no model configured"):
        generator._llm_paragraph("sys", "user", "unknown-provider")


def test_critique_paragraph_is_null_when_the_provider_is_mock(monkeypatch):
    """The offline switch short-circuits before any SDK import."""
    monkeypatch.setenv("AGENT_PROVIDER", "mock")

    def explode(*args, **kwargs):
        raise AssertionError("the seam must not be reached")

    monkeypatch.setattr(generator, "_llm_paragraph", explode)
    req = generator.CritiqueRequest(file=ACE_FILE, genre_folder=GENRE_FOLDER)

    assert asyncio.run(generator._critique_paragraph(req, {}, None)) is None


def test_critique_brief_survives_a_report_with_nothing_in_it():
    """The brief is built from ``.get``s: a thin report is thin prose."""
    req = generator.CritiqueRequest(file=ACE_FILE, genre_folder=GENRE_FOLDER)
    brief = generator._critique_brief(req, {}, None)
    assert "(no prompt recorded)" in brief
    assert "no band" in brief
    assert "Reported metadata: none reported" in brief
