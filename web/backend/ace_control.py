"""Optional ACE lifecycle API and single-worker GPU admission gate."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

import httpx
from fastapi import APIRouter, Depends, HTTPException

from . import auth, db, permissions
from .ace_control_contract import ServiceState

router = APIRouter(prefix="/api/generator/service")
# Inherit uvicorn's installed console handler so successful operator actions
# reach the journal as well as refusals, without changing global logging.
log = logging.getLogger("uvicorn.error.ace_control")
_gates: WeakKeyDictionary = WeakKeyDictionary()


def configured() -> bool:
    # Partial configuration must not silently fall back to unmanaged mode.
    return bool(os.getenv("ACESTEP_CONTROL_URL", "").strip())


def gate() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    return _gates.setdefault(loop, asyncio.Lock())


async def controller(action: str | None = None) -> ServiceState:
    base = os.getenv("ACESTEP_CONTROL_URL", "").strip().rstrip("/")
    token = os.getenv("ACESTEP_CONTROL_TOKEN", "")
    if not base or len(token) < 32:
        raise HTTPException(503, "ACE service control is not configured.")
    try:
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            response = await client.request(
                "POST" if action else "GET",
                base + "/v1/service" + (f"/{action}" if action else ""),
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code == 409:
            detail = response.json().get("detail")
            raise HTTPException(409, detail if isinstance(detail, str) else "ACE is busy.")
        response.raise_for_status()
        return ServiceState.model_validate(response.json())
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise HTTPException(503, "ACE controller is unavailable. Refresh status before retrying.") from exc


def pending_results() -> int:
    connection = db._conn()
    try:
        return connection.execute("SELECT COUNT(*) FROM generations WHERE status = 'pending'").fetchone()[0]
    finally:
        connection.close()


def reject_live() -> None:
    from .generator import live_session_active, VRAM_CONFLICT_MESSAGE
    if live_session_active():
        raise HTTPException(409, VRAM_CONFLICT_MESSAGE)


async def generation_access(current_user: dict = Depends(auth.get_current_user)):
    """Hold admission through release AND persistence of its task id."""
    if not configured():
        yield
        return
    async with gate():
        reject_live()
        await controller("check")
        yield


@asynccontextmanager
async def live_admission():
    """Keep the check and WS registration atomic with ACE admission."""
    if not configured():
        yield
        return
    async with gate():
        state = await controller()
        if state.state not in {"stopped", "failed"}:
            raise HTTPException(409, "Stop ACE in Generations before starting a live set.")
        yield


@router.get("")
async def service_status(current_user: dict = Depends(auth.get_current_user)):
    from .generator import live_session_active
    snapshot = ServiceState(state="unknown", reason="ACE service control is not configured.")
    reachable = False
    if configured():
        try:
            snapshot = await controller()
            reachable = True
        except HTTPException as exc:
            snapshot.reason = exc.detail
    return {
        **snapshot.model_dump(), "configured": configured(), "reachable": reachable,
        "can_manage": permissions.has_capability(current_user, permissions.MANAGE_GENERATOR),
        "blocked_by_live": live_session_active(),
        "pending_results": await asyncio.to_thread(pending_results),
    }


@router.post("/{action}", response_model=ServiceState)
async def service_action(action: str, current_user: dict = Depends(auth.get_current_user)):
    if not permissions.has_capability(current_user, permissions.MANAGE_GENERATOR):
        raise HTTPException(403, "Only an Apollo administrator can control ACE.")
    if action not in {"start", "stop"}:
        raise HTTPException(404, "Unknown service action.")
    async with gate():
        reject_live()
        if action == "stop" and await asyncio.to_thread(pending_results):
            raise HTTPException(409, "Generation results are still pending. Resume pending batches in Generations before stopping ACE.")
        try:
            result = await controller(action)
        except HTTPException as exc:
            log.warning("ACE control user=%s action=%s result=refused status=%s", current_user["id"], action, exc.status_code)
            raise
        log.info("ACE control user=%s action=%s state=%s", current_user["id"], action, result.state)
        return result
