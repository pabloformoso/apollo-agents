import sys
import types
from pathlib import Path

import pytest

from web.backend import track_analysis


@pytest.fixture
def audio(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    source.write_bytes(b"wav")
    def encode(path, *, output_path):
        assert path == str(source)
        Path(output_path).write_bytes(b"complete mp3")
        return output_path
    main = types.SimpleNamespace(
        _wav_duration_sec=lambda p: 180,
        detect_downbeats=lambda p, bpm: {"source": "madmom", "downbeats_sec": [0, 2]},
        compute_waveform_peaks=lambda p: [0, 1],
        _ensure_mp3_for=encode,
    )
    monkeypatch.setitem(sys.modules, "main", main)
    monkeypatch.setitem(sys.modules, "madmom.features.downbeats", types.SimpleNamespace(RNNDownBeatProcessor=object))
    monkeypatch.setattr(track_analysis.shutil, "which", lambda name: "/bin/ffmpeg")
    return source, main


def test_preparation_fills_all_fields_atomically(audio):
    source, _ = audio
    result = track_analysis.prepare(source, 120)
    assert result["duration_sec"] == 180
    assert result["waveform_peaks"] == [0, 1]
    assert result["beatgrid"]["source"] == "madmom"
    assert Path(result["mp3_file"]).read_bytes() == b"complete mp3"
    assert source.read_bytes() == b"wav"
    assert not list(source.parent.glob(".prepare-*"))


@pytest.mark.parametrize("case", ["madmom", "ffmpeg", "duration", "bpm", "grid", "mp3"])
def test_preparation_refuses_incomplete_analysis(audio, monkeypatch, case):
    source, main = audio
    if case == "madmom":
        monkeypatch.setitem(sys.modules, "madmom.features.downbeats", None)
    elif case == "ffmpeg":
        monkeypatch.setattr(track_analysis.shutil, "which", lambda name: None)
    elif case == "duration":
        main._wav_duration_sec = lambda p: None
    elif case == "grid":
        main.detect_downbeats = lambda p, bpm: {"source": "librosa"}
    elif case == "mp3":
        main._ensure_mp3_for = lambda *args, **kwargs: None
    with pytest.raises(RuntimeError):
        track_analysis.prepare(source, 0 if case == "bpm" else 120)
    assert not source.with_suffix(".stream.mp3").exists()
