"""Apollo's own copy of every finished take (``web/backend/take_store.py``).

Prod, 2026-11-23: ten finished "Chapter" takes could not be played,
because the audio proxy only knew how to ask ACE for them and ACE was
stopped — as the VRAM protocol keeps it most of the time. The same
dependency made critique a 503 with ACE stopped and an LLM hazard with
it running. These tests pin the fix: the done-poll copies each take into
the store, and every reader (proxy, publish, critique, the edit's upload
fallback) is served from that copy with ACE unreachable.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys

import httpx
import pytest
from fastapi import HTTPException

from web.backend import acestep_client as ac
from web.backend import generator, take_store

from .test_generator_library import (  # noqa: F401 — fixtures are used by name
    TAKE_0_FILE,
    TAKE_1_FILE,
    _box,
    _endpoint,
    _feed,
    _install_ace,
    _poll,
    _publish_body,
    _release,
    ace_on,
    clean_live_registry,
    long_wav,
    no_catalog_reads,
    tmp_catalog,
)

AUDIO = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x01" * 64


def _ace_down(monkeypatch) -> list[httpx.Request]:
    """ACE configured but not answering — the box is stopped."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(generator, "_client", lambda: ac.AceStepClient(transport=transport))
    return calls


def _audio_calls(calls) -> list[httpx.Request]:
    return [c for c in calls if c.url.path == "/v1/audio"]


# ══ The store itself ═════════════════════════════════════════════════


def test_the_store_is_keyed_by_ace_basename():
    assert take_store.name_for(TAKE_0_FILE) == TAKE_0_FILE.rsplit("/", 1)[1]
    assert take_store.stored_path(TAKE_0_FILE).parent == take_store.takes_dir()


@pytest.mark.parametrize(
    "bad", [None, "", "/x/", "/x/.hidden.wav", "/x/take.txt", "/x/a b.wav", "/x/..wav"]
)
def test_names_that_cannot_be_a_take_get_no_copy(bad):
    assert take_store.name_for(bad) is None
    assert take_store.local_copy(bad) is None


def test_the_store_location_follows_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLLO_TAKES_DIR", str(tmp_path / "elsewhere"))
    assert take_store.takes_dir() == tmp_path / "elsewhere"


# ══ The done-poll copies ═════════════════════════════════════════════


def test_the_done_poll_copies_every_take(auth_client, ace_on, monkeypatch):
    _release(auth_client, monkeypatch)
    from .test_generator_library import _entry

    calls = _install_ace(monkeypatch, _box(results=[_entry()], audio=AUDIO))
    assert auth_client.get("/api/generator/tasks/task-1").status_code == 200

    assert take_store.local_copy(TAKE_0_FILE).read_bytes() == AUDIO
    assert take_store.local_copy(TAKE_1_FILE).read_bytes() == AUDIO
    assert len(_audio_calls(calls)) == 2
    assert not list(take_store.takes_dir().glob("*.part"))

    # A re-poll finds the copies and fetches nothing.
    assert auth_client.get("/api/generator/tasks/task-1").status_code == 200
    assert len(_audio_calls(calls)) == 2


def test_an_empty_answer_is_never_stored(auth_client, ace_on, monkeypatch):
    _release(auth_client, monkeypatch)
    _poll(auth_client, monkeypatch)  # the box answers b"" for the audio

    assert take_store.local_copy(TAKE_0_FILE) is None
    assert not list(take_store.takes_dir().glob("*"))


def test_a_failed_copy_never_breaks_the_poll(auth_client, ace_on, monkeypatch):
    _release(auth_client, monkeypatch)
    from .test_generator_library import _entry

    _install_ace(monkeypatch, _box(results=[_entry()], audio_status=404))
    r = auth_client.get("/api/generator/tasks/task-1")

    assert r.status_code == 200 and r.json()["status"] == "done"
    assert take_store.local_copy(TAKE_0_FILE) is None
    # The library row still turned done: history never depends on audio.
    assert _feed(auth_client)[0]["status"] == "done"


# ══ Readers are served from the copy, ACE down ═══════════════════════


def _stored(path: str, data: bytes = AUDIO):
    dest = take_store.stored_path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def test_the_proxy_serves_the_copy_with_ace_stopped(auth_client, ace_on, monkeypatch):
    _stored(TAKE_0_FILE)
    calls = _ace_down(monkeypatch)

    r = auth_client.get("/api/generator/audio", params={"path": _endpoint(TAKE_0_FILE)})

    assert r.status_code == 200
    assert r.content == AUDIO
    assert r.headers["content-type"] == "audio/wav"
    assert calls == []


def test_the_proxy_copy_supports_range(auth_client, ace_on, monkeypatch):
    _stored(TAKE_0_FILE)
    _ace_down(monkeypatch)

    r = auth_client.get(
        "/api/generator/audio",
        params={"path": _endpoint(TAKE_0_FILE)},
        headers={"Range": "bytes=4-7"},
    )

    assert r.status_code == 206
    assert r.content == AUDIO[4:8]


def test_the_proxy_still_root_checks_before_reading_the_store(auth_client, ace_on, monkeypatch):
    """A file named like a stored take, outside ACE's root, is still a 400."""
    _stored(TAKE_0_FILE)
    _ace_down(monkeypatch)
    foreign = "/etc/" + take_store.name_for(TAKE_0_FILE)

    r = auth_client.get("/api/generator/audio", params={"path": _endpoint(foreign)})

    assert r.status_code == 400


def test_the_proxy_without_a_copy_still_asks_ace(auth_client, ace_on, monkeypatch):
    _ace_down(monkeypatch)
    r = auth_client.get("/api/generator/audio", params={"path": _endpoint(TAKE_0_FILE)})
    assert r.status_code == 503


def test_publish_works_with_ace_stopped(
    auth_client, ace_on, monkeypatch, tmp_catalog, long_wav
):
    _release(auth_client, monkeypatch)
    _poll(auth_client, monkeypatch)
    _stored(TAKE_1_FILE, long_wav)
    calls = _ace_down(monkeypatch)

    r = auth_client.post("/api/generator/publish", json=_publish_body())

    assert r.status_code == 200, r.text
    assert _audio_calls(calls) == []
    assert _feed(auth_client)[0]["takes"][1]["state"] == "published"


def test_publish_with_ace_off_and_no_copy_is_still_503(auth_client, monkeypatch, tmp_catalog):
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    r = auth_client.post("/api/generator/publish", json=_publish_body())
    assert r.status_code == 503


def test_download_take_prefers_the_copy(monkeypatch, tmp_path):
    """The one helper behind publish, critique and the edit's upload."""
    _stored(TAKE_0_FILE)
    calls = _ace_down(monkeypatch)
    dest = tmp_path / "out.wav"

    asyncio.run(generator._download_take(generator._client(), _endpoint(TAKE_0_FILE), str(dest)))

    assert dest.read_bytes() == AUDIO
    assert calls == []


def test_download_take_without_copy_and_without_ace_is_503(monkeypatch, tmp_path):
    monkeypatch.delenv(ac.ENV_BASE_URL, raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            generator._download_take(
                generator._client(), _endpoint(TAKE_0_FILE), str(tmp_path / "x.wav")
            )
        )
    assert exc.value.status_code == 503


# ══ The backfill ═════════════════════════════════════════════════════


def test_backfill_copies_recorded_takes_once(tmp_path, monkeypatch, capsys):
    from scripts import backfill_take_store as backfill

    src = tmp_path / "ace" / "api_audio"
    src.mkdir(parents=True)
    present = src / "aaaa-1111.wav"
    present.write_bytes(AUDIO)
    gone = src / "bbbb-2222.wav"
    db_path = tmp_path / "apollo.db"
    with sqlite3.connect(db_path) as c:
        c.execute("CREATE TABLE generation_takes (decoded_path TEXT)")
        c.executemany(
            "INSERT INTO generation_takes VALUES (?)",
            [(str(present),), (str(present),), (str(gone),), (None,), ("api_audio/rel.txt",)],
        )

    monkeypatch.setattr(sys, "argv", ["backfill", "--db", str(db_path), "--dry-run"])
    assert backfill.main() == 1  # one take is missing on ACE's disk
    assert take_store.local_copy(str(present)) is None

    monkeypatch.setattr(sys, "argv", ["backfill", "--db", str(db_path)])
    assert backfill.main() == 1
    assert take_store.local_copy(str(present)).read_bytes() == AUDIO

    capsys.readouterr()
    backfill.main()
    out = capsys.readouterr().out
    assert "copied 0" in out and "already stored 1" in out and "missing 1" in out
