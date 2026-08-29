"""G2b — ``POST /api/generator/publish`` + the shared audio-path validator.

Two halves:

1. **The endpoint, end to end.** A MockTransport ACE box serves a real
   (silent) 121 s WAV; the handler downloads it and runs the REAL
   ``main.ingest_track`` against a tmp ``tracks/`` tree — the same
   ``monkeypatch.chdir`` trick ``tests/test_ingest.py`` uses, since
   ``main``'s ``TRACKS_BASE_DIR`` / ``CATALOG_PATH`` are relative. So
   these tests exercise the ingest for real: the WAV lands, tracks.json
   grows, the ``.lrc`` appears, and every refusal comes back in the
   ingest's own words.
2. **``validate_ace_audio_path``** as a unit, both accepted shapes and
   the garbage list, because it is the ONE function the audio proxy and
   the publisher share (flipping the accepted shape must be a constant
   change, not a refactor).

No socket is ever opened toward a real generation box (the G0/G1
convention) and no test touches the developer's real catalog.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from web.backend import acestep_client as ac
from web.backend import generator
from web.backend.ws_manager import ws_manager


# ── Helpers ──────────────────────────────────────────────────────────

#: The real shape, confirmed with the ACE session: an absolute POSIX
#: path on their box, under the tmp api_audio root, ``<uuid>_<take>.wav``.
ACE_ROOT = generator.DEFAULT_AUDIO_ROOTS[0]
ACE_FILE = f"{ACE_ROOT}/6f1c2b7e-9d4a-4c11-b0a3-2e5f8d7c1a90_0.wav"

#: The same file in ACE's own wire form — ``quote(p, safe="")``, so every
#: slash arrives as ``%2F``. The inner path is root-checked on EVERY
#: route now, so this is the only endpoint shape either mode accepts.
ACE_ENDPOINT_FILE = f"/v1/audio?path={quote(ACE_FILE, safe='')}"

#: Over the 120 s session-eligibility floor.
LONG_SEC = 121


def _wav_bytes(path: Path, seconds: float, rate: int = 44100, channels: int = 2) -> bytes:
    """A real, catalog-conformant (44.1 kHz/16-bit/stereo) silent WAV."""
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00" * (frames * channels * 2))
    return path.read_bytes()


@pytest.fixture(scope="module")
def long_wav(tmp_path_factory) -> bytes:
    d = tmp_path_factory.mktemp("ace_takes")
    return _wav_bytes(d / "take.wav", LONG_SEC)


@pytest.fixture(scope="module")
def short_wav(tmp_path_factory) -> bytes:
    d = tmp_path_factory.mktemp("ace_short")
    return _wav_bytes(d / "short.wav", 30.0)


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
        "metas": {"bpm": 138, "keyscale": "A Minor", "duration": 181.4},
        "prompt": "dark melodic techno, hypnotic, driving",
        "display_name": "Neon Rain",
        "genre_folder": "techno",
    }
    body.update(over)
    return body


def _read_catalog(tracks: Path) -> list[dict]:
    return json.loads((tracks / "tracks.json").read_text(encoding="utf-8"))["tracks"]


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
def tmp_catalog(tmp_path, monkeypatch) -> Path:
    """A tmp ``tracks/`` tree, with ``main``'s relative paths pointed at it.

    Same shape as ``tests/test_ingest.py``'s ``catalog`` fixture — the
    endpoint runs the real ingest, so it needs the real tree.
    """
    monkeypatch.chdir(tmp_path)
    tracks = tmp_path / "tracks"
    (tracks / "techno").mkdir(parents=True)
    (tracks / "healing").mkdir(parents=True)
    (tracks / "tracks.json").write_text(
        json.dumps({"tracks": [{
            "id": "techno--old-signal",
            "display_name": "Old Signal",
            "file": "tracks/techno/Old Signal.wav",
            "genre_folder": "techno",
            "genre": "techno",
            "camelot_key": "5A",
            "bpm": 138.0,
            "variant_of": None,
        }]}, indent=2),
        encoding="utf-8",
    )
    return tracks


# ══ Auth ═════════════════════════════════════════════════════════════


def test_publish_requires_auth(client, ace_on, monkeypatch):
    calls = _install_ace(monkeypatch)
    assert client.post("/api/generator/publish", json=_body()).status_code == 401
    assert calls == []


def test_publish_rejects_a_bad_token(client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    r = client.post(
        "/api/generator/publish",
        json=_body(),
        headers={"Authorization": "Bearer garbage"},
    )
    assert r.status_code == 401


# ══ Happy path ═══════════════════════════════════════════════════════


def test_publish_lands_the_take_in_the_catalog(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    calls = _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post("/api/generator/publish", json=_body())

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["track_id"] == "techno--neon-rain"
    assert payload["file"] == "tracks/techno/Neon Rain.wav"
    assert payload["display_name"] == "Neon Rain"
    assert payload["camelot_key"] == "8A"
    assert payload["bpm"] == 138.0
    assert payload["variant_of"] is None
    assert "--fix-incomplete" in payload["note"]

    # The WAV really landed, bit-exact (a conformant source is copied).
    dest = tmp_catalog / "techno" / "Neon Rain.wav"
    assert dest.read_bytes() == long_wav

    # …and the catalog grew by exactly one entry, with the echoed shape.
    entries = _read_catalog(tmp_catalog)
    assert len(entries) == 2
    assert entries[-1]["id"] == payload["track_id"]
    assert entries[-1]["camelot_key"] == "8A"

    # The download went through the proxy's canonical form, and the
    # inner path arrived decoded on ACE's side.
    audio = [c for c in calls if c.url.path == "/v1/audio"]
    assert len(audio) == 1
    assert audio[0].url.params.get("path") == ACE_FILE
    assert audio[0].url.host == "ace.test"


def test_publish_backs_the_catalog_up_before_writing(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    before = _read_catalog(tmp_catalog)
    _install_ace(monkeypatch, audio=long_wav)

    assert auth_client.post("/api/generator/publish", json=_body()).status_code == 200

    backups = list(tmp_catalog.glob("tracks.json.*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["tracks"] == before


def test_publish_forwards_the_api_key(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    monkeypatch.setenv(ac.ENV_API_KEY, "sk-ace-publish")
    calls = _install_ace(monkeypatch, audio=long_wav)

    auth_client.post("/api/generator/publish", json=_body())

    audio = [c for c in calls if c.url.path == "/v1/audio"]
    assert audio[0].headers["authorization"] == "Bearer sk-ace-publish"


def test_publish_accepts_the_raw_file_field_shape(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    """A page that persisted ACE's ``file`` verbatim still publishes.

    The contract asks for the DECODED path, but the encoded endpoint
    form carries the same information and unwrapping it costs one call
    into the shared validator.
    """
    from urllib.parse import quote

    _install_ace(monkeypatch, audio=long_wav)
    encoded = f"/v1/audio?path={quote(ACE_FILE, safe='')}"

    r = auth_client.post("/api/generator/publish", json=_body(file=encoded))

    assert r.status_code == 200, r.text
    assert r.json()["track_id"] == "techno--neon-rain"


def test_publish_is_allowed_during_a_live_session(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav, clean_live_registry
):
    """No 409: publishing touches the disk, not the GPU."""
    _install_ace(monkeypatch, audio=long_wav)
    clean_live_registry[("sess-live", generator.LIVE_WS_CHANNEL)] = _FakeWS()

    r = auth_client.post("/api/generator/publish", json=_body())

    assert r.status_code == 200, r.text


# ══ Lyrics ═══════════════════════════════════════════════════════════


def test_publish_lyrics_text_lands_as_an_lrc(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    """The wire carries TEXT (the sidecar's semantics), not a filename."""
    _install_ace(monkeypatch, audio=long_wav)
    words = "[Verse]\nneon rain on the window\n\n[Chorus]\nstay"

    r = auth_client.post("/api/generator/publish", json=_body(lyrics=words))

    assert r.status_code == 200, r.text
    lrc = tmp_catalog / "techno" / "Neon Rain.lrc"
    assert lrc.read_text(encoding="utf-8") == words


def test_publish_without_lyrics_writes_no_lrc(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)
    auth_client.post("/api/generator/publish", json=_body(lyrics="   "))
    assert not (tmp_catalog / "techno" / "Neon Rain.lrc").exists()


# ══ variant_of ═══════════════════════════════════════════════════════


def test_publish_variant_of_resolves_to_the_base_display_name(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(display_name="Old Signal", variant_of="techno--old-signal"),
    )

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["track_id"] == "techno--old-signal-v2"
    assert payload["variant_of"] == "Old Signal"
    assert payload["file"] == "tracks/techno/Old Signal (1).wav"
    assert (tmp_catalog / "techno" / "Old Signal (1).wav").exists()


def test_publish_variant_by_display_name(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(display_name="Old Signal", variant_of="Old Signal"),
    )

    assert r.status_code == 200, r.text
    assert r.json()["track_id"] == "techno--old-signal-v2"


def test_publish_dangling_variant_of_is_refused_verbatim(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish", json=_body(variant_of="techno--nothing")
    )

    assert r.status_code == 422
    assert "matches no catalog id or display_name" in r.json()["detail"]


# ══ Ingest refusals, passed through verbatim ═════════════════════════


def test_publish_422_on_a_short_take(
    auth_client, ace_on, monkeypatch, tmp_catalog, short_wav
):
    """No declared duration ⇒ the refusal comes from the probed file."""
    _install_ace(monkeypatch, audio=short_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={"bpm": 138, "keyscale": "A Minor"}),
    )

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "30.0s" in detail and "120s minimum" in detail
    assert not (tmp_catalog / "techno" / "Neon Rain.wav").exists()
    assert len(_read_catalog(tmp_catalog)) == 1


def test_publish_422_before_downloading_when_metas_declare_a_short_take(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    """The cheap pre-flight: refused without pulling 35 MB across the LAN."""
    calls = _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={"bpm": 138, "keyscale": "A Minor", "duration": 44.0}),
    )

    assert r.status_code == 422
    assert "44.0s" in r.json()["detail"]
    assert calls == []


def test_publish_422_on_an_unknown_genre_folder(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post("/api/generator/publish", json=_body(genre_folder="synthware"))

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "synthware" in detail
    # It lists what does exist, exactly as the CLI does.
    assert "techno" in detail and "healing" in detail


def test_publish_422_on_a_bpm_outside_the_genre_window(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={"bpm": 90, "keyscale": "A Minor", "duration": 181.4}),
    )

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "90" in detail and "120-160" in detail
    assert len(_read_catalog(tmp_catalog)) == 1


def test_publish_422_on_an_unparseable_keyscale(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={"bpm": 138, "keyscale": "H Dorian", "duration": 181.4}),
    )

    assert r.status_code == 422
    assert "H Dorian" in r.json()["detail"]


def test_publish_422_on_an_id_collision(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)
    assert auth_client.post("/api/generator/publish", json=_body()).status_code == 200

    r = auth_client.post("/api/generator/publish", json=_body())

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "techno--neon-rain" in detail
    # The message points at the way out, verbatim from the CLI.
    assert "--variant-of" in detail
    assert len(_read_catalog(tmp_catalog)) == 2


def test_publish_422_on_a_display_name_that_is_not_a_filename(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post("/api/generator/publish", json=_body(display_name="Bad/Name?"))

    assert r.status_code == 422
    assert "illegal characters" in r.json()["detail"]


# ══ Body validation ══════════════════════════════════════════════════


@pytest.mark.parametrize("missing", ["file", "metas", "display_name", "genre_folder"])
def test_publish_422_without_a_required_field(
    auth_client, ace_on, monkeypatch, missing
):
    calls = _install_ace(monkeypatch)
    body = _body()
    body.pop(missing)

    r = auth_client.post("/api/generator/publish", json=body)

    assert r.status_code == 422
    assert calls == []


def test_publish_422_on_an_unknown_body_field(auth_client, ace_on, monkeypatch):
    """``extra="forbid"`` — a silently ignored knob surfaces hours later."""
    calls = _install_ace(monkeypatch)

    r = auth_client.post("/api/generator/publish", json=_body(task_id="task-1"))

    assert r.status_code == 422
    assert "task_id" in r.text
    assert calls == []


@pytest.mark.parametrize("blank", ["", "   "])
def test_publish_422_on_a_blank_display_name(auth_client, ace_on, monkeypatch, blank):
    _install_ace(monkeypatch)
    r = auth_client.post("/api/generator/publish", json=_body(display_name=blank))
    assert r.status_code == 422


def test_publish_422_on_a_blank_keyscale(auth_client, ace_on, monkeypatch):
    _install_ace(monkeypatch)
    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={"bpm": 138, "keyscale": "", "duration": 181.4}),
    )
    assert r.status_code == 422


def test_publish_ignores_extra_metas_keys(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    """``metas`` is ACE's shape, not Apollo's — extras must not 422."""
    _install_ace(monkeypatch, audio=long_wav)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(metas={
            "bpm": 138, "keyscale": "A Minor", "duration": 181.4,
            "genres": "techno", "timesignature": "4",
        }),
    )

    assert r.status_code == 200, r.text


# ══ Transport refusals ═══════════════════════════════════════════════


def test_publish_503_when_the_generator_is_disabled(
    auth_client, ace_off, monkeypatch, tmp_catalog
):
    """No box, no audio — this refusal is structural, not a policy."""
    calls = _install_ace(monkeypatch)

    r = auth_client.post("/api/generator/publish", json=_body())

    assert r.status_code == 503
    assert ac.ENV_BASE_URL in r.json()["detail"]
    assert calls == []


def test_publish_503_when_the_box_is_unreachable(
    auth_client, ace_on, monkeypatch, tmp_catalog
):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        generator,
        "_client",
        lambda: ac.AceStepClient(transport=httpx.MockTransport(refuse)),
    )

    r = auth_client.post("/api/generator/publish", json=_body())

    assert r.status_code == 503


def test_publish_404_when_the_result_file_is_gone(
    auth_client, ace_on, monkeypatch, tmp_catalog
):
    _install_ace(monkeypatch, audio_status=404)
    r = auth_client.post("/api/generator/publish", json=_body())
    assert r.status_code == 404


def test_publish_502_when_ace_errors(auth_client, ace_on, monkeypatch, tmp_catalog):
    _install_ace(monkeypatch, audio_status=500)
    r = auth_client.post("/api/generator/publish", json=_body())
    assert r.status_code == 502


# ══ Path validation — the ONE shared function ════════════════════════


@pytest.mark.parametrize("shape", [
    ACE_FILE,                                          # the real shape
    f"{ACE_ROOT}/take with spaces_1.wav",              # spaces survive
    ACE_ENDPOINT_FILE,                                 # G1's endpoint shape
    "api_audio/x.wav",                                 # relative, ACE resolves it
])
def test_proxy_accepts_every_documented_shape(shape):
    resolved = generator.validate_ace_audio_path(shape)
    assert resolved.api_path


def test_publish_shape_is_the_absolute_path_under_the_root():
    resolved = generator.validate_ace_audio_path(ACE_FILE, resolve_file=True)
    assert resolved.shape == "absolute"
    assert resolved.file_path == ACE_FILE
    # Re-encoded into the endpoint form for stream_audio, slashes as %2F.
    assert resolved.api_path.startswith("/v1/audio?path=%2Fhome%2Fpablo")
    assert "/" not in resolved.api_path.split("path=", 1)[1]


def test_publish_unwraps_the_encoded_endpoint_shape():
    from urllib.parse import quote

    resolved = generator.validate_ace_audio_path(
        f"/v1/audio?path={quote(ACE_FILE, safe='')}", resolve_file=True
    )
    assert resolved.file_path == ACE_FILE


def test_publish_refuses_a_relative_path():
    """A relative path can't be root-checked, and publish writes to disk."""
    with pytest.raises(generator.AceAudioPathError) as exc:
        generator.validate_ace_audio_path("api_audio/x.wav", resolve_file=True)
    assert "decoded ACE-Step path" in str(exc.value)


def test_publish_refuses_an_absolute_path_outside_the_root():
    with pytest.raises(generator.AceAudioPathError) as exc:
        generator.validate_ace_audio_path("/tmp/out/take0.wav", resolve_file=True)
    assert generator.ENV_AUDIO_ROOT in str(exc.value)


def test_the_two_modes_agree_about_an_endpoint_path():
    """The asymmetry is GONE — one rule for one value, so pin that.

    ``/v1/audio?path=<encoded>`` still names an ACE ENDPOINT, and ACE's
    own validator is still the far-side authority on what it will serve.
    But Apollo will not FORWARD a location it would refuse to PUBLISH:
    the decoded inner path clears the root check on both routes or on
    neither, so the proxy can no longer be the soft way in.
    """
    in_root = ACE_ENDPOINT_FILE
    out_of_root = "/v1/audio?path=%2Ftmp%2Fout%2Ftake0.wav"

    # Under the root: both modes accept, and both resolve the same file.
    assert generator.validate_ace_audio_path(in_root).api_path == in_root
    assert generator.validate_ace_audio_path(in_root).file_path == ACE_FILE
    assert (
        generator.validate_ace_audio_path(in_root, resolve_file=True).file_path
        == ACE_FILE
    )

    # Outside it: both modes refuse, and both name the env override the
    # operator needs (only the HTTP status differs — 400 vs 422).
    for resolve_file in (False, True):
        with pytest.raises(generator.AceAudioPathError) as exc:
            generator.validate_ace_audio_path(out_of_root, resolve_file=resolve_file)
        assert generator.ENV_AUDIO_ROOT in str(exc.value)


@pytest.mark.parametrize("bad", [
    "http://evil.test/v1/audio?path=x",
    "https://ace.test:8001/v1/audio",
    "//evil.test/v1/audio",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "out\\take0.wav",
    "/v1/../secret",
    f"/v1/audio?path=%2Fhome%2Fpablo%2F..%2F..%2Fetc%2Fpasswd",
    "",
    "   ",
])
@pytest.mark.parametrize("resolve_file", [False, True])
def test_garbage_is_refused_in_both_modes(bad, resolve_file):
    with pytest.raises(generator.AceAudioPathError):
        generator.validate_ace_audio_path(bad, resolve_file=resolve_file)


def test_the_root_is_env_tunable(monkeypatch):
    """Flipping the accepted location is a constant, not a refactor."""
    monkeypatch.setenv(generator.ENV_AUDIO_ROOT, "/srv/ace/out")

    assert generator.ace_audio_roots() == ("/srv/ace/out",)
    resolved = generator.validate_ace_audio_path(
        "/srv/ace/out/take_0.wav", resolve_file=True
    )
    assert resolved.file_path == "/srv/ace/out/take_0.wav"
    with pytest.raises(generator.AceAudioPathError):
        generator.validate_ace_audio_path(ACE_FILE, resolve_file=True)


def test_several_roots_may_be_configured(monkeypatch):
    monkeypatch.setenv(generator.ENV_AUDIO_ROOT, f"/srv/a, {ACE_ROOT}/")
    assert generator.ace_audio_roots() == ("/srv/a", ACE_ROOT)
    assert generator.validate_ace_audio_path("/srv/a/x.wav", resolve_file=True)
    assert generator.validate_ace_audio_path(ACE_FILE, resolve_file=True)


def test_a_plus_in_a_filename_is_not_turned_into_a_space():
    """``quote(p, safe="")`` leaves ``+`` alone; ``parse_qs`` would not."""
    from urllib.parse import quote

    plus = f"{ACE_ROOT}/take+one_0.wav"
    resolved = generator.validate_ace_audio_path(
        f"/v1/audio?path={quote(plus, safe='')}", resolve_file=True
    )
    assert resolved.file_path == plus


def test_the_proxy_accepts_an_absolute_path_under_the_root(
    auth_client, ace_on, monkeypatch
):
    """The publish shape also streams, re-encoded into the endpoint form."""
    calls = _install_ace(monkeypatch, audio=b"RIFF....WAVE")

    r = auth_client.get("/api/generator/audio", params={"path": ACE_FILE})

    assert r.status_code == 200
    audio = [c for c in calls if c.url.path == "/v1/audio"]
    assert audio[0].url.params.get("path") == ACE_FILE


def test_the_proxy_still_400s_an_absolute_path_outside_the_root(
    auth_client, ace_on, monkeypatch
):
    calls = _install_ace(monkeypatch)
    r = auth_client.get("/api/generator/audio", params={"path": "/tmp/out/take0.wav"})
    assert r.status_code == 400
    assert calls == []


def test_publish_422_names_the_root_on_a_bad_file(
    auth_client, ace_on, monkeypatch, tmp_catalog
):
    calls = _install_ace(monkeypatch)

    r = auth_client.post("/api/generator/publish", json=_body(file="/tmp/x.wav"))

    assert r.status_code == 422
    assert ACE_ROOT in r.json()["detail"]
    assert calls == []


def test_publish_422_on_an_endpoint_path_out_of_root(
    auth_client, ace_on, monkeypatch, tmp_catalog
):
    """Wrapping the same out-of-root path in ACE's endpoint form is no
    way around the root check — the wire twin of the proxy's 400."""
    calls = _install_ace(monkeypatch)

    r = auth_client.post(
        "/api/generator/publish",
        json=_body(file="/v1/audio?path=%2Ftmp%2Fout%2Ftake0.wav"),
    )

    assert r.status_code == 422
    assert ACE_ROOT in r.json()["detail"]
    assert calls == []  # nothing downloaded, nothing written
