"""Authenticated Apollo gateway to the host-side Algorave Mind SERVICE.

The Mind is an HTTP process on the GPU host that turns an intent into
Strudel. It thinks with the main LLM — the one model ``main_llm`` chooses
and loads — so this gateway carries no model settings and no load or
unload: it starts and stops the service, and forwards inference naming
the main LLM so the host can verify that model is the one resident.
"""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from . import ace_control, auth, main_llm, permissions

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mind")


def configured() -> bool:
    return bool(os.getenv("ACESTEP_CONTROL_URL", "").strip()) and len(os.getenv("ACESTEP_CONTROL_TOKEN", "")) >= 32


async def host(path: str = "", method: str = "GET", payload=None):
    base = os.getenv("ACESTEP_CONTROL_URL", "").strip().rstrip("/")
    token = os.getenv("ACESTEP_CONTROL_TOKEN", "")
    if not base or len(token) < 32:
        raise HTTPException(503, "Mind host controller is not configured.")
    try:
        async with httpx.AsyncClient(timeout=280 if path == "/infer" else 25, trust_env=False) as client:
            response = await client.request(method, base + "/v1/mind" + path, json=payload,
                                            headers={"Authorization": "Bearer " + token})
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Mind controller is unavailable. Refresh status.") from exc
    if response.status_code >= 400:
        return JSONResponse(result, status_code=response.status_code)
    return result


async def inference_pending() -> bool:
    """Whether the host reports an answer in flight or an unresolved transport.

    Best effort, for ``main_llm``'s unload guard: an unconfigured or
    unreachable controller answers False, because a dead controller must
    not make the main LLM impossible to unload.
    """
    if not configured():
        return False
    try:
        status = await host()
    except HTTPException:
        log.warning("Mind controller unreachable while checking for an answer in flight")
        return False
    if not isinstance(status, dict):
        return False
    return bool(status.get("busy") or status.get("uncertain"))


def admin(user: dict):
    if not permissions.has_capability(user, permissions.MANAGE_GENERATOR):
        raise HTTPException(403, "Only an Apollo administrator can manage the Mind service.")


@router.get("")
async def status(user: dict = Depends(auth.get_current_user)):
    result = await host()
    if isinstance(result, dict):
        result["can_manage"] = permissions.has_capability(user, permissions.MANAGE_GENERATOR)
        result["main_llm"] = main_llm.current_model()
    return result


@router.post("/actions/{action}")
async def action(action: str, user: dict = Depends(auth.get_current_user)):
    admin(user)
    if action not in {"start", "stop"}:
        raise HTTPException(404, "Unknown Mind action.")
    async with ace_control.gate():
        return await host("/actions/" + action, "POST")


@router.get("/infer")
async def models(user: dict = Depends(auth.get_current_user)):
    model = main_llm.current_model()
    return {"models": [model], "default": model}


@router.post("/infer")
async def infer(payload: dict, user: dict = Depends(auth.get_current_user)):
    if not permissions.has_capability(user, permissions.GENERATE_MUSIC):
        raise HTTPException(403, "This account cannot ask Mind.")
    model = main_llm.current_model()
    if payload.get("model") not in {None, model}:
        raise HTTPException(422, "The Mind answers with the main LLM chosen in Settings.")
    payload["model"] = model
    return await host("/infer", "POST", payload)
