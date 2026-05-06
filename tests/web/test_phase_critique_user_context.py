"""Tests for v2.3.2 — `phase_critique` hydrates user context.

The Critic phase now mirrors the Planner: when `ctx["user_id"]` is set,
favorite_ids / dislike_ids / user_ratings / user_playlists land in ctx
before the LLM is invoked, so its tool calls (and the deterministic
dislike-flagging post-process) have data to work with.
"""

from __future__ import annotations

import asyncio


async def _noop_emit(_event: dict) -> None:
    pass


def _capture_runner(text: str = "PROBLEMS: none\nVERDICT: APPROVED\n"):
    async def _fake(system, tool_fns, messages, ctx, emit, max_turns=20):
        return text
    return _fake


def test_phase_critique_hydrates_user_context_when_user_id_present(tmp_db, monkeypatch):
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("critic_user", "c@test.io", "hash")
    db.upsert_track_rating(user_id, "fav-1", 5)
    db.upsert_track_rating(user_id, "fav-2", 4)
    db.upsert_track_rating(user_id, "bad-1", 1)
    db.create_playlist(user_id, "Critic Playlist")

    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())

    ctx = {
        "user_id": user_id,
        "playlist": [{"id": "fav-1", "display_name": "Fav One"}],
    }
    asyncio.run(pipeline.phase_critique(ctx, _noop_emit, memory_summary=""))

    assert ctx["favorite_ids"] == {"fav-1", "fav-2"}
    assert ctx["dislike_ids"] == {"bad-1"}
    assert "user_ratings" in ctx
    assert "user_playlists" in ctx


def test_phase_critique_skips_hydration_without_user_id(monkeypatch):
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())

    ctx = {"playlist": [{"id": "x", "display_name": "X"}]}
    asyncio.run(pipeline.phase_critique(ctx, _noop_emit, memory_summary=""))

    assert "favorite_ids" not in ctx
    assert "dislike_ids" not in ctx
    assert "user_ratings" not in ctx


def test_phase_critique_idempotent_when_already_hydrated(tmp_db, monkeypatch):
    """If ctx already has favorite_ids (e.g. phase_plan ran first), the
    helper short-circuits and doesn't re-query the DB."""
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("warm_user", "w@test.io", "hash")
    db.upsert_track_rating(user_id, "fav-real", 5)

    # Pre-populate ctx as if phase_plan ran already with stale-but-explicit values.
    ctx = {
        "user_id": user_id,
        "playlist": [],
        "favorite_ids": {"prefilled-fav"},
        "dislike_ids": set(),
        "user_ratings": {"prefilled-fav": 5},
        "user_playlists": [],
    }
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())
    asyncio.run(pipeline.phase_critique(ctx, _noop_emit, memory_summary=""))

    # Idempotent: existing ctx not overwritten by a fresh DB read.
    assert ctx["favorite_ids"] == {"prefilled-fav"}
