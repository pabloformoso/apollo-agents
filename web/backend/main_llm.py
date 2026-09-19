"""Manage the ONE LM Studio model Apollo thinks with: the main LLM.

Brief extraction, session planning, the live DJ and the Algorave Mind
are four callers of the SAME model. Until 2026-09-19 Apollo managed it
as two — a "session model" loaded over LM Studio's REST API and a "Mind
model" loaded on the host under a private alias — so one physical LLM
had two settings files, two load buttons and, when both were pressed,
two copies in VRAM on a GPU shared with ACE. This module is the single
place that model is chosen, loaded and unloaded; every caller resolves
it through ``persisted_model()`` / ``current_model()``.

ACE is the other resident of that GPU and stays its own service: it
generates audio, it is not an LLM, and it keeps its own panel.

The model is served by the OpenAI-compatible endpoint configured in
``OLLAMA_BASE_URL``.  LM Studio's native REST API is used for inventory
and residency so operators do not have to edit ``.env`` or restart
Apollo just to switch.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import ace_control, auth, permissions

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/main-llm")

_DEFAULT_MODEL = "gemma4:4b"
_DEFAULT_CONTEXT = 8192


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_key: str = Field(min_length=1, max_length=256)
    context_length: int = Field(default=_DEFAULT_CONTEXT, ge=512, le=131072)
    flash_attention: bool = True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def settings_path() -> Path:
    configured = os.getenv("APOLLO_MAIN_LLM_SETTINGS_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _repo_root() / ".tmp" / "main-llm-settings.json"


def _legacy_settings_path() -> Path:
    """Where the "session model" era (PR #207/#208) persisted its choice.

    Read-only: a selection an administrator saved before the rename still
    applies on the first boot after it, and the first save writes the new
    file. Same shape, so the same ``Settings`` validates it.
    """
    configured = os.getenv("APOLLO_SESSION_MODEL_SETTINGS_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _repo_root() / ".tmp" / "session-model-settings.json"


def default_model() -> str:
    return os.getenv("AGENT_MODEL", "").strip() or _DEFAULT_MODEL


def _stored_path() -> Path | None:
    path = settings_path()
    if path.exists():
        return path
    legacy = _legacy_settings_path()
    return legacy if legacy.exists() else None


def read_settings() -> Settings:
    path = _stored_path()
    if path is None:
        return Settings(model_key=default_model())
    try:
        return Settings.model_validate(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(503, "Main LLM settings are unreadable; check the server configuration.") from exc


def persisted_model() -> str | None:
    """Return the operator-selected model, without breaking inference startup."""
    try:
        if _stored_path() is None:
            return None
        return read_settings().model_key
    except HTTPException:
        log.warning("Main LLM settings could not be read", exc_info=True)
        return None


def current_model() -> str:
    """The model every caller should name: the saved choice, else the env default."""
    return persisted_model() or default_model()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(settings.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, 0o600)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    except OSError as exc:
        raise HTTPException(503, "Main LLM settings could not be saved.") from exc


def provider() -> str:
    return os.getenv("AGENT_PROVIDER", "").strip().lower() or ("ollama" if os.getenv("OLLAMA_BASE_URL") else "")


def endpoint() -> str:
    """Turn the OpenAI-compatible ``.../v1`` URL into LM Studio's API root."""
    raw = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def _headers() -> dict[str, str]:
    token = os.getenv("LM_STUDIO_API_TOKEN", "").strip() or os.getenv("OLLAMA_API_KEY", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _model_record(raw: dict[str, Any]) -> dict[str, Any]:
    loaded = raw.get("loaded_instances")
    if not isinstance(loaded, list):
        loaded = []
    return {
        "key": str(raw.get("key") or raw.get("id") or raw.get("model_key") or ""),
        "name": str(raw.get("display_name") or raw.get("name") or raw.get("key") or raw.get("id") or ""),
        "type": raw.get("type", "llm"),
        "state": "loaded" if loaded else str(raw.get("state") or "not-loaded"),
        "loaded_instances": loaded,
        "max_context_length": raw.get("max_context_length"),
        "architecture": raw.get("architecture") or raw.get("arch"),
        "params_string": raw.get("params_string"),
    }


async def _request(path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    base = endpoint()
    if not base or provider() not in {"ollama", "lmstudio"}:
        raise HTTPException(503, "Main LLM management requires an LM Studio OpenAI-compatible endpoint.")
    try:
        async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
            response = await client.request(method, base + path, json=payload, headers=_headers())
    except httpx.HTTPError as exc:
        raise HTTPException(503, "LM Studio is unavailable. Check the model server and refresh status.") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:500]}
    if response.status_code >= 400:
        detail = body.get("error") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type")
        raise HTTPException(response.status_code, str(detail or "LM Studio rejected the request."))
    return body


async def list_models() -> list[dict[str, Any]]:
    try:
        body = await _request("/api/v1/models")
        values = body.get("models", []) if isinstance(body, dict) else []
    except HTTPException as exc:
        if exc.status_code not in {404, 405}:
            raise
        body = await _request("/api/v0/models")
        values = body.get("data", []) if isinstance(body, dict) else []
    return [_model_record(item) for item in values if isinstance(item, dict) and _model_record(item)["key"]]


async def status_snapshot(user: dict) -> dict[str, Any]:
    configured = bool(endpoint()) and provider() in {"ollama", "lmstudio"}
    settings = read_settings()
    if not configured:
        return {
            "configured": False, "provider": provider() or "unknown", "endpoint": None,
            "settings": settings.model_dump(), "models": [], "loaded_model": None, "selected_loaded": False,
            "can_manage": permissions.has_capability(user, permissions.MANAGE_GENERATOR),
            "error": "Set AGENT_PROVIDER=ollama and OLLAMA_BASE_URL to manage an LM Studio model.",
        }
    try:
        models = await list_models()
        selected = next((m for m in models if m["key"] == settings.model_key), None)
        loaded = [m for m in models if m["loaded_instances"]]
        return {
            "configured": True, "provider": provider(), "endpoint": endpoint(),
            "settings": settings.model_dump(), "models": models,
            "selected": selected, "loaded_model": loaded[0]["key"] if loaded else None,
            "selected_loaded": bool(selected and selected["loaded_instances"]),
            "can_manage": permissions.has_capability(user, permissions.MANAGE_GENERATOR), "error": None,
        }
    except HTTPException as exc:
        return {
            "configured": True, "provider": provider(), "endpoint": endpoint(),
            "settings": settings.model_dump(), "models": [], "loaded_model": None, "selected_loaded": False,
            "can_manage": permissions.has_capability(user, permissions.MANAGE_GENERATOR),
            "error": str(exc.detail),
        }


def _shares_host_with_ace() -> bool:
    """Return whether LM Studio and ACE point at the same machine."""
    lm_host = urlsplit(os.getenv("OLLAMA_BASE_URL", "")).hostname
    ace_host = urlsplit(os.getenv("ACESTEP_CONTROL_URL", "")).hostname
    return bool(lm_host and ace_host and lm_host == ace_host)


async def _ensure_capacity() -> None:
    """Avoid an opaque LM Studio load error when ACE owns the shared GPU."""
    if not _shares_host_with_ace() or not ace_control.configured():
        return
    try:
        state = await ace_control.controller()
    except HTTPException:
        # ACE's controller may be unavailable while the LM Studio host is
        # still usable. Let LM Studio make the final decision in that case.
        return
    if state.loaded or state.state in {"starting", "stopping"}:
        raise HTTPException(
            409,
            "Stop ACE before loading the main LLM. ACE is holding the shared GPU.",
        )


async def _ensure_mind_idle() -> None:
    """Never pull the model out from under an Algorave answer in flight.

    The Mind service runs on the GPU host and is the one caller whose
    request outlives the browser (``mind_supervisor.infer``). Its
    supervisor reports ``busy``/``uncertain``; when it is not configured
    or cannot be reached there is nothing to consult and the unload goes
    ahead — LM Studio is the authority on its own residency.
    """
    from . import mind_control  # noqa: PLC0415 — sibling router, imported lazily to avoid a cycle
    if await mind_control.inference_pending():
        raise HTTPException(409, "The Algorave Mind is answering. Wait for it to finish before unloading the main LLM.")


def _selected_settings(settings: Settings | None) -> Settings:
    return settings if settings is not None else read_settings()


def _find_model(models: list[dict[str, Any]], key: str) -> dict[str, Any]:
    selected = next((model for model in models if model["key"] == key), None)
    if selected is None or selected.get("type") not in {"llm", "vlm"}:
        raise HTTPException(422, "That model is not available on the configured LM Studio server.")
    return selected


def admin(user: dict) -> None:
    if not permissions.has_capability(user, permissions.MANAGE_GENERATOR):
        raise HTTPException(403, "Only an Apollo administrator can manage the main LLM.")


@router.get("")
async def status(user: dict = Depends(auth.get_current_user)):
    return await status_snapshot(user)


@router.put("/settings")
async def configure(settings: Settings, user: dict = Depends(auth.get_current_user)):
    admin(user)
    models = await list_models()
    _find_model(models, settings.model_key)
    save_settings(settings)
    return settings.model_dump()


@router.post("/actions/{action}")
async def action(
    action: str,
    settings: Settings | None = None,
    user: dict = Depends(auth.get_current_user),
):
    admin(user)
    if action not in {"load", "unload"}:
        raise HTTPException(404, "Unknown main LLM action.")
    async with ace_control.gate():
        ace_control.reject_live()
        if action == "load":
            await _ensure_capacity()
            selected_settings = _selected_settings(settings)
            models = await list_models()
            selected = _find_model(models, selected_settings.model_key)
            if settings is not None:
                # Loading from the selector is an atomic selection + apply
                # operation. The old flow loaded the environment default when
                # the user had changed the dropdown but not clicked Save.
                save_settings(selected_settings)
            context_length = selected_settings.context_length
            max_context = selected.get("max_context_length")
            if isinstance(max_context, int):
                context_length = min(context_length, max_context)
            return await _request("/api/v1/models/load", "POST", {
                "model": selected_settings.model_key,
                "context_length": context_length,
                "flash_attention": selected_settings.flash_attention,
                "echo_load_config": True,
            })
        await _ensure_mind_idle()
        models = await list_models()
        instances = [i for m in models for i in m["loaded_instances"] if isinstance(i, dict)]
        if not instances:
            return {"status": "unloaded", "instance_id": None}
        instance_id = instances[0].get("instance_id") or instances[0].get("id") or instances[0].get("key")
        return await _request("/api/v1/models/unload", "POST", {"instance_id": instance_id})
