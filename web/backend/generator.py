"""Apollo G0 — ACE-Step generator feature module (backend only, no UI yet).

Owns everything the session wizard's future "generate a track" step needs
from the backend side. Follows the ``render.py`` precedent: an
``APIRouter`` defined here, included from ``app.py`` with a single line,
so the feature can grow (G1 submit/poll/audio-proxy, G2 publisher)
without further surgery on ``app.py``.

Plan: ``docs/acestep-wizard-plan.md``. API contract:
``docs/ACE-STEP-API-SPEC.md``. HTTP client: :mod:`acestep_client`.

``GET /api/generator/health`` is the feature flag the wizard renders
against: ``{available, blocked_by_live, stats}``. "Not available" is a
normal answer — the ACE-Step box is off most of the time by design (the
VRAM protocol below), so the UI must show "generator unavailable"
instead of an error state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from . import acestep_client, auth
from .ws_manager import ws_manager


#: ``ws_manager`` channel the primary live WS registers under. Defined in
#: ``app.live_session_ws`` (``ws_manager.connect(..., channel="live")``).
LIVE_WS_CHANNEL = "live"


def live_session_active(session_id: str | None = None) -> bool:
    """Apollo's side of the ACE-Step VRAM protocol: is a live set on air?

    The 16 GB GPU is shared between ACE-Step (~12.5 GB once loaded, and
    it does not give it back) and the live DJ's LM Studio model. Starting
    a generation during a broadcast starves the DJ — the symptom is a
    400 "Failed to load model" while ``/v1/models`` still lists it.

    **This is the guard G1 enforces.** ``GET /api/generator/health``
    merely surfaces it; G1's generation endpoints must call this helper
    and REFUSE to release a task while it returns ``True``. Import it
    from here (``from .generator import live_session_active``) rather
    than re-deriving live state, so there is one definition to fix.

    It reads the REAL registry: ``ws_manager``'s connection table, whose
    ``live``-channel entry is created by the primary live WS handler
    after its playlist checks and removed in that handler's ``finally``.
    Log grepping (``docker logs | grep live-ws``, as the API spec
    suggests for humans) is explicitly NOT the mechanism here — it is
    unreliable, racy, and invisible to tests.

    Read-only viewers (OBS via ``/live/viewer``) deliberately do not
    count: they never touch ``ws_manager`` and cannot drive an engine, so
    a lingering viewer with no primary consumes no VRAM.

    Args:
        session_id: check one session instead of the whole box. Defaults
            to ``None`` = "is ANY session live?", which is the right
            question for a shared GPU — another session's broadcast
            blocks generation just as hard as this one's.
    """
    if session_id is not None:
        return ws_manager.is_connected(session_id, channel=LIVE_WS_CHANNEL)
    return bool(ws_manager.active_sessions(channel=LIVE_WS_CHANNEL))


def _client() -> acestep_client.AceStepClient:
    """Build the ACE-Step client for a request.

    A function rather than a module-level singleton so the env is read
    per call (``--reload`` + late ``.env``) and so tests can inject an
    ``httpx.MockTransport`` by monkeypatching this seam — the suite must
    never open a socket toward a real ACE-Step box.
    """
    return acestep_client.AceStepClient()


router = APIRouter()


@router.get("/api/generator/health")
async def generator_health(
    current_user: dict = Depends(auth.get_current_user),
):
    """Feature flag + queue snapshot for the wizard's generation step.

    ``available``: ``ACESTEP_BASE_URL`` is set AND ``/health`` answered.
    ``blocked_by_live``: a live set is on air (see
    :func:`live_session_active`) — generation must not start.
    ``stats``: ``/v1/stats`` (queue depth, ``avg_job_seconds`` for the
    UI's ETA) when up, else ``None``.

    Never 5xx on a dead generator: unreachable is a normal state, so it
    reports ``available: false``. A ``/health`` that answers while
    ``/v1/stats`` fails still reports available with ``stats: null``
    rather than lying about the box being down.
    """
    client = _client()
    available = await client.health()

    stats = None
    if available:
        try:
            stats = await client.stats()
        except acestep_client.AceStepError as exc:
            # Up but not answering /v1/stats — degrade to no ETA data.
            print(f"[generator] /v1/stats failed: {exc}", flush=True)
            stats = None

    return {
        "available": available,
        "blocked_by_live": live_session_active(),
        "stats": stats,
    }
