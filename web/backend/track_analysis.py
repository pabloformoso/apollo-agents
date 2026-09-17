"""Bounded CPU subprocess; analyse one trusted catalog WAV, never the catalog."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def prepare(source: Path, bpm: float) -> dict:
    import main
    try:
        from madmom.features.downbeats import RNNDownBeatProcessor  # noqa: F401
    except Exception as exc:
        raise RuntimeError("madmom is unavailable. Install the backend beatgrid dependencies, then retry.") from exc
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is unavailable. Install it in the backend, then retry.")
    duration = main._wav_duration_sec(str(source))
    if not duration or bpm <= 0:
        raise RuntimeError("Audio duration or catalog BPM is invalid.")
    grid = main.detect_downbeats(str(source), bpm)
    if grid.get("source") != "madmom" or len(grid.get("downbeats_sec", [])) < 2:
        raise RuntimeError("madmom could not detect a reliable beatgrid. The track remains outside sessions.")
    peaks = main.compute_waveform_peaks(str(source))
    # Encode under a temporary name. A killed ffmpeg cannot leave a partial
    # sibling that the idempotent encoder mistakes for a complete MP3.
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=source.parent) as work:
        mp3 = main._ensure_mp3_for(str(source), output_path=str(Path(work) / "audio.stream.mp3"))
        if not mp3 or not Path(mp3).is_file():
            raise RuntimeError("MP3 encoding failed. Retry preparation.")
        target = source.with_suffix(".stream.mp3")
        os.replace(mp3, target)
    return {"duration_sec": round(duration, 1), "beatgrid": grid,
            "waveform_peaks": peaks, "mp3_file": os.path.relpath(target).replace(os.sep, "/")}


if __name__ == "__main__":
    try:
        payload = prepare(Path(sys.argv[1]), float(sys.argv[2]))
        code = 0
    except Exception as exc:
        payload = {"error": str(exc)[:300]}
        code = 1
    Path(sys.argv[3]).write_text(json.dumps(payload), encoding="utf-8")
    raise SystemExit(code)
