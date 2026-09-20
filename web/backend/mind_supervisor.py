"""Host-only Mind service control. Browser input never becomes a command or URL.

The Mind service (``apollo-mind.service``, the algorave playground on
loopback:4032) thinks with the main LLM, which Apollo loads into LM Studio
over its REST API (``web/backend/main_llm.py``). This supervisor therefore
owns no model: it starts and stops the HTTP service and forwards an
answer request only when the model Apollo names is actually resident, so
the playground never triggers a JIT load on the shared GPU.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException

UNIT = "apollo-mind.service"
MIND_URL = "http://127.0.0.1:4032"
router = APIRouter(prefix="/v1/mind")
_task: asyncio.Task | None = None
_operation: str | None = None
_error: str | None = None
_uncertain = False


def busy() -> bool:
    return _task is not None and not _task.done()


def ensure_idle() -> None:
    if busy() or _uncertain:
        raise HTTPException(409, "Mind is answering or a request is unresolved. Keep playing and refresh status.")


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


async def loaded_models() -> list[dict]:
    """The LM Studio instances currently resident, as ``lms ps --json`` reports them."""
    try:
        loaded = json.loads(await command(lms(), "ps", "--json"))
        if not isinstance(loaded, list) or any(
            not isinstance(m, dict) or not isinstance(m.get("modelKey"), str) for m in loaded
        ):
            raise ValueError("Unknown loaded model state")
        return loaded
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "Cannot verify LM Studio model state.") from exc


def is_loaded(loaded: list[dict], model: str) -> bool:
    """Match by model key or by instance identifier — either is what a request may name."""
    return any(m.get("modelKey") == model or m.get("identifier") == model for m in loaded)


async def service_state() -> str:
    raw = await command("/usr/bin/systemctl", "--user", "show", "--property=LoadState,ActiveState", UNIT)
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if values.get("LoadState") != "loaded":
        return "not-installed"
    return values.get("ActiveState", "unknown")


@router.get("")
async def status():
    loaded = await loaded_models()
    state = await service_state()
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(MIND_URL + "/models")
            reachable = response.status_code == 200
    except httpx.HTTPError:
        pass
    return {"service": state, "reachable": reachable,
            "loaded_models": [m["modelKey"] for m in loaded],
            "busy": busy(), "operation": _operation, "error": _error, "uncertain": _uncertain}


async def perform(action: str):
    global _error, _uncertain
    try:
        await command("/usr/bin/systemctl", "--user", action, UNIT, timeout=20)
    except TimeoutError:
        _error = "Service command timed out; check the host journal before retrying."
    except Exception as exc:
        _error = exc.detail if isinstance(exc, HTTPException) else "Mind service operation failed; inspect the host logs."
    else:
        if action == "stop":
            # The unit is KillMode=control-group: a successful stop means
            # the process that might still have been answering is gone,
            # and with it the only work an unresolved transport could
            # have left behind. This is the ONE path that clears the
            # flag — nothing else can know the answer finished.
            _uncertain = False


@router.post("/actions/{action}", status_code=202)
async def action(action: Literal["start", "stop"]):
    global _task, _operation, _error
    from .ace_supervisor import _lock
    async with _lock:
        if action == "stop":
            # Stopping is how an unresolved transport gets resolved, so it
            # is refused only while an answer is genuinely in flight.
            if busy():
                raise HTTPException(409, "Mind is answering. Keep playing and refresh status.")
        else:
            ensure_idle()
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
        _task = asyncio.create_task(perform(action))
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
        _error = "Mind transport failed after dispatch. Verify inference has finished on the host, then Stop Mind to clear this state."
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
    from .ace_supervisor import _lock
    async with _lock:
        ensure_idle()
        if len(json.dumps(payload).encode()) > 256 * 1024:
            raise HTTPException(400, "Mind request is too large.")
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            raise HTTPException(422, "Name the main LLM the Mind should answer with.")
        if not is_loaded(await loaded_models(), model):
            raise HTTPException(409, "Load the main LLM from Settings before asking or starting B2B.")
        if await service_state() != "active":
            raise HTTPException(409, "Start the Mind service from Settings.")
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
