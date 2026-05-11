"""Pydantic request / response models."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class GenreIntentRequest(BaseModel):
    message: str


class CheckpointRequest(BaseModel):
    feedback: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Body for ``POST /api/sessions``.

    v2.6.0 — when ``brief`` is provided, the backend parses it via
    ``brief_parser`` and kicks off ``run_planning_from_brief`` as a
    background task. Legacy clients omit the body entirely and get an
    empty session back (backwards-compatible with the v2.5.x flow).
    """
    brief: Optional[str] = None
    environment: Optional[str] = None


class EditorCommandRequest(BaseModel):
    message: str


class SessionTracksReorder(BaseModel):
    """Body for ``POST /api/sessions/{id}/tracks/reorder`` (v2.6.0)."""
    order: list[int] = Field(..., min_length=1)


class SessionTrackInsert(BaseModel):
    """Body for ``POST /api/sessions/{id}/tracks/insert`` (v2.6.0)."""
    at: int = Field(ge=0)
    track_id: str = Field(..., min_length=1)


class SessionEditorCommand(BaseModel):
    """Body for ``POST /api/sessions/{id}/editor_command`` (v2.6.0 SSE)."""
    text: str = Field(..., min_length=1)


class RatingRequest(BaseModel):
    rating: int  # 1–5
    notes: Optional[str] = None
    transition_ratings: Optional[list[dict]] = None


# ---------------------------------------------------------------------------
# Playlists (v2.2.1)
# ---------------------------------------------------------------------------

class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class PlaylistRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class PlaylistAddTracks(BaseModel):
    track_ids: list[str] = Field(..., min_length=1)


class PlaylistReorder(BaseModel):
    track_ids: list[str] = Field(..., min_length=0)


# ---------------------------------------------------------------------------
# Ratings (v2.2.2)
# ---------------------------------------------------------------------------

class RatingUpdate(BaseModel):
    """Body for PUT /api/tracks/{track_id}/rating — single 1–5 score."""
    rating: int = Field(ge=1, le=5)
