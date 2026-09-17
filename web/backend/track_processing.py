"""Durable, single-worker preparation queue stored with its catalog entries.

Only web publishing and this worker share the lock. Do not run catalog CLI
writers concurrently with the web service (the existing catalog constraint).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading

from fastapi import APIRouter, Depends, HTTPException

from . import auth, permissions

router = APIRouter(prefix="/api/generator/tracks")
log = logging.getLogger("uvicorn.error.track_processing")
CATALOG_PATH = Path("tracks/tracks.json")
ANALYSIS_TIMEOUT_SECONDS = 900
_lock = threading.RLock()


def _read() -> dict:
    if not CATALOG_PATH.exists():
        return {"tracks": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _write(catalog: dict) -> None:
    fd, name = tempfile.mkstemp(dir=CATALOG_PATH.parent, suffix=".tmp")
    try:
        previous = CATALOG_PATH.stat()
        os.chmod(name, previous.st_mode & 0o777)
        if getattr(os, "geteuid", lambda: -1)() == 0:
            os.chown(name, previous.st_uid, previous.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(catalog, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, CATALOG_PATH)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _entry(catalog: dict, track_id: str) -> dict:
    for entry in catalog["tracks"]:
        if entry.get("id") == track_id:
            return entry
    raise HTTPException(404, "Catalog track not found.")


def status(entry: dict) -> dict:
    state = entry.get("processing_status")
    if not state:
        complete = all(entry.get(k) is not None for k in
                       ("duration_sec", "beatgrid", "waveform_peaks", "mp3_file"))
        state = "ready" if complete else "unprepared"
    return {"track_id": entry["id"], "status": state,
            "error": entry.get("processing_error")}


def ingest(ingest_track, *args, **kwargs):
    # The queued marker is in the first write: a restart cannot strand the
    # track between publishing and enqueueing, or admit it into a session.
    with _lock:
        return ingest_track(*args, **kwargs, prepare_for_sessions=True)


def snapshot(track_id: str) -> dict:
    with _lock:
        return status(_entry(_read(), track_id))


def enqueue(track_id: str) -> dict:
    with _lock:
        catalog = _read()
        entry = _entry(catalog, track_id)
        if status(entry)["status"] in {"unprepared", "failed"}:
            entry.update(processing_status="queued", processing_error=None)
            _write(catalog)
        return status(entry)


def recover() -> None:
    with _lock:
        catalog = _read()
        changed = False
        for entry in catalog["tracks"]:
            if entry.get("processing_status") == "running":
                entry.update(processing_status="queued", processing_error=None)
                changed = True
        if changed:
            _write(catalog)


def claim() -> dict | None:
    with _lock:
        catalog = _read()
        for entry in catalog["tracks"]:
            if entry.get("processing_status") == "queued":
                entry.update(processing_status="running", processing_error=None)
                _write(catalog)
                return dict(entry)
    return None


def finish(track_id: str, updates: dict) -> None:
    with _lock:
        # Read again AFTER analysis, retaining other publications/metadata.
        catalog = _read()
        _entry(catalog, track_id).update(updates)
        _write(catalog)


async def analyse(entry: dict) -> dict:
    source = Path(entry["file"]).resolve()
    if not source.is_relative_to(Path("tracks").resolve()) or not source.is_file():
        raise RuntimeError("The catalog audio file is missing or outside tracks/.")
    with tempfile.TemporaryDirectory(prefix="apollo-analysis-") as work:
        result = Path(work) / "result.json"
        env = {**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "CUDA_VISIBLE_DEVICES": ""}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "web.backend.track_analysis", str(source),
            str(entry.get("bpm") or 0), str(result), env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=ANALYSIS_TIMEOUT_SECONDS)
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        if not result.exists():
            raise RuntimeError("Audio analysis exited without a result. Check server dependencies.")
        payload = json.loads(result.read_text())
        if proc.returncode or "error" in payload:
            raise RuntimeError(payload.get("error", "Audio analysis failed."))
        return payload


async def process_one() -> bool:
    from .generator import live_session_active
    if live_session_active():
        return False
    entry = await asyncio.to_thread(claim)
    if entry is None:
        return False
    try:
        updates = await analyse(entry)
        updates.update(processing_status="ready", processing_error=None)
    except asyncio.CancelledError:
        await asyncio.to_thread(finish, entry["id"], {"processing_status": "queued"})
        raise
    except Exception as exc:
        log.exception("Track preparation failed: %s", entry["id"])
        updates = {"processing_status": "failed", "processing_error": str(exc)[:300] or "Audio analysis timed out. Retry preparation."}
    await asyncio.to_thread(finish, entry["id"], updates)
    return True


async def run() -> None:
    recovered = False
    while True:
        try:
            if not recovered:
                await asyncio.to_thread(recover)
                recovered = True
            await process_one()
        except Exception:
            log.exception("Track preparation queue failed")
            recovered = False
        await asyncio.sleep(3)


@contextlib.asynccontextmanager
async def worker():
    task = asyncio.create_task(run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@router.get("/{track_id}/processing")
async def get_processing(track_id: str, user: dict = Depends(auth.get_current_user)):
    return await asyncio.to_thread(snapshot, track_id)


@router.post("/{track_id}/processing")
async def retry_processing(track_id: str, user: dict = Depends(auth.get_current_user)):
    if not permissions.has_capability(user, permissions.PUBLISH_TO_CATALOG):
        raise HTTPException(403, "Only a catalog publisher can prepare tracks.")
    return await asyncio.to_thread(enqueue, track_id)
