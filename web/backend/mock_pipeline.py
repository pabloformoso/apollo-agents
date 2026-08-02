"""
Deterministic fake pipeline phases for tests and Playwright E2E runs.

Shared by tests/web/conftest.py::mock_pipeline and by the live backend when
AGENT_PROVIDER=mock — no Anthropic/OpenAI calls, no librosa, no DALL-E.
"""
from __future__ import annotations

import asyncio
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
    # v2.5.0 — environment-perception. The frontend appends a
    # "(environment: <text>)" suffix to the user's message when the
    # decorative environment textarea is non-empty. We round-trip whatever
    # appears between the parens so E2E specs can assert the value flows
    # end-to-end. Anything else falls back to "unspecified".
    environment = "unspecified"
    if "(environment:" in lowered:
        try:
            start = lowered.index("(environment:") + len("(environment:")
            end = lowered.index(")", start)
            environment = (message or "")[start:end].strip() or "unspecified"
        except ValueError:
            environment = "unspecified"
    return {
        "genre": genre,
        "duration_min": 60,
        "mood": mood,
        "environment": environment,
    }


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


async def fake_phase_live(
    playlist: list[dict],
    ctx: dict,
    engine,
    emit: Callable,
    command_queue,
) -> None:
    """Deterministic fake live-phase: emits a tiny scripted event timeline
    so E2E specs can wait on real engine events without touching the LLM
    or the LiveDJ loop. The browser still drives audio (HTML5 ``<audio>``)
    via the engine commands the engine itself emits.

    The script is intentionally short and instant:

      1. ``engine.play(playlist)`` → the engine emits ``track_started`` for
         playlist[0] and the ``engine_command`` ``load`` for the browser.
      2. After a short delay, emit a synthetic ``approaching_crossfade``
         event so the UI can show its countdown widget.
      3. Drain the command queue and ack any user_msg / quit so the
         frontend smoke test can verify command routing without an LLM.

    The fake engine and live_dj are skipped entirely — the spec only needs
    a couple of events plus an honest ack of skip/quit commands."""
    engine.play(playlist)
    await asyncio.sleep(0.01)

    if len(playlist) > 1:
        # Surface an APPROACHING_CF event without going through the
        # real timing machinery so the UI shows its countdown.
        try:
            engine._emitter(  # type: ignore[attr-defined]
                {
                    "type": "approaching_crossfade",
                    "track": playlist[0],
                    "next_track": playlist[1],
                    "seconds_remaining": 10.0,
                }
            )
        except Exception:
            pass

    perception_count = 0
    while True:
        try:
            item = await asyncio.wait_for(command_queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        item_type = item.get("type")
        if item_type == "quit":
            await emit({"type": "live_message", "role": "assistant", "content": "Stopping."})
            break
        if item_type == "perception_sample":
            # v2.5.2 — accept the metric, surface a synthetic dj_chat
            # acknowledgement on the very first sample so E2E specs can
            # observe end-to-end mic → backend → UI flow without an LLM.
            perception_count += 1
            ctx.setdefault("perception_buffer", []).append(item)
            if perception_count == 1:
                await emit(
                    {
                        "type": "dj_chat",
                        "text": "Reading the room.",
                    }
                )
            continue
        if item_type == "user_msg":
            text = (item.get("text") or "").strip().lower()
            if text in {"skip", "next"}:
                engine.skip_track()
                await emit(
                    {
                        "type": "live_message",
                        "role": "assistant",
                        "content": "Skipping.",
                    }
                )
            elif text in {"stay", "longer", "more"}:
                engine.extend_track(20)
                await emit(
                    {
                        "type": "live_message",
                        "role": "assistant",
                        "content": "Extended 20s.",
                    }
                )
            else:
                # v2.5.2 — audience requests get a polite dj_chat reply
                # ("noted, but staying course") so the E2E spec for the
                # audience-request flow has a deterministic event to wait
                # on. Real path goes through emit_chat tool calls.
                await emit(
                    {
                        "type": "dj_chat",
                        "text": f"Heard: {item.get('text','')}. Staying the course.",
                    }
                )
                await emit(
                    {
                        "type": "live_message",
                        "role": "assistant",
                        "content": f"Got it: {text}",
                    }
                )
        elif item_type == "session_ended":
            break


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
    """Materialise a 1 s silence WAV under <project_root>/.tmp/ so the
    streaming endpoint can serve it without polluting tracks/ (issue #13).

    `.tmp/` is gitignored at the repo root and is NOT scanned by
    `--build-catalog`, so dropping the file here keeps developer checkouts
    clean even if `AGENT_PROVIDER=mock` is invoked locally. The streaming
    endpoint's path-traversal guard treats `.tmp/` as an additional allowed
    root specifically for this fixture. Idempotent."""
    project_root = Path(pipeline_module._PROJECT_DIR)
    target_dir = project_root / ".tmp"
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
    # Multiple entries (all sharing the same on-disk silence file) so E2E
    # specs that need >1 catalog item — favorites filter, reorder, multi-track
    # playlists, etc. — have something to work with. The first track ("Mock
    # Silence") is referenced by name in the v2.2.0 player spec; the rest are
    # extras introduced for v2.2.1 (playlists) and v2.2.2 (ratings).
    _MOCK_TRACKS_CACHE = [
        # v3.6.2 — ``fake_plan`` seeds session playlists with t1/t2, and
        # the live WS handler now validates playlists against
        # ``load_catalog`` before starting the engine. These two entries
        # keep that filter satisfied in mock/E2E runs. Deliberately NO
        # ``file`` key: ``/api/tracks/{id}/stream`` keeps 404ing for
        # them, so E2E decks stay inert exactly as before the filter —
        # the whole live E2E suite drives the UI without real audio.
        {
            "id": "t1",
            "display_name": "Track 1",
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "9A",
            "bpm": 128.0,
            "duration_sec": 360.0,
            "variant_of": None,
        },
        {
            "id": "t2",
            "display_name": "Track 2",
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "10A",
            "bpm": 130.0,
            "duration_sec": 360.0,
            "variant_of": None,
        },
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
        {
            "id": "mock-lofi-alpha",
            "display_name": "Mock Alpha",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "9A",
            "bpm": 95.0,
            "duration_sec": 1.0,
            "variant_of": None,
        },
        {
            "id": "mock-lofi-bravo",
            "display_name": "Mock Bravo",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "10A",
            "bpm": 100.0,
            "duration_sec": 1.0,
            "variant_of": None,
        },
        {
            "id": "mock-lofi-charlie",
            "display_name": "Mock Charlie",
            "file": rel,
            "genre_folder": "lofi",
            "genre": "lofi",
            "camelot_key": "11A",
            "bpm": 105.0,
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
    pipeline_module.phase_live = fake_phase_live
    pipeline_module.load_memory = fake_memory
    pipeline_module.write_session_record = fake_write
    pipeline_module.check_catalog = fake_check_catalog

    def _fake_load_catalog(genre: str | None = None):
        tracks = _build_mock_catalog(pipeline_module)
        if genre:
            tracks = [t for t in tracks if t["genre_folder"].lower() == genre.lower()]
        return tracks, ["lofi"]

    pipeline_module.load_catalog = _fake_load_catalog

    def _fake_get_track_by_id(track_id: str) -> dict | None:
        return next(
            (t for t in _build_mock_catalog(pipeline_module) if t["id"] == track_id),
            None,
        )

    pipeline_module.get_track_by_id = _fake_get_track_by_id
