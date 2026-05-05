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


class EditorCommandRequest(BaseModel):
    message: str


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
