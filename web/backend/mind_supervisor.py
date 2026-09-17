"""Host-only Mind/model control. Browser input never becomes a command or URL."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

UNIT = "apollo-mind.service"
MODEL_ID = "apollo-mind"
MIND_URL = "http://127.0.0.1:4032"
router = APIRouter(prefix="/v1/mind")
_task: asyncio.Task | None = None
_operation: str | None = None
_error: str | None = None
_uncertain = False


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_key: str = Field(default="google/gemma-4-e4b", min_length=1, max_length=250)
    context_length: int = Field(default=4096, ge=512, le=32768)
    gpu_fraction: float = Field(default=0.25, ge=0, le=1)
    allow_shared_gpu: bool = False


def settings_path() -> Path:
    return Path(os.getenv("APOLLO_MIND_SETTINGS_PATH", str(Path.home() / ".config/apollo/mind-settings.json")))


def read_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        return Settings.model_validate_json(path.read_text())
    except (ValueError, OSError) as exc:
        raise HTTPException(503, "Mind settings are unreadable; check the host configuration.") from exc


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(settings.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def busy() -> bool:
    return _task is not None and not _task.done()


def ensure_idle() -> None:
    if busy() or _uncertain:
        raise HTTPException(409, "Mind is busy or a model operation is unresolved. Keep playing and refresh status.")


async def command(*argv: str, timeout: float = 8) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.communicate()
    except OSError as exc:
        raise HTTPException(503, "Host command unavailable. Check the service installation.") from exc
    if proc.returncode:
        raise HTTPException(503, "Host operation failed. Check LM Studio memory and host service logs.")
    return stdout.decode()


def lms() -> str:
    return str(Path.home() / ".lmstudio/bin/lms")


async def inventory() -> tuple[list[dict], list[dict]]:
    try:
        disk, loaded = await asyncio.gather(command(lms(), "ls", "--json"), command(lms(), "ps", "--json"))
        disk, loaded = json.loads(disk), json.loads(loaded)
        if not isinstance(disk, list) or not isinstance(loaded, list):
            raise ValueError("Invalid model list")
        models = [{"key": m["modelKey"], "name": m.get("displayName", m["modelKey"]), "size_bytes": m.get("sizeBytes")}
                  for m in disk if m.get("type") == "llm" and isinstance(m.get("modelKey"), str) and not m["modelKey"].startswith("-")]
        if any(not isinstance(m, dict) or not isinstance(m.get("identifier"), str) for m in loaded):
            raise ValueError("Unknown loaded model state")
        return models, loaded
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "Cannot verify LM Studio model state.") from exc


async def service_state() -> str:
    raw = await command("/usr/bin/systemctl", "--user", "show", "--property=LoadState,ActiveState", UNIT)
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if values.get("LoadState") != "loaded":
        return "not-installed"
    return values.get("ActiveState", "unknown")


@router.get("")
async def status():
    global _uncertain
    models, loaded = await inventory()
    own = next((m for m in loaded if m["identifier"] == MODEL_ID), None)
    state = await service_state()
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(MIND_URL + "/models")
            reachable = response.status_code == 200 and MODEL_ID in response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    if own is not None and _operation == "load" and not busy():
        _uncertain = False
    return {"service": state, "reachable": reachable, "model_loaded": own is not None,
            "loaded_model": own.get("modelKey") if own else None,
            "models": models, "settings": read_settings().model_dump(),
            "busy": busy(), "operation": _operation, "error": _error,
            "uncertain": _uncertain, "other_loaded_models": len(loaded) - int(own is not None)}


@router.put("/settings")
async def configure(settings: Settings):
    from .ace_supervisor import _lock
    async with _lock:
        ensure_idle()
        models, _ = await inventory()
        if settings.model_key not in {m["key"] for m in models}:
            raise HTTPException(422, "Choose a model installed in LM Studio.")
        save_settings(settings)
    return settings.model_dump()


async def perform(action: str, settings: Settings):
    global _error, _uncertain
    try:
        if action in {"start", "stop"}:
            await command("/usr/bin/systemctl", "--user", action, UNIT, timeout=20)
        elif action == "load":
            await command(lms(), "load", settings.model_key, "--identifier", MODEL_ID,
                          "--context-length", str(settings.context_length), "--gpu", str(settings.gpu_fraction),
                          "--yes", timeout=180)
        else:
            await command(lms(), "unload", MODEL_ID, timeout=30)
    except TimeoutError:
        _uncertain = action in {"load", "unload"}
        _error = "Operation timed out; LM Studio may still be working. Refresh and verify on the host before retrying."
    except Exception as exc:
        _error = exc.detail if isinstance(exc, HTTPException) else "Mind operation failed; inspect the host logs."


@router.post("/actions/{action}", status_code=202)
async def action(action: Literal["start", "stop", "load", "unload"]):
    global _task, _operation, _error
    from .ace_supervisor import _lock, observe
    async with _lock:
        ensure_idle()
        settings = read_settings()
        if action in {"load", "unload"}:
            models, loaded = await inventory()
            own = any(m["identifier"] == MODEL_ID for m in loaded)
            if action == "load":
                if own:
                    raise HTTPException(409, "Unload the current Mind model before loading another configuration.")
                if settings.model_key not in {m["key"] for m in models}:
                    raise HTTPException(422, "The configured model is no longer installed.")
                ace = await observe()
                if ace.state not in {"stopped", "failed"} and not settings.allow_shared_gpu:
                    raise HTTPException(409, "ACE is active or unknown. Enable shared GPU explicitly in Settings, or stop ACE yourself.")
            elif not own:
                return {"accepted": True}
        else:
            state = await service_state()
            if state not in {"active", "inactive", "failed"}:
                raise HTTPException(409, "Mind service is not installed or is changing state.")
            # Never start over an unmanaged process on the configured port.
            if action == "start" and state != "active":
                try:
                    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                        await client.get(MIND_URL + "/models")
                except httpx.ConnectError:
                    pass
                except httpx.HTTPError as exc:
                    raise HTTPException(409, "Cannot verify that the Mind port is free.") from exc
                else:
                    raise HTTPException(409, "An unmanaged Mind already owns this port.")
        _operation, _error = action, None
        _task = asyncio.create_task(perform(action, settings))
    return {"accepted": True}


async def infer_request(payload: dict):
    global _uncertain, _error
    try:
        async with httpx.AsyncClient(timeout=260, trust_env=False) as client:
            response = await client.post(MIND_URL + "/mind", json=payload)
    except httpx.ConnectError:
        raise
    except httpx.HTTPError:
        # A transport timeout/disconnect does not cancel work inside the
        # HTTP service or LM Studio. Do not unload underneath that work.
        _uncertain = True
        _error = "Mind transport failed after dispatch. Verify inference has finished on the host before restarting the controller."
        raise
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Mind returned an invalid response.") from exc
    from fastapi.responses import JSONResponse
    return JSONResponse(result, status_code=response.status_code)


@router.post("/infer")
async def infer(payload: dict):
    global _task, _operation
    from .ace_supervisor import _lock, observe
    async with _lock:
        ensure_idle()
        if len(json.dumps(payload).encode()) > 256 * 1024:
            raise HTTPException(400, "Mind request is too large.")
        if not read_settings().allow_shared_gpu and (await observe()).state not in {"stopped", "failed"}:
            raise HTTPException(409, "ACE is active or unknown. Enable shared GPU in Settings to use both, or stop ACE yourself.")
        _, loaded = await inventory()
        if not any(m["identifier"] == MODEL_ID for m in loaded):
            raise HTTPException(409, "Load the Mind model using Model management before asking or starting B2B.")
        if await service_state() != "active":
            raise HTTPException(409, "Start Mind using Model management.")
        if payload.get("model") not in {None, MODEL_ID}:
            raise HTTPException(422, "Select the managed Mind model.")
        payload["model"] = MODEL_ID
        _operation = "inference"
        _task = asyncio.create_task(infer_request(payload))
        # Retain and consume the result even if the browser disconnects. Model
        # unload/stop remain refused while the underlying request is running.
        _task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        task = _task
    try:
        return await asyncio.shield(task)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Mind is unreachable; your current pattern has not been changed.") from exc
