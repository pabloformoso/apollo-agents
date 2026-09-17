"""Host-side optional service. Run one worker, as the ACE service's Unix user.

No shell, caller-supplied unit names, privileged Docker socket, or credentials
from the browser. Installation/configuration: docs/s0-ace-control.md.
"""
from __future__ import annotations

import asyncio
import hmac
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

from .ace_control_contract import ServiceState, queue_counts

UNIT = "apollo-acestep.service"
app = FastAPI(title="Apollo ACE controller", docs_url=None, redoc_url=None, openapi_url=None)
_lock = asyncio.Lock()


def authorize(authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("ACESTEP_CONTROL_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Controller token is not configured (minimum 32 characters).")
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Invalid controller credentials.")


async def systemctl(*args: str) -> str:
    """Only internal constants reach this argv. Bound and reap each child."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/systemctl", "--user", *args, UNIT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise HTTPException(503, "Service manager is unavailable.") from exc
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), 5)
    except (TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        raise
    if proc.returncode:
        raise HTTPException(503, "Service manager rejected the operation; check the host journal.")
    return stdout.decode().strip()


async def ace_json(path: str) -> dict:
    base = os.getenv("ACESTEP_LOCAL_URL", "http://127.0.0.1:8001").rstrip("/")
    key = os.getenv("ACESTEP_API_KEY", "")
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        response = await client.get(base + path, headers={"Authorization": f"Bearer {key}"} if key else {})
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict) or body.get("code", 200) != 200 or body.get("error"):
        raise ValueError("Invalid ACE response")
    body = body.get("data", body)
    if not isinstance(body, dict):
        raise ValueError("Invalid ACE payload")
    return body


async def llm_idle() -> None:
    """No automatic unloading of another workload. Unknown state is a refusal."""
    url = os.getenv("ACESTEP_CONTROL_LLM_URL", "http://127.0.0.1:1234/api/v0/models")
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            models = response.json()["data"]
        if not isinstance(models, list) or any(
            not isinstance(m, dict) or m.get("state") not in {"loaded", "not-loaded"}
            for m in models
        ):
            raise ValueError("Unknown model state")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Cannot verify that the DJ / LLM has released the GPU.") from exc
    from . import mind_supervisor
    if mind_supervisor._uncertain or (mind_supervisor.busy() and mind_supervisor._operation in {"load", "unload"}):
        raise HTTPException(409, "A Mind model residency operation is running. Wait for it to finish.")
    if any(m["state"] == "loaded" for m in models):
        shared = mind_supervisor.read_settings().allow_shared_gpu
        if shared:
            _, loaded = await mind_supervisor.inventory()
            shared = bool(loaded) and all(m["identifier"] == mind_supervisor.MODEL_ID for m in loaded)
        if not shared:
            raise HTTPException(409, "The DJ / LLM still holds the GPU. Unload its models before using ACE.")


async def observe() -> ServiceState:
    try:
        raw = await systemctl("show", "--property=LoadState,ActiveState", "--no-pager")
    except (HTTPException, TimeoutError):
        return ServiceState(state="unknown", reason="Service manager is unavailable.")
    properties = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if properties.get("LoadState") != "loaded":
        return ServiceState(state="unknown", reason="ACE service is not installed.")
    active = properties.get("ActiveState")
    if active in {"inactive", "failed"}:
        # A manual ACE process may already own the port. Do not call it
        # "stopped" or start a second instance merely because our unit is off.
        try:
            await ace_json("/health")
        except httpx.ConnectError:
            pass
        except (httpx.HTTPError, ValueError):
            return ServiceState(state="unknown", reason="Cannot verify that the ACE API is stopped.")
        else:
            return ServiceState(state="unknown", reason="ACE is answering outside the managed service. Check its process on the host.")
    mapped = {"inactive": "stopped", "failed": "failed", "activating": "starting", "deactivating": "stopping"}
    if active in mapped:
        return ServiceState(state=mapped[active])
    if active != "active":
        return ServiceState(state="unknown", reason="Service state is unknown.")
    try:
        health = await ace_json("/health")
        if health.get("status") != "ok":
            raise ValueError("Invalid health")
    except (httpx.HTTPError, ValueError):
        return ServiceState(state="unresponsive", reason="ACE process is active; waiting for its API.")
    counts = None
    try:
        counts = queue_counts(await ace_json("/v1/stats"))
    except (httpx.HTTPError, ValueError):
        pass
    return ServiceState(
        state="running", ready=True,
        loaded=bool(health.get("models_initialized") or health.get("llm_initialized")),
        queued=counts[0] if counts else None,
        running=counts[1] if counts else None,
        reason=None if counts else "Cannot verify the ACE job queue; stopping is disabled.",
    )


@app.get("/v1/service", dependencies=[Depends(authorize)], response_model=ServiceState)
async def service_status():
    return await observe()


@app.post("/v1/service/{action}", dependencies=[Depends(authorize)], response_model=ServiceState)
async def service_action(action: str):
    if action not in {"start", "stop", "check"}:
        raise HTTPException(404, "Unknown service action.")
    async with _lock:
        state = await observe()
        if action == "check":
            if not state.ready:
                raise HTTPException(409, "ACE is not ready to generate.")
            await llm_idle()
            return state
        if action == "start":
            if state.state in {"running", "starting"}:
                return state
            if state.state not in {"stopped", "failed"}:
                raise HTTPException(409, state.reason or "Wait for the service operation to finish.")
            await llm_idle()
        else:
            if state.state in {"stopped", "stopping"}:
                return state
            if state.state != "running" or state.queued is None or state.running is None:
                raise HTTPException(409, state.reason or "Cannot verify that ACE is idle.")
            if state.queued or state.running:
                raise HTTPException(409, "ACE has queued or running jobs. Wait for them to finish.")
        try:
            # Wait for Type=exec to complete. --no-block may acknowledge before
            # state changes, admitting a generation just as a stop begins.
            await systemctl(action)
        except TimeoutError as exc:
            raise HTTPException(503, "Service command timed out. Refresh status before retrying.") from exc
        return ServiceState(state="starting" if action == "start" else "stopping")


from . import mind_supervisor  # noqa: E402 — callbacks import this module lazily
app.include_router(mind_supervisor.router, dependencies=[Depends(authorize)])
