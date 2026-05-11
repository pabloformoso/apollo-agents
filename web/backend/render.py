"""Apollo v2.6.0 — async render endpoint + downloads.

POST /api/sessions/{id}/render kicks off the build subprocess and
returns ``{ jobId, streamUrl }``. GET /api/sessions/{id}/render/stream
is the SSE endpoint the frontend's `<EventSource>` subscribes to;
``?token=`` carries the JWT because EventSource can't set headers.

Subprocess is spawned via ``asyncio.create_subprocess_exec`` and its
stdout is parsed through ``agent.tools._parse_build_progress_line``.
Stages are mapped to v2.6 user-facing names (``stems · crossfades ·
master · cover · encode``) and a stage-weighted ``pct`` is computed on
the fly with a rolling ETA. A ``_jobs`` registry holds the latest frame
+ a per-session queue so reconnecting tabs replay the last state
instead of seeing a blank stream.

Downloads (``/api/sessions/{id}/download/{kind}``) are FileResponses
over the project's ``output/<session_name>/`` directory, gated by the
same query-string token pattern as ``stream_track``.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from . import auth
from .session_store import store


# ── Stage mapping (v2.5 → v2.6) ──────────────────────────────────────
# ``mixing`` is split between ``stems`` (i ≤ 2) and ``crossfades`` (i ≥ 3)
# inside `_v26_stage` since the v2.5 stdout doesn't expose that nuance.
STAGE_MAP = {
    "loading_session": "stems",
    "mix_done": "crossfades",
    "export_audio": "master",
    "artwork": "cover",
    "artwork_track": "cover",
    "artwork_load": "cover",
    "video_loops": "encode",
    "waveform": "encode",
    "render_video": "encode",
    "validate": "encode",
}

# ── Downloadable assets the build pipeline produces ─────────────────
DOWNLOAD_KINDS: dict[str, tuple[str, str]] = {
    "wav": ("mix_output.wav", "audio/wav"),
    "mp4": ("mix_video.mp4", "video/mp4"),
    "short": ("short.mp4", "video/mp4"),
    "transitions": ("transitions.json", "application/json"),
    "youtube_md": ("youtube.md", "text/markdown"),
    "session_json": ("session.json", "application/json"),
}


class _Job:
    """In-memory record for an active render. Keyed by session_id.

    Frames are pushed into ``queue`` by the subprocess-driver task and
    drained by the SSE generator. ``last_frame`` is replayed when a new
    subscriber connects mid-render so the page doesn't blink to 0%.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.last_frame: dict = {
            "stage": None, "pct": 0.0, "etaSeconds": None, "message": "",
        }
        self.started_at: float = time.time()
        self.finished: bool = False
        self.assets: dict[str, str] | None = None
        self.chapters: list[dict] | None = None
        self.error: str | None = None


# session_id → _Job. Cleared after a grace window post-finish (so a
# late reload still sees the final frame).
_jobs: dict[str, _Job] = {}


# ── Helpers ──────────────────────────────────────────────────────────


def _project_root() -> Path:
    from agent.tools import _PROJECT_DIR  # noqa: PLC0415
    return Path(_PROJECT_DIR)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _v26_stage(event: dict) -> str:
    """Map a v2.5 progress event to its v2.6 user-facing stage name."""
    s = event.get("stage") or ""
    if s == "mixing":
        # Message format: "Mixing track {i}/{n}: {title}" — parse the i.
        try:
            head = (event.get("message") or "").split(":")[0]
            i = int(head.split(" ")[-1].split("/")[0])
            return "stems" if i <= 2 else "crossfades"
        except (ValueError, IndexError):
            return "stems"
    return STAGE_MAP.get(s, "stems")


def _compute_pct(event: dict, last: float) -> float:
    """Derive a stage-weighted pct from a v2.5 progress event.

    Stages get fixed budgets that sum to 100. Mixing splits its budget
    proportionally across the (i/N) tracks so the bar moves linearly
    instead of plateauing.
    """
    stage = event.get("stage") or ""
    msg = event.get("message") or ""
    if stage == "loading_session":
        return 2.0
    if stage == "mixing":
        try:
            head = msg.split(":")[0]
            i, n = head.split(" ")[-1].split("/")
            i, n = int(i), int(n)
            # Tracks 1–2 → 5..30, tracks 3..N → 30..55.
            if i <= 2:
                return min(30.0, 5 + (i / 2) * 25)
            return min(55.0, 30 + ((i - 2) / max(1, n - 2)) * 25)
        except (ValueError, IndexError):
            return max(last, 5.0)
    if stage == "mix_done":
        return 55.0
    if stage == "export_audio":
        return 63.0
    if stage == "artwork":
        return 65.0
    if stage == "artwork_track":
        return min(85.0, last + 4)
    if stage == "artwork_load":
        return 88.0
    if stage == "video_loops":
        return 90.0
    if stage == "waveform":
        return 92.0
    if stage == "render_video":
        return 95.0
    if stage == "validate":
        return 98.0
    return last


def _eta(started_at: float, pct: float) -> float | None:
    """Rolling-ETA via simple elapsed-over-progress proportion."""
    if pct < 5:
        return None
    elapsed = time.time() - started_at
    remaining = elapsed * (100 - pct) / pct
    return max(5.0, min(1800.0, remaining))


def _collect_chapters(out_dir: Path) -> list[dict]:
    """Read ``transitions.json`` and turn it into YouTube-style chapters."""
    trans_path = out_dir / "transitions.json"
    if not trans_path.exists():
        return []
    try:
        with trans_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    entries = data if isinstance(data, list) else data.get("transitions") or []
    chapters: list[dict] = []
    cur_sec = 0.0
    for ix, entry in enumerate(entries):
        chapters.append({
            "tMs": int(cur_sec * 1000),
            "title": entry.get("display_name") or entry.get("title") or f"Track {ix + 1}",
            "camelot": entry.get("camelot_key"),
        })
        # 6.8 min default if the entry doesn't carry a duration.
        cur_sec += float(entry.get("duration_sec") or 408)
    return chapters


def _available_assets(session_name: str, base_url_root: str) -> dict[str, str]:
    out_dir = _project_root() / "output" / session_name
    return {
        kind: f"{base_url_root}/{kind}"
        for kind, (filename, _) in DOWNLOAD_KINDS.items()
        if (out_dir / filename).exists()
    }


def _delete_job_later(session_id: str, delay: float = 60.0) -> None:
    """Drop the job entry from ``_jobs`` after ``delay`` seconds so late
    reloads still see the final frame, but the registry doesn't grow
    unbounded across many renders."""

    async def _later() -> None:
        await asyncio.sleep(delay)
        _jobs.pop(session_id, None)

    asyncio.create_task(_later())


# ── Router ───────────────────────────────────────────────────────────

router = APIRouter()


@router.post("/api/sessions/{session_id}/render")
async def start_render(
    session_id: str,
    current_user: dict = Depends(auth.get_current_user),
):
    s = store.get(session_id)
    if not s or s.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")

    # Concurrency guard: a second POST while a job is in flight returns
    # the existing stream URL with status="already_running" rather than
    # spawning a duplicate subprocess.
    existing = _jobs.get(session_id)
    if existing and not existing.finished:
        return {
            "jobId": session_id,
            "streamUrl": f"/api/sessions/{session_id}/render/stream",
            "status": "already_running",
        }

    if not s.context_variables.get("playlist"):
        raise HTTPException(status_code=422, detail="No playlist to render")

    from agent.tools import (  # noqa: PLC0415 — local import so tests can
        _write_draft_session,    # monkeypatch the subprocess seam.
        _parse_build_progress_line,
        _MAIN_PY,
        _slugify,
    )

    session_name = _slugify(
        s.session_name
        or s.context_variables.get("last_build")
        or s.context_variables.get("genre")
        or f"session-{s.id[:8]}"
    )
    genre = s.context_variables.get("genre") or "untitled"

    job = _Job(session_id)
    _jobs[session_id] = job

    s.phase = "rendering"
    store.save(s)

    draft_path = await asyncio.to_thread(
        _write_draft_session, session_name, s.context_variables,
    )

    async def _drive() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(_MAIN_PY),
                "--from-session", str(draft_path),
                "--name", session_name,
                "--genre", genre,
                cwd=str(_project_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None

            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                event = _parse_build_progress_line(line)
                if not event:
                    continue
                pct = _compute_pct(event, job.last_frame.get("pct", 0.0))
                frame = {
                    "stage": _v26_stage(event),
                    "pct": round(pct, 1),
                    "etaSeconds": _eta(job.started_at, pct),
                    "message": event.get("message", ""),
                }
                job.last_frame = frame
                await job.queue.put({"_type": "frame", **frame})

            rc = await proc.wait()
            if rc == 0:
                out_dir = _project_root() / "output" / session_name
                base = f"/api/sessions/{session_id}/download"
                assets = _available_assets(session_name, base)
                chapters = _collect_chapters(out_dir)
                job.assets = assets
                job.chapters = chapters
                job.finished = True
                job.last_frame = {
                    "stage": "encode", "pct": 100.0, "etaSeconds": 0,
                    "message": "Complete",
                }
                await job.queue.put({
                    "_type": "done",
                    "assets": assets,
                    "chapters": chapters,
                })
                s.phase = "complete"
                s.session_name = session_name
                store.save(s)
            else:
                msg = f"main.py exited with code {rc}"
                job.error = msg
                job.finished = True
                await job.queue.put({"_type": "error", "message": msg, "code": rc})
                s.phase = "failed"
                store.save(s)
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            job.error = msg
            job.finished = True
            await job.queue.put({"_type": "error", "message": msg, "code": -1})
            s.phase = "failed"
            store.save(s)
        finally:
            _delete_job_later(session_id)

    asyncio.create_task(_drive())
    return {
        "jobId": session_id,
        "streamUrl": f"/api/sessions/{session_id}/render/stream",
        "status": "started",
    }


@router.get("/api/sessions/{session_id}/render/stream")
async def render_stream(
    session_id: str,
    token: str = Query(...),
):
    user = auth.user_from_query_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    s = store.get(session_id)
    if not s or s.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")

    job = _jobs.get(session_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No active render")

    async def gen():
        # Replay the latest frame so a reconnect picks up the current
        # state immediately rather than waiting for the next event.
        if job.last_frame.get("stage") is not None:
            yield f"data: {json.dumps(job.last_frame)}\n\n"

        # Job already done? Emit terminal frame and close.
        if job.finished:
            if job.error:
                yield (
                    f"event: error\ndata: "
                    f"{json.dumps({'message': job.error})}\n\n"
                )
            elif job.assets is not None:
                yield (
                    f"event: done\ndata: "
                    f"{json.dumps({'assets': job.assets, 'chapters': job.chapters or []})}\n\n"
                )
            return

        # Live stream — drain the queue until a terminal event.
        while True:
            try:
                data = await asyncio.wait_for(job.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            t = data.get("_type")
            if t == "frame":
                payload = {k: v for k, v in data.items() if not k.startswith("_")}
                yield f"data: {json.dumps(payload)}\n\n"
            elif t == "done":
                done_payload = {
                    "assets": data.get("assets", {}),
                    "chapters": data.get("chapters", []),
                }
                yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
                return
            elif t == "error":
                err_payload = {
                    "message": data.get("message", ""),
                    "code": data.get("code", -1),
                }
                yield f"event: error\ndata: {json.dumps(err_payload)}\n\n"
                return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/sessions/{session_id}/render/status")
async def render_status(
    session_id: str,
    current_user: dict = Depends(auth.get_current_user),
):
    """Poll endpoint for reloads — returns the last frame so the page
    can decide whether to re-subscribe to the SSE stream."""
    s = store.get(session_id)
    if not s or s.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")
    job = _jobs.get(session_id)
    if job is None:
        return {"phase": s.phase, "running": False}
    return {
        "phase": s.phase,
        "running": not job.finished,
        "stage": job.last_frame.get("stage"),
        "pct": job.last_frame.get("pct"),
        "etaSeconds": job.last_frame.get("etaSeconds"),
        "assets": job.assets,
        "chapters": job.chapters,
        "error": job.error,
    }


@router.get("/api/sessions/{session_id}/download/{kind}")
async def download_asset(
    session_id: str,
    kind: str,
    token: str = Query(...),
):
    user = auth.user_from_query_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    s = store.get(session_id)
    if not s or s.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")

    if kind not in DOWNLOAD_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown kind: {kind}")
    filename, media_type = DOWNLOAD_KINDS[kind]

    session_name = s.session_name or s.context_variables.get("last_build")
    if not session_name:
        raise HTTPException(status_code=404, detail="No render output for this session")

    out_root = (_project_root() / "output").resolve()
    file_path = (_project_root() / "output" / session_name / filename).resolve()
    if not _is_within(file_path, out_root):
        raise HTTPException(status_code=404, detail="Path traversal blocked")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} not found")

    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=f"{session_name}_{filename}",
    )
