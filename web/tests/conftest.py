"""Shared fixtures for v2.2 stream tests.

Reuses the same TestClient/auth-token plumbing as tests/web/conftest.py but
keeps things in this file so `pytest web/tests` works as a standalone suite.
"""
from __future__ import annotations

import os
import struct
import sys
import wave
from pathlib import Path

# Deterministic JWT secret for all tests in this module
os.environ.setdefault("JWT_SECRET", "test-secret")

# Make the project root importable so "from web.backend..." works
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient


def _write_silence_wav(path: Path, duration_sec: float = 1.0, sample_rate: int = 8000) -> None:
    """Write a tiny mono 16-bit PCM WAV of silence."""
    n_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


def _write_silence_mp3(path: Path) -> None:
    """Write a minimal valid MP3 frame so FastAPI can serve it.

    We don't need a decodable file for the streaming tests — only a real
    file that lives at the right place with the right extension. We use
    pydub if available, falling back to a tiny placeholder byte sequence
    that at least passes mimetype detection.
    """
    try:
        from pydub import AudioSegment  # noqa: PLC0415

        silence = AudioSegment.silent(duration=200)  # 200 ms
        silence.export(str(path), format="mp3")
    except Exception:
        # Fallback: write a few bytes that look like an MP3 header so the
        # file isn't empty. The streaming endpoint only checks extension
        # and content; it does not decode the file.
        path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)


@pytest.fixture
def stream_env(tmp_path, monkeypatch):
    """Set up a fake tracks/ root with a WAV and an MP3, and patch pipeline
    so `load_catalog` and the path resolver use this temp tree.

    Returns: dict with keys `tmp_root`, `wav_track`, `mp3_track`,
    `wav_size`, `mp3_size`.
    """
    from web.backend import db, pipeline

    # Re-init DB at a clean tmp file
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()

    tracks_root = tmp_path / "tracks"
    genre_dir = tracks_root / "lofi"
    genre_dir.mkdir(parents=True)

    wav_path = genre_dir / "silence.wav"
    mp3_path = genre_dir / "silence.mp3"
    _write_silence_wav(wav_path, duration_sec=1.0)
    _write_silence_mp3(mp3_path)

    wav_track = {
        "id": "lofi--silence",
        "display_name": "Silence",
        "file": str(wav_path.relative_to(tmp_path)).replace("\\", "/"),
        "genre_folder": "lofi",
        "genre": "lofi",
        "camelot_key": "8A",
        "bpm": 90,
        "duration_sec": 1.0,
    }
    mp3_track = {
        "id": "lofi--silence-mp3",
        "display_name": "Silence MP3",
        "file": str(mp3_path.relative_to(tmp_path)).replace("\\", "/"),
        "genre_folder": "lofi",
        "genre": "lofi",
        "camelot_key": "8A",
        "bpm": 90,
        "duration_sec": 1.0,
    }

    monkeypatch.setattr(pipeline, "_PROJECT_DIR", tmp_path)

    def fake_load_catalog(genre=None):
        tracks = [wav_track, mp3_track]
        if genre:
            tracks = [t for t in tracks if t["genre_folder"].lower() == genre.lower()]
        return tracks, ["lofi"]

    def fake_check_catalog(genre=None):
        return None

    monkeypatch.setattr(pipeline, "load_catalog", fake_load_catalog)
    monkeypatch.setattr(pipeline, "check_catalog", fake_check_catalog)

    return {
        "tmp_root": tmp_path,
        "wav_track": wav_track,
        "mp3_track": mp3_track,
        "wav_path": wav_path,
        "mp3_path": mp3_path,
        "wav_size": wav_path.stat().st_size,
        "mp3_size": mp3_path.stat().st_size,
    }


@pytest.fixture
def auth_client(stream_env):
    """TestClient with a registered user. Depends on `stream_env` so the
    DB monkeypatch and tmp tracks tree are both active."""
    from web.backend.app import app
    from web.backend.session_store import store

    store._reset()
    client = TestClient(app)
    client.post(
        "/api/auth/register",
        json={"username": "u1", "email": "u1@test.io", "password": "pw12345"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "u1", "password": "pw12345"},
    )
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    client.auth_token = token  # type: ignore[attr-defined]
    return client


@pytest.fixture
def auth_token(auth_client):
    return auth_client.auth_token  # type: ignore[attr-defined]
