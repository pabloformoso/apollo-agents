"""Session-eligibility rules for catalog tracks.

v3.9.1 — single source of truth for which catalog tracks may be
SELECTED into a session (offline render, planner playlist, live picks,
endless continuations).

Motivation (observed live 2026-08-03): the aural batch contains pieces
of 35–120 s. In a session they read as tracks that "cut off" — with a
24 s drift crossfade a 64 s piece is audible for ~35 s. The rule: any
track shorter than MIN_TRACK_DURATION_SEC (default 120 s) is not
eligible for sessions. It stays in the catalog — stream lookups by id,
ratings, artwork and the web library are unaffected; only the
SELECTION paths filter.

Deliberately NOT enforced on manual UI actions (drag-reorder / swap in
the web queue): an explicit human choice overrides the screen.

Override per environment: ``APOLLO_MIN_TRACK_DURATION_SEC`` (seconds;
0 disables the screen entirely).
"""
from __future__ import annotations

import os


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


MIN_TRACK_DURATION_SEC = _env_float("APOLLO_MIN_TRACK_DURATION_SEC", 120.0)


def is_session_eligible(track: dict) -> bool:
    """True when ``track`` may be selected into a session.

    A track with unknown duration (``duration_sec`` missing/None) stays
    eligible — legacy catalog entries predate duration backfill and a
    silent genre shrink would be worse than an occasional short piece;
    run ``--fix-incomplete`` to backfill and make the screen bite.
    """
    dur = track.get("duration_sec")
    if dur is None:
        return True
    try:
        return float(dur) >= MIN_TRACK_DURATION_SEC
    except (TypeError, ValueError):
        return True


def filter_session_eligible(tracks: list[dict]) -> list[dict]:
    """Return only the session-eligible tracks, order preserved."""
    return [t for t in tracks if is_session_eligible(t)]


def ineligibility_reason(track: dict) -> str | None:
    """Human/LLM-readable reason a track fails the screen, or None if it passes.

    Used by agent tools (extend_set / swap_track) to coach the model
    back to ``pick_next_track`` instead of silently dropping its choice.
    """
    if is_session_eligible(track):
        return None
    dur = track.get("duration_sec")
    return (
        f"track is {float(dur):.0f}s long — shorter than the "
        f"{MIN_TRACK_DURATION_SEC:.0f}s minimum for session eligibility"
    )
