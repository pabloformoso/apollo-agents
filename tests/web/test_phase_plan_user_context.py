"""Tests for v2.3.0 — `phase_plan` injects USER PREFERENCES into the prompt.

We mock `pipeline.run_agent_streaming` to capture the prompt the planner
would have sent to the LLM, then assert on its contents.
"""
from __future__ import annotations

import asyncio

import pytest


async def _noop_emit(_event: dict) -> None:
    pass


async def _noop_to_thread_load(*_args, **_kwargs):
    """Stand-in for asyncio.to_thread when pipeline pre-loads user_ctx."""
    return None


def _capture_runner(captured: list[str]):
    async def _fake(system, tool_fns, messages, ctx, emit, max_turns=20):
        # Concatenate the user prompt(s) so we can grep them.
        text = "\n\n".join(
            (m.get("content") if isinstance(m.get("content"), str) else "")
            for m in messages
        )
        captured.append(text)
        return "ok"
    return _fake


# ---------------------------------------------------------------------------
# user_id present → USER PREFERENCES block injected
# ---------------------------------------------------------------------------

def test_phase_plan_injects_user_summary_when_user_id_present(tmp_db, monkeypatch):
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("planner_user", "p@test.io", "hash")
    db.upsert_track_rating(user_id, "fav-techno-1", 5)
    db.upsert_track_rating(user_id, "fav-techno-2", 4)
    db.upsert_track_rating(user_id, "bad-track-1", 1)
    db.create_playlist(user_id, "Late Night")

    # Stub catalog so genre filter doesn't crash on missing tracks/.
    monkeypatch.setattr(
        pipeline,
        "load_catalog",
        lambda genre=None: (
            [
                {
                    "id": "fav-techno-1",
                    "display_name": "Fav Techno 1",
                    "genre_folder": "techno",
                    "genre": "techno",
                    "bpm": 130,
                    "camelot_key": "8A",
                },
            ],
            ["techno"],
        ),
    )

    captured: list[str] = []
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner(captured))

    ctx = {
        "user_id": user_id,
        "genre": "techno",
        "duration_min": 60,
        "mood": "dark",
    }

    asyncio.run(pipeline.phase_plan(ctx, _noop_emit, memory_summary=""))

    assert captured, "run_agent_streaming was not called"
    prompt = captured[0]
    assert "USER PREFERENCES" in prompt
    # Favorites section must include the rated track ids and counts.
    assert "fav-techno-1" in prompt or "Favorites" in prompt
    assert "Late Night" in prompt
    # Phase_plan must also have hydrated ctx for downstream consumers.
    assert ctx["favorite_ids"] == {"fav-techno-1", "fav-techno-2"}
    assert ctx["dislike_ids"] == {"bad-track-1"}
    assert "user_ratings" in ctx
    assert "user_playlists" in ctx


# ---------------------------------------------------------------------------
# user_id absent → no USER PREFERENCES block
# ---------------------------------------------------------------------------

def test_phase_plan_skips_user_summary_when_no_user_id(tmp_db, monkeypatch):
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    captured: list[str] = []
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner(captured))

    ctx = {"genre": "techno", "duration_min": 60, "mood": "dark"}  # no user_id
    asyncio.run(pipeline.phase_plan(ctx, _noop_emit, memory_summary=""))

    assert captured
    prompt = captured[0]
    assert "USER PREFERENCES" not in prompt
    # No user-context keys leak into ctx when there's no user_id.
    assert "favorite_ids" not in ctx
    assert "dislike_ids" not in ctx


def test_phase_plan_skips_user_summary_when_user_has_no_data(tmp_db, monkeypatch):
    """A logged-in user with no ratings/playlists should still produce a
    clean prompt — no empty 'USER PREFERENCES' block, no formatting glitches."""
    from web.backend import db, pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})

    user_id = db.create_user("blank_user", "b@test.io", "hash")

    captured: list[str] = []
    monkeypatch.setattr(pipeline, "run_agent_streaming", _capture_runner(captured))

    ctx = {
        "user_id": user_id,
        "genre": "techno",
        "duration_min": 60,
        "mood": "dark",
    }
    asyncio.run(pipeline.phase_plan(ctx, _noop_emit, memory_summary=""))

    assert captured
    prompt = captured[0]
    assert "USER PREFERENCES" not in prompt
    # ctx is still hydrated (just with empty sets), so v2.3.1 can rely on
    # `ctx.get("favorite_ids", set())` returning a real set.
    assert ctx["favorite_ids"] == set()
    assert ctx["dislike_ids"] == set()
