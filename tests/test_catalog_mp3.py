"""Tests for MP3 support in the catalog scanner (`main.scan_genre_folders`,
`main.build_catalog`) and in `web.backend.pipeline.load_catalog`."""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

import main


def _write_silence_wav(path: Path, sample_rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * sample_rate)  # 1 s


def _write_silence_mp3(path: Path) -> None:
    """Use pydub if available; otherwise emit a tiny placeholder so the
    scanner picks it up by extension. The catalog scanner doesn't care about
    decode-ability — librosa is mocked in these tests."""
    try:
        from pydub import AudioSegment  # noqa: PLC0415

        AudioSegment.silent(duration=200).export(str(path), format="mp3")
    except Exception:
        path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)


def test_scan_genre_folders_picks_up_mp3(tmp_path, monkeypatch):
    tracks_dir = tmp_path / "tracks"
    genre_dir = tracks_dir / "lofi"
    genre_dir.mkdir(parents=True)
    wav = genre_dir / "a.wav"
    mp3 = genre_dir / "b.mp3"
    _write_silence_wav(wav)
    _write_silence_mp3(mp3)

    monkeypatch.setattr(main, "TRACKS_BASE_DIR", str(tracks_dir))
    found = main.scan_genre_folders()
    rels = sorted(os.path.basename(p) for _, p in found)
    assert rels == ["a.wav", "b.mp3"]


def test_audio_duration_sec_handles_mp3(tmp_path):
    mp3 = tmp_path / "x.mp3"
    _write_silence_mp3(mp3)
    # Just verify the helper does not crash for MP3 — duration may be 0.0
    # if pydub isn't available, that's fine.
    dur = main._wav_duration_sec(str(mp3))
    assert isinstance(dur, float)
    assert dur >= 0.0
    # The new alias should resolve to the same function.
    assert main._audio_duration_sec is main._wav_duration_sec


def test_build_catalog_picks_up_mp3(tmp_path, monkeypatch):
    """`build_catalog` should write an MP3 entry to tracks.json with the
    real `.mp3` extension and BPM/duration populated."""
    tracks_dir = tmp_path / "tracks"
    genre_dir = tracks_dir / "lofi"
    genre_dir.mkdir(parents=True)
    mp3 = genre_dir / "tune.mp3"
    _write_silence_mp3(mp3)

    catalog_path = tracks_dir / "tracks.json"
    monkeypatch.setattr(main, "TRACKS_BASE_DIR", str(tracks_dir))
    monkeypatch.setattr(main, "CATALOG_PATH", str(catalog_path))

    # Mock the heavy analysers so we don't need real decoding.
    monkeypatch.setattr(main, "detect_bpm", lambda path, genre: 90.0)
    monkeypatch.setattr(
        main, "detect_beatgrid", lambda path, bpm: {"bpm": 90.0, "first_beat_sec": 0.0}
    )
    monkeypatch.setattr(main, "detect_camelot_key", lambda path: "8A")
    monkeypatch.setattr(main, "_wav_duration_sec", lambda path: 1.0)

    # Run from inside tmp_path so relpath() returns clean tracks/lofi/tune.mp3
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main.build_catalog()
    finally:
        os.chdir(cwd)

    assert catalog_path.exists()
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    files = [e["file"] for e in data["tracks"]]
    assert any(f.endswith("tune.mp3") for f in files), files
    mp3_entry = next(e for e in data["tracks"] if e["file"].endswith("tune.mp3"))
    assert mp3_entry["bpm"] == 90.0
    assert mp3_entry["duration_sec"] == 1.0
    assert mp3_entry["camelot_key"] == "8A"
    assert mp3_entry["genre_folder"] == "lofi"


def test_load_catalog_returns_mp3_track(tmp_path, monkeypatch):
    """`web.backend.pipeline.load_catalog` returns MP3 entries unchanged."""
    from web.backend import pipeline

    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    catalog = {
        "tracks": [
            {
                "id": "lofi--tune",
                "display_name": "Tune",
                "file": "tracks/lofi/tune.mp3",
                "genre_folder": "lofi",
                "genre": "lofi",
                "camelot_key": "8A",
                "bpm": 90.0,
                "duration_sec": 1.0,
            },
        ],
    }
    (tracks_dir / "tracks.json").write_text(json.dumps(catalog), encoding="utf-8")

    monkeypatch.setattr(pipeline, "_PROJECT_DIR", tmp_path)
    tracks, genres = pipeline.load_catalog()
    assert genres == ["lofi"]
    assert len(tracks) == 1
    assert tracks[0]["file"].endswith(".mp3")
    assert tracks[0]["id"] == "lofi--tune"
