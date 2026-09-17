"""Authenticated Apollo gateway to host-side Mind operations."""
import asyncio
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from . import ace_control, auth, permissions
from .mind_supervisor import Settings

router = APIRouter(prefix="/api/mind")


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


def admin(user: dict):
    if not permissions.has_capability(user, permissions.MANAGE_GENERATOR):
        raise HTTPException(403, "Only an Apollo administrator can manage models and settings.")


@router.get("")
async def status(user: dict = Depends(auth.get_current_user)):
    result = await host()
    if isinstance(result, dict):
        result["can_manage"] = permissions.has_capability(user, permissions.MANAGE_GENERATOR)
    return result


@router.put("/settings")
async def configure(settings: Settings, user: dict = Depends(auth.get_current_user)):
    admin(user)
    return await host("/settings", "PUT", settings.model_dump())


@router.post("/actions/{action}")
async def action(action: str, user: dict = Depends(auth.get_current_user)):
    admin(user)
    if action not in {"start", "stop", "load", "unload"}:
        raise HTTPException(404, "Unknown Mind action.")
    async with ace_control.gate():
        if action in {"load", "unload"}:
            ace_control.reject_live()
            if await asyncio.to_thread(ace_control.pending_results):
                raise HTTPException(409, "Finish collecting pending generations before changing model residency.")
        return await host("/actions/" + action, "POST")


@router.get("/infer")
async def models(user: dict = Depends(auth.get_current_user)):
    return {"models": ["apollo-mind"], "default": "apollo-mind"}


@router.post("/infer")
async def infer(payload: dict, user: dict = Depends(auth.get_current_user)):
    if not permissions.has_capability(user, permissions.GENERATE_MUSIC):
        raise HTTPException(403, "This account cannot ask Mind.")
    return await host("/infer", "POST", payload)
