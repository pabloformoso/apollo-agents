"""
Deterministic fake pipeline phases for tests and Playwright E2E runs.

Shared by tests/web/conftest.py::mock_pipeline and by the live backend when
AGENT_PROVIDER=mock — no Anthropic/OpenAI calls, no librosa, no DALL-E.
"""
from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Callable


async def fake_genre(message: str, history: list[dict], ctx: dict, emit: Callable) -> dict | None:
    await emit({"type": "text_delta", "content": "genre-ok"})
    lowered = (message or "").lower()
    if "cyberpunk" in lowered:
        genre = "cyberpunk"
    elif "techno" in lowered:
        genre = "techno"
    elif "house" in lowered:
        genre = "deep house"
    elif "lofi" in lowered or "ambient" in lowered:
        genre = "lofi - ambient"
    else:
        # E2E's "bad genre" path: unresolved → None (maps to `error` event)
        if "garbage" in lowered or "xyzzy" in lowered:
            return None
        genre = "techno"
    # Sentinel for C2: "crash" in the prompt makes the planner blow up later.
    mood = "crash" if "crash" in lowered else "dark"
    return {"genre": genre, "duration_min": 60, "mood": mood}


async def fake_plan(ctx: dict, emit: Callable, memory_summary: str = "") -> str:
    if ctx.get("mood") == "crash":
        raise RuntimeError("simulated planner crash")
    ctx["playlist"] = [
        {"id": "t1", "display_name": "Track 1", "bpm": 128, "camelot_key": "9A", "genre": ctx.get("genre", "techno"), "duration_sec": 360},
        {"id": "t2", "display_name": "Track 2", "bpm": 130, "camelot_key": "10A", "genre": ctx.get("genre", "techno"), "duration_sec": 360},
    ]
    await emit({"type": "tool_call", "name": "propose_playlist", "input": {}})
    return "playlist proposed"


async def fake_critique(ctx: dict, emit: Callable, memory_summary: str = "") -> tuple[str, list[str], list[dict]]:
    await emit({"type": "text_delta", "content": "critic-ok"})
    return ("APPROVED", [], [])


async def fake_editor(message: str, history: list[dict], ctx: dict, emit: Callable) -> str:
    await emit({"type": "text_delta", "content": "editor-ok"})
    if message.startswith("build"):
        ctx["last_build"] = message.split(maxsplit=1)[1] if " " in message else "e2e-smoke"
    return "done"


async def fake_validate(session_name: str, ctx: dict, emit: Callable) -> tuple[str, list[str]]:
    await emit({"type": "text_delta", "content": "validator-ok"})
    return ("PASS", [])


async def fake_memory(genre: str, ctx: dict) -> str:
    return ""


def fake_write(**kwargs) -> str:
    return "saved"


def fake_check_catalog(genre: str | None = None) -> None:
    """No-op stand-in for `pipeline.check_catalog` — tests/E2E never need a
    real `tracks/tracks.json` since every phase is a deterministic fake."""
    return None


# ---------------------------------------------------------------------------
# Catalog/streaming fakes for v2.2 — emit a tiny synthetic catalog on demand
# so E2E runs (`AGENT_PROVIDER=mock`) can hit `/api/tracks/{id}/stream`
# against a real file on disk without dragging in the production tracks/ dir.
# ---------------------------------------------------------------------------

_MOCK_TRACKS_CACHE: list[dict] | None = None


def _ensure_mock_audio_file(pipeline_module) -> Path:
    """Materialise a 1 s silence WAV under <project_root>/tracks/lofi/ so the
    streaming endpoint can serve it. Idempotent."""
    project_root = Path(pipeline_module._PROJECT_DIR)
    target_dir = project_root / "tracks" / "lofi"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "mock-silence.wav"
    if target.exists() and target.stat().st_size > 0:
        return target
    # Tiny, real, decodable WAV — 1 second of silence at 8 kHz mono.
    sample_rate = 8000
    n_frames = sample_rate
    with wave.open(str(target), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return target


def _build_mock_catalog(pipeline_module) -> list[dict]:
    global _MOCK_TRACKS_CACHE
    if _MOCK_TRACKS_CACHE is not None:
        return _MOCK_TRACKS_CACHE
    audio_path = _ensure_mock_audio_file(pipeline_module)
    rel = (
        str(audio_path.relative_to(Path(pipeline_module._PROJECT_DIR)))
        .replace("\\", "/")
    )
    # E2E specs need at least three distinct tracks to exercise reorder /
    # multi-track playlists. They share the same file on disk — only the id
    # and display_name diverge so the UI can tell them apart.
    _MOCK_TRACKS_CACHE = [
        {
            "id": "mock-lofi-silence",
            "display_name": "Mock Silence",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "8A",
            "bpm": 90.0,
            "duration_sec": 1.0,
            "variant_of": None,
        },
        {
            "id": "mock-lofi-silence-2",
            "display_name": "Mock Silence Two",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "9A",
            "bpm": 92.0,
            "duration_sec": 1.0,
            "variant_of": None,
        },
        {
            "id": "mock-lofi-silence-3",
            "display_name": "Mock Silence Three",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "10A",
            "bpm": 94.0,
            "duration_sec": 1.0,
            "variant_of": None,
        },
    ]
    return _MOCK_TRACKS_CACHE


def install(pipeline_module) -> None:
    """Swap every phase_* on the live pipeline module with the fakes above."""
    pipeline_module.phase_genre_guard = fake_genre
    pipeline_module.phase_plan = fake_plan
    pipeline_module.phase_critique = fake_critique
    pipeline_module.phase_editor = fake_editor
    pipeline_module.phase_validate = fake_validate
    pipeline_module.load_memory = fake_memory
    pipeline_module.write_session_record = fake_write
    pipeline_module.check_catalog = fake_check_catalog

    def _fake_load_catalog(genre: str | None = None):
        tracks = _build_mock_catalog(pipeline_module)
        if genre:
            tracks = [t for t in tracks if t["genre_folder"].lower() == genre.lower()]
        return tracks, ["lofi"]

    pipeline_module.load_catalog = _fake_load_catalog
