"""Tests for v2.3.2 — `phase_editor` hydrates user context.

Mirrors the phase_critique tests. The Editor's USER PREFERENCES SIGNAL
clause depends on favorite_ids / dislike_ids / user_ratings being in
ctx when the LLM tool-call loop runs.
"""

from __future__ import annotations

import asyncio


async def _noop_emit(_event: dict) -> None:
    pass


def _capture_runner(text: str = "ok"):
    async def _fake(system, tool_fns, messages, ctx, emit, max_turns=20):
        return text
    return _fake


def test_phase_editor_hydrates_user_context_when_user_id_present(tmp_db, monkeypatch):
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("editor_user", "e@test.io", "hash")
    db.upsert_track_rating(user_id, "fav-1", 5)
    db.upsert_track_rating(user_id, "fav-2", 4)
    db.upsert_track_rating(user_id, "bad-1", 1)
    db.create_playlist(user_id, "My Editor Set")

    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())

    ctx = {
        "user_id": user_id,
        "playlist": [{"id": "fav-1", "display_name": "Fav One"}],
    }
    history: list[dict] = []
    asyncio.run(pipeline.phase_editor("swap something", history, ctx, _noop_emit))

    assert ctx["favorite_ids"] == {"fav-1", "fav-2"}
    assert ctx["dislike_ids"] == {"bad-1"}
    assert "user_ratings" in ctx
    assert "user_playlists" in ctx


def test_phase_editor_skips_hydration_without_user_id(monkeypatch):
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())

    ctx = {"playlist": []}
    history: list[dict] = []
    asyncio.run(pipeline.phase_editor("hello", history, ctx, _noop_emit))

    assert "favorite_ids" not in ctx
    assert "dislike_ids" not in ctx


def test_phase_editor_idempotent_when_already_hydrated(tmp_db, monkeypatch):
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    user_id = db.create_user("prewarm_editor", "p@test.io", "hash")
    db.upsert_track_rating(user_id, "fresh-fav", 5)

    ctx = {
        "user_id": user_id,
        "playlist": [],
        "favorite_ids": {"stale-fav"},
        "dislike_ids": set(),
        "user_ratings": {"stale-fav": 5},
        "user_playlists": [],
    }
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner())
    asyncio.run(pipeline.phase_editor("noop", [], ctx, _noop_emit))

    # Existing ctx values not overwritten — pipeline trusts the upstream phase.
    assert ctx["favorite_ids"] == {"stale-fav"}
