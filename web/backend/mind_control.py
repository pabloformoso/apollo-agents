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

#: Answers this process has dispatched to the host and not yet received.
#: Registered under ``ace_control.gate()`` — the lock the main LLM's unload
#: holds for its whole run — so "nothing in flight" checked under that lock
#: stays true until the lock is released. The host's own ``busy`` cannot
#: give that guarantee: it is set only once the request reaches the host.
_inflight = 0


async def host(path: str = "", method: str = "GET", payload=None):
    """One request to the ACE controller's ``/v1/mind`` routes.

    Configured means the URL is set — ``ace_control.configured()``, the
    same rule as ACE, so a URL with a missing or short token is a loud
    503 here rather than a silent "unmanaged".
    """
    base = os.getenv("ACESTEP_CONTROL_URL", "").strip().rstrip("/")
    token = os.getenv("ACESTEP_CONTROL_TOKEN", "")
    if not ace_control.configured():
        raise HTTPException(503, "Mind host controller is not configured.")
    if len(token) < 32:
        raise HTTPException(503, "Mind host controller token is missing or too short.")
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
    """Whether an answer is in flight — from this process or as the host sees it.

    For ``main_llm``'s unload guard. Best effort on the host half: an
    unconfigured or unreachable controller answers False, because a dead
    controller must not make the main LLM impossible to unload. The
    in-process half is exact.
    """
    if _inflight:
        return True
    if not ace_control.configured():
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


def _decorate(result, user: dict):
    result["can_manage"] = permissions.has_capability(user, permissions.MANAGE_GENERATOR)
    result["main_llm"] = main_llm.current_model()
    return result


@router.get("")
async def status(user: dict = Depends(auth.get_current_user)):
    """The host's status, or ``{configured: false}`` when there is no host.

    An install without the controller is a normal shape, not a failure:
    it still manages the model. A CONFIGURED host that cannot be reached
    stays a 503, so the panel can tell the two apart.
    """
    if not ace_control.configured():
        return _decorate({"configured": False}, user)
    result = await host()
    if isinstance(result, dict):
        _decorate(result, user)["configured"] = True
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
    global _inflight
    if not permissions.has_capability(user, permissions.GENERATE_MUSIC):
        raise HTTPException(403, "This account cannot ask Mind.")
    if not main_llm.managed():
        # The Mind runs on the GPU host against LM Studio; a main LLM that
        # is a Claude or Azure name can never be resident there.
        raise HTTPException(503, "The Algorave Mind thinks with the main LLM, which needs an LM Studio endpoint "
                                 "(AGENT_PROVIDER=ollama and OLLAMA_BASE_URL).")
    model = main_llm.current_model()
    if payload.get("model") not in {None, model}:
        raise HTTPException(422, "The Mind answers with the main LLM chosen in Settings.")
    payload["model"] = model
    # Register under the gate, then answer OUTSIDE it: holding the lock for
    # a 20 s answer would also hold up live-set registration and ACE.
    async with ace_control.gate():
        _inflight += 1
    try:
        return await host("/infer", "POST", payload)
    finally:
        _inflight -= 1
