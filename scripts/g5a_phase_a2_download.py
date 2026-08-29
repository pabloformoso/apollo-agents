"""G5a phase A2: download the persisted takes WHILE the ACE server is still up.

Runbook fix (2026-08-29): /v1/audio dies with the server, so the download
belongs at the tail of phase A — before the phase-B stop signal. Fallback
if the server is already down: scp the decoded paths from tunel over SSH.

    uv run python scripts/g5a_phase_a2_download.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import os  # noqa: E402
os.environ.setdefault("ACESTEP_BASE_URL", "http://100.68.5.104:8001")

from web.backend import acestep_client  # noqa: E402

OUT = REPO / "output" / "g5a"


async def main() -> int:
    takes = json.loads((OUT / "takes.json").read_text(encoding="utf-8"))["takes"]
    client = acestep_client.AceStepClient()
    for take in takes:
        dest = OUT / f"take_{take['index']}.wav"
        async with client.stream_audio(take["file_field"]) as resp:
            with open(dest, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
        size = dest.stat().st_size
        print(f"take {take['index']}: {size} bytes -> {dest}")
        if size < 1_000_000:
            print(f"  WARNING: suspiciously small for a 180s WAV")
    print("DOWNLOADED — safe to signal phase B")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
