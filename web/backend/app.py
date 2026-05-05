"""
ApolloAgents Web Backend — FastAPI application (v2.0)

Startup:
    uvicorn backend.app:app --reload --port 4020 --app-dir web
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import db, auth, pipeline
from .models import (
    EditorCommandRequest,
    GenreIntentRequest,
    LoginRequest,
    PlaylistAddTracks,
    PlaylistCreate,
    PlaylistRename,
    PlaylistReorder,
    RatingRequest,
    RatingUpdate,
    RegisterRequest,
    TokenResponse,
)
from .session_store import store
from .ws_manager import ws_manager


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="ApolloAgents API", version="2.0.0", lifespan=lifespan)

_DEFAULT_ORIGINS = "http://localhost:4010,http://127.0.0.1:4010"
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("APOLLO_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Genre Guard cap: max user turns before we treat the conversation as
# stuck and emit the "Could not confirm genre" error. See issue #23.
MAX_GENRE_TURNS = 8


def _should_emit_genre_error(history: list[dict]) -> bool:
    """Return True when the genre-guard turn ended without a confirmation
    AND the agent gave up (empty/whitespace assistant response, OR the
    user has hit MAX_GENRE_TURNS without confirming).

    Returns False on the normal "still asking, awaiting user reply" turn,
    so the handler should leave ``s.phase`` at ``"genre"`` instead of
    surfacing a misleading red error banner. See issue #23.
    """
    last_assistant = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "assistant"),
        "",
    )
    if not (last_assistant or "").strip():
        return True
    user_turns = sum(1 for m in history if m.get("role") == "user")
    return user_turns >= MAX_GENRE_TURNS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    if db.get_user_by_username(req.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    user_id = db.create_user(req.username, req.email, auth.hash_password(req.password))
    token = auth.create_access_token({"sub": str(user_id)})
    return TokenResponse(
        access_token=token,
        user={"id": user_id, "username": req.username, "email": req.email},
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = db.get_user_by_username(req.username)
    if not user or not auth.verify_password(req.password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = auth.create_access_token({"sub": str(user["id"])})
    return TokenResponse(
        access_token=token,
        user={"id": user["id"], "username": user["username"], "email": user["email"]},
    )


@app.get("/api/auth/me")
async def me(current_user: dict = Depends(auth.get_current_user)):
    return {"id": current_user["id"], "username": current_user["username"], "email": current_user["email"]}


# ---------------------------------------------------------------------------
# Catalog (read-only browse of tracks.json)
# ---------------------------------------------------------------------------

@app.get("/api/catalog")
async def get_catalog(
    genre: str | None = Query(None, description="Filter by genre_folder (case-insensitive)"),
    current_user: dict = Depends(auth.get_current_user),
):
    try:
        tracks, genres = await asyncio.to_thread(pipeline.load_catalog, genre)
    except pipeline.CatalogUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Hydrate each track with the calling user's own rating (or null). This is
    # always scoped to current_user.id — ratings from other users never leak.
    ratings = await asyncio.to_thread(db.get_user_ratings, current_user["id"])
    enriched = [{**t, "user_rating": ratings.get(t.get("id")) } for t in tracks]
    return {"tracks": enriched, "genres": genres}


# ---------------------------------------------------------------------------
# Audio streaming — single endpoint that browser <audio> can hit directly.
# JWT travels in the query string (browsers can't set Authorization on
# <audio>), mirroring the WebSocket pattern above.
# ---------------------------------------------------------------------------

_STREAM_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def _is_within(path: Path, root: Path) -> bool:
    """True if `path` is the same as or a descendant of `root`. Both paths
    must already be absolute and resolved."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _stream_authorize(token: str) -> dict:
    """Decode the JWT from the query string and load the user, or raise 401."""
    payload = auth.decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)


def _resolve_track_path(track_id: str) -> Path:
    """Look up `track_id` in the catalog and return a safe absolute path.

    Raises 404 for unknown ids or any path that escapes the allowed roots
    (`tracks/` for real catalog entries, `.tmp/` for the mock-pipeline
    fixture used in E2E), and 415 for extensions outside `.wav` / `.mp3`.
    """
    try:
        tracks, _ = pipeline.load_catalog(None)
    except pipeline.CatalogUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    track = next((t for t in tracks if t.get("id") == track_id), None)
    if not track or not track.get("file"):
        raise HTTPException(status_code=404, detail="Track not found")

    project_root = Path(pipeline._PROJECT_DIR).resolve()
    # Path-traversal defence: the resolved file must live under one of the
    # allowed roots. `tracks/` covers real catalog entries; `.tmp/` is the
    # mock-pipeline fixture root used during E2E (see #13 — keeps the mock
    # silence file out of tracks/ so --build-catalog never picks it up).
    allowed_roots = [
        (project_root / "tracks").resolve(),
        (project_root / ".tmp").resolve(),
    ]

    raw_path = (project_root / track["file"]).resolve()

    if not any(_is_within(raw_path, root) for root in allowed_roots):
        raise HTTPException(status_code=404, detail="Track not found")

    if not raw_path.exists() or not raw_path.is_file():
        raise HTTPException(status_code=404, detail="Track file missing")

    suffix = raw_path.suffix.lower()
    if suffix not in _STREAM_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported audio format: {suffix}")

    return raw_path


@app.get("/api/tracks/{track_id}/stream")
async def stream_track(track_id: str, token: str = Query(...)):
    _stream_authorize(token)
    path = await asyncio.to_thread(_resolve_track_path, track_id)
    media_type = _STREAM_MEDIA_TYPES[path.suffix.lower()]
    # Starlette's FileResponse handles Range/206 Partial Content natively,
    # which is what makes seek + iOS playback work without extra plumbing.
    return FileResponse(str(path), media_type=media_type)


# ---------------------------------------------------------------------------
# Playlists (v2.2.1) — named, ordered collections of catalog tracks. The
# tracks themselves stay in `tracks/tracks.json`; only the playlist shell and
# the ordered track_ids live in SQLite. GET hydrates each id back into a full
# Track via the catalog, so the frontend never re-resolves metadata itself.
# ---------------------------------------------------------------------------


def _own_playlist(playlist_id: int, user: dict) -> dict:
    p = db.get_playlist(playlist_id)
    if not p or p["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return p


@app.post("/api/playlists", status_code=201)
async def create_playlist(
    req: PlaylistCreate,
    current_user: dict = Depends(auth.get_current_user),
):
    return db.create_playlist(current_user["id"], req.name)


@app.get("/api/playlists")
async def list_playlists(current_user: dict = Depends(auth.get_current_user)):
    return db.list_playlists_by_user(current_user["id"])


@app.get("/api/playlists/{playlist_id}")
async def get_playlist_detail(
    playlist_id: int,
    current_user: dict = Depends(auth.get_current_user),
):
    p = _own_playlist(playlist_id, current_user)

    try:
        catalog_tracks, _ = await asyncio.to_thread(pipeline.load_catalog, None)
    except pipeline.CatalogUnavailable:
        catalog_tracks = []
    by_id = {t.get("id"): t for t in catalog_tracks if t.get("id")}

    hydrated: list[dict] = []
    for tid in p["track_ids"]:
        t = by_id.get(tid)
        if t is None:
            # Catalog may have been rebuilt and dropped this id — surface it
            # rather than failing so the user can clean up the playlist.
            hydrated.append({"id": tid, "display_name": tid, "missing": True})
        else:
            hydrated.append(t)

    return {
        "id": p["id"],
        "user_id": p["user_id"],
        "name": p["name"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "tracks": hydrated,
    }


@app.patch("/api/playlists/{playlist_id}")
async def rename_playlist_endpoint(
    playlist_id: int,
    req: PlaylistRename,
    current_user: dict = Depends(auth.get_current_user),
):
    _own_playlist(playlist_id, current_user)
    db.rename_playlist(playlist_id, req.name)
    refreshed = db.get_playlist(playlist_id)
    assert refreshed is not None
    return {
        "id": refreshed["id"],
        "user_id": refreshed["user_id"],
        "name": refreshed["name"],
        "created_at": refreshed["created_at"],
        "updated_at": refreshed["updated_at"],
        "track_count": len(refreshed["track_ids"]),
    }


@app.delete("/api/playlists/{playlist_id}", status_code=204)
async def delete_playlist_endpoint(
    playlist_id: int,
    current_user: dict = Depends(auth.get_current_user),
):
    _own_playlist(playlist_id, current_user)
    db.delete_playlist(playlist_id)


@app.post("/api/playlists/{playlist_id}/tracks")
async def add_tracks_endpoint(
    playlist_id: int,
    req: PlaylistAddTracks,
    current_user: dict = Depends(auth.get_current_user),
):
    _own_playlist(playlist_id, current_user)
    new_count = db.add_tracks_to_playlist(playlist_id, req.track_ids)
    return {"playlist_id": playlist_id, "track_count": new_count}


@app.delete("/api/playlists/{playlist_id}/tracks/{track_id}", status_code=204)
async def remove_track_endpoint(
    playlist_id: int,
    track_id: str,
    current_user: dict = Depends(auth.get_current_user),
):
    _own_playlist(playlist_id, current_user)
    if not db.remove_track_from_playlist(playlist_id, track_id):
        raise HTTPException(status_code=404, detail="Track not in playlist")


@app.put("/api/playlists/{playlist_id}/order")
async def reorder_endpoint(
    playlist_id: int,
    req: PlaylistReorder,
    current_user: dict = Depends(auth.get_current_user),
):
    _own_playlist(playlist_id, current_user)
    ok = db.reorder_playlist_tracks(playlist_id, req.track_ids)
    if not ok:
        raise HTTPException(
            status_code=422,
            detail="track_ids must match the playlist's current track_ids exactly",
        )
    refreshed = db.get_playlist(playlist_id)
    assert refreshed is not None
    return {
        "id": refreshed["id"],
        "track_ids": refreshed["track_ids"],
        "updated_at": refreshed["updated_at"],
    }


# ---------------------------------------------------------------------------
# Per-user track ratings (1–5). The catalog endpoint above hydrates the
# `user_rating` field for the calling user; these two routes let the user
# create / update / clear their own rating.
# ---------------------------------------------------------------------------

@app.put("/api/tracks/{track_id}/rating")
async def set_track_rating(
    track_id: str,
    body: RatingUpdate,
    current_user: dict = Depends(auth.get_current_user),
):
    await asyncio.to_thread(
        db.upsert_track_rating, current_user["id"], track_id, body.rating
    )
    return {"track_id": track_id, "rating": body.rating}


@app.delete("/api/tracks/{track_id}/rating", status_code=204)
async def clear_track_rating(
    track_id: str,
    current_user: dict = Depends(auth.get_current_user),
):
    # Idempotent: deleting a non-existent rating succeeds with 204 anyway —
    # the UI fires DELETE on every "click on filled star" without first
    # checking the row exists.
    await asyncio.to_thread(
        db.delete_track_rating, current_user["id"], track_id
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Sessions — REST CRUD
# ---------------------------------------------------------------------------

@app.post("/api/sessions")
async def create_session(current_user: dict = Depends(auth.get_current_user)):
    s = store.create(current_user["id"])
    return s.to_dict()


@app.get("/api/sessions")
async def list_sessions(current_user: dict = Depends(auth.get_current_user)):
    return [s.to_dict() for s in store.get_user_sessions(current_user["id"])]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(auth.get_current_user)):
    return _own(session_id, current_user).to_dict()


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, current_user: dict = Depends(auth.get_current_user)):
    _own(session_id, current_user)
    store.delete(session_id)


# ---------------------------------------------------------------------------
# Rating (REST — called after the session completes)
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{session_id}/rate")
async def rate_session(
    session_id: str,
    req: RatingRequest,
    current_user: dict = Depends(auth.get_current_user),
):
    s = _own(session_id, current_user)
    ctx = s.context_variables
    result = await asyncio.to_thread(
        pipeline.write_session_record,
        session_name=s.session_name or ctx.get("last_build", "unnamed"),
        genre=ctx.get("genre", ""),
        duration_min=ctx.get("duration_min", 0),
        mood=ctx.get("mood", ""),
        rating=req.rating,
        notes=req.notes or "",
        critic_verdict=s.critic_verdict or "",
        critic_problems_json=json.dumps(s.critic_problems),
        validator_status=s.validator_status or "",
        validator_issues_json=json.dumps(s.validator_issues),
        tracks_swapped_json=json.dumps([]),
        final_playlist_json=json.dumps([t.get("display_name") for t in ctx.get("playlist", [])]),
        transition_ratings_json=json.dumps(req.transition_ratings or []),
        structured_problems_json=json.dumps(s.structured_problems),
        context_variables=ctx,
    )
    s.phase = "complete"
    store.save(s)
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# WebSocket — streaming pipeline channel
# ---------------------------------------------------------------------------

@app.websocket("/ws/sessions/{session_id}")
async def session_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
):
    payload = auth.decode_token(token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = db.get_user_by_id(int(payload.get("sub", 0)))
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    s = store.get(session_id)
    if not s or s.user_id != user["id"]:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(session_id, websocket)

    async def emit(data: dict) -> None:
        await ws_manager.send(session_id, data)

    try:
        # Send current state on connect
        await emit({"type": "state", "data": s.to_dict()})

        while True:
            msg = await ws_manager.receive(session_id)
            if msg is None:
                break

            msg_type = msg.get("type")
            content = msg.get("content", "")

            try:
                await _handle_ws_message(s, msg_type, content, emit)
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001 — surface any phase failure as a UI banner
                await emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                # Persist after every message so a backend restart resumes at
                # the last committed phase/playlist/chat-history.
                store.save(s)

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(session_id)


# ---------------------------------------------------------------------------
# WS message dispatcher (separated so the outer loop can catch phase failures
# and emit a graceful `error` event instead of dropping the connection)
# ---------------------------------------------------------------------------

async def _handle_ws_message(s, msg_type: str | None, content: str, emit) -> None:
    # ── Genre Guard ──────────────────────────────────────────────
    if msg_type == "genre_intent":
        s.phase = "genre"
        history = s.messages.setdefault("genre", [])
        try:
            await asyncio.to_thread(pipeline.check_catalog)
        except pipeline.CatalogUnavailable as exc:
            await emit({"type": "error", "message": str(exc)})
            s.phase = "init"
            return
        confirmed = await pipeline.phase_genre_guard(content, history, s.context_variables, emit)

        if confirmed:
            s.context_variables.update(confirmed)
            # Always emit s.to_dict() for phase_complete so the frontend can
            # safely setSession(event.data) without losing fields like playlist.
            await emit({"type": "phase_complete", "phase": "genre", "data": s.to_dict()})

            # Verify the confirmed genre actually has tracks before invoking
            # the Planner — otherwise the LLM ends up calling get_catalog and
            # producing a vague "issue accessing the catalog" message.
            try:
                await asyncio.to_thread(pipeline.check_catalog, confirmed["genre"])
            except pipeline.CatalogUnavailable as exc:
                await emit({"type": "error", "message": str(exc)})
                s.phase = "init"
                return

            # ── Planner (auto-starts after genre confirmation) ──
            s.phase = "planning"
            await emit({"type": "phase_start", "phase": "planning"})
            memory = await pipeline.load_memory(confirmed["genre"], s.context_variables)
            await pipeline.phase_plan(s.context_variables, emit, memory)

            s.phase = "checkpoint1"
            await emit({"type": "phase_complete", "phase": "planning", "data": s.to_dict()})
        else:
            # Distinguish "agent is still asking" from "agent gave up". On
            # in-progress turns the LLM is politely asking "Is this correct?"
            # and the user just needs to reply — emitting an error banner
            # next to that question is purely cosmetic noise. See issue #23.
            if _should_emit_genre_error(history):
                await emit({"type": "error", "message": "Could not confirm genre — please start a new session."})
                s.phase = "init"
            # Otherwise, the agent is still asking a question — keep
            # s.phase = "genre" so the user's next message routes through
            # this handler again. No error event.

    # ── Checkpoint 1 — user approves playlist → run Critic ──────
    elif msg_type == "checkpoint_approve" and s.phase == "checkpoint1":
        try:
            await asyncio.to_thread(pipeline.check_catalog, s.context_variables.get("genre"))
        except pipeline.CatalogUnavailable as exc:
            await emit({"type": "error", "message": str(exc)})
            return
        s.phase = "critique"
        await emit({"type": "phase_start", "phase": "critique"})
        memory = await pipeline.load_memory(s.context_variables.get("genre", ""), s.context_variables)
        verdict, problems, structured = await pipeline.phase_critique(s.context_variables, emit, memory)

        s.critic_verdict = verdict
        s.critic_problems = problems
        s.structured_problems = structured
        s.phase = "checkpoint2"
        await emit({"type": "phase_complete", "phase": "critique", "data": s.to_dict()})

    # ── Checkpoint 2 — user proceeds to Editor ───────────────────
    elif msg_type == "checkpoint2_approve" and s.phase == "checkpoint2":
        s.phase = "editing"
        s.messages.setdefault("editor", [])
        await emit({"type": "phase_start", "phase": "editing"})
        await emit({"type": "phase_complete", "phase": "checkpoint2", "data": s.to_dict()})

    # ── Editor command ────────────────────────────────────────────
    elif msg_type == "editor_command" and s.phase == "editing":
        try:
            await asyncio.to_thread(pipeline.check_catalog, s.context_variables.get("genre"))
        except pipeline.CatalogUnavailable as exc:
            await emit({"type": "error", "message": str(exc)})
            return
        history = s.messages.setdefault("editor", [])
        await pipeline.phase_editor(content, history, s.context_variables, emit)

        last_build = s.context_variables.get("last_build")
        if last_build:
            s.session_name = last_build
            s.phase = "validating"
            await emit({"type": "phase_start", "phase": "validating"})
            v_status, v_issues = await pipeline.phase_validate(last_build, s.context_variables, emit)
            s.validator_status = v_status
            s.validator_issues = v_issues
            s.phase = "rating"
            await emit({"type": "phase_complete", "phase": "validating", "data": s.to_dict()})
        else:
            await emit({"type": "phase_complete", "phase": "editor_turn", "data": s.to_dict()})

    # ── State sync ────────────────────────────────────────────────
    elif msg_type == "get_state":
        await emit({"type": "state", "data": s.to_dict()})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(session_id: str, user: dict):
    s = store.get(session_id)
    if not s or s.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")
    return s
