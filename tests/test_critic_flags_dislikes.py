"""Tests for v2.3.2 — Critic deterministic dislike-flagging post-process.

`phase_critique` now appends a structured_problem for every playlist track
the user has rated ★1 or ★2, regardless of what the LLM said. This is
implemented as the pure helper `_append_dislike_problems` in pipeline.py
plus a call site in `phase_critique`.
"""

from __future__ import annotations

import asyncio


# ---------------------------------------------------------------------------
# Helper unit-tests on the pure function (no pipeline / async needed).
# ---------------------------------------------------------------------------


def test_append_dislike_problems_appends_one_per_low_rated_track():
    from web.backend.pipeline import _append_dislike_problems

    playlist = [
        {"id": "track-a", "display_name": "Alpha"},
        {"id": "track-b", "display_name": "Beta"},
        {"id": "track-c", "display_name": "Gamma"},
    ]
    dislike_ids = {"track-a", "track-c"}
    ratings = {"track-a": 1, "track-b": 5, "track-c": 2}

    out = _append_dislike_problems(playlist, dislike_ids, ratings, [])
    assert len(out) == 2
    texts = [p["text"] for p in out]
    assert any("Alpha" in t and "★1" in t for t in texts)
    assert any("Gamma" in t and "★2" in t for t in texts)
    # pos_from / pos_to are 1-indexed.
    pos_pairs = [(p["pos_from"], p["pos_to"]) for p in out]
    assert (1, 1) in pos_pairs
    assert (3, 3) in pos_pairs


def test_append_dislike_problems_preserves_existing_problems():
    from web.backend.pipeline import _append_dislike_problems

    playlist = [
        {"id": "track-a", "display_name": "Alpha"},
        {"id": "track-b", "display_name": "Beta"},
    ]
    existing = [{"pos_from": 1, "pos_to": 2, "key_pair": "1A→3A", "bpm_diff": 12, "text": "BPM gap"}]
    out = _append_dislike_problems(playlist, {"track-a"}, {"track-a": 1}, existing)
    assert len(out) == 2
    assert out[0] == existing[0]
    assert "Alpha" in out[1]["text"]


def test_append_dislike_problems_no_dislikes_returns_baseline():
    from web.backend.pipeline import _append_dislike_problems

    playlist = [{"id": "track-a", "display_name": "Alpha"}]
    existing = [{"pos_from": 1, "pos_to": 1, "key_pair": "", "bpm_diff": 0, "text": "x"}]
    out = _append_dislike_problems(playlist, set(), {}, existing)
    assert out == existing


def test_append_dislike_problems_skips_tracks_outside_dislike_set():
    from web.backend.pipeline import _append_dislike_problems

    playlist = [
        {"id": "track-a", "display_name": "Alpha"},
        {"id": "track-b", "display_name": "Beta"},
    ]
    # track-b has rating 3 (neutral) — not in dislike_ids → not flagged.
    out = _append_dislike_problems(playlist, {"track-a"}, {"track-a": 1, "track-b": 3}, [])
    assert len(out) == 1
    assert "Alpha" in out[0]["text"]


def test_append_dislike_problems_uses_track_id_when_display_name_missing():
    """Defensive: a stripped catalog entry without display_name should still produce a usable message."""
    from web.backend.pipeline import _append_dislike_problems

    playlist = [{"id": "track-x"}]
    out = _append_dislike_problems(playlist, {"track-x"}, {"track-x": 2}, [])
    assert len(out) == 1
    assert "track-x" in out[0]["text"]


# ---------------------------------------------------------------------------
# phase_critique integration — combines LLM problems and rating problems.
# ---------------------------------------------------------------------------


async def _noop_emit(_event: dict) -> None:
    pass


def _capture_runner(verdict_text: str):
    """Build a fake run_agent_streaming that returns a hard-coded verdict."""
    async def _fake(system, tool_fns, messages, ctx, emit, max_turns=20):
        return verdict_text
    return _fake


def test_phase_critique_appends_dislike_problems_when_dislikes_present(monkeypatch):
    """Playlist with two ★1 tracks → structured_problems contains 2 dislike entries."""
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    monkeypatch.setattr(
        pipeline,
        "run_agent_streaming",
        _capture_runner("PROBLEMS: none\nVERDICT: APPROVED\n"),
    )

    ctx = {
        "playlist": [
            {"id": "bad-1", "display_name": "Bad One", "bpm": 120, "camelot_key": "1A"},
            {"id": "ok-1",  "display_name": "Ok",      "bpm": 122, "camelot_key": "2A"},
            {"id": "bad-2", "display_name": "Bad Two", "bpm": 124, "camelot_key": "3A"},
        ],
        "dislike_ids": {"bad-1", "bad-2"},
        "user_ratings": {"bad-1": 1, "bad-2": 2, "ok-1": 4},
    }

    verdict, problems, structured = asyncio.run(
        pipeline.phase_critique(ctx, _noop_emit, memory_summary="")
    )

    # LLM said APPROVED with no problems, but the dislike pass should have
    # added two structured problems.
    assert len(structured) == 2
    texts = [p["text"] for p in structured]
    assert any("Bad One" in t for t in texts)
    assert any("Bad Two" in t for t in texts)


def test_phase_critique_combines_llm_and_rating_problems(monkeypatch):
    """LLM returns 1 problem, dislike pass adds 1 → total 2."""
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    monkeypatch.setattr(
        pipeline,
        "run_agent_streaming",
        _capture_runner(
            "PROBLEMS:\n- [pos 1→2] BPM gap too wide — fix: insert bridge\n\n"
            "VERDICT: NEEDS_FIXES\n"
        ),
    )

    ctx = {
        "playlist": [
            {"id": "bad-1", "display_name": "Bad", "bpm": 120, "camelot_key": "1A"},
            {"id": "ok-1",  "display_name": "Ok",  "bpm": 140, "camelot_key": "2A"},
        ],
        "dislike_ids": {"bad-1"},
        "user_ratings": {"bad-1": 1},
    }

    verdict, problems, structured = asyncio.run(
        pipeline.phase_critique(ctx, _noop_emit, memory_summary="")
    )
    assert verdict == "NEEDS_FIXES"
    assert len(structured) == 2
    assert any("BPM gap" in p["text"] for p in structured)
    assert any("Bad" in p["text"] and "★1" in p["text"] for p in structured)


def test_phase_critique_no_extra_problems_without_dislikes(monkeypatch):
    """No dislike_ids → output equal to baseline (just whatever the LLM produced)."""
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_USER_CONTEXT_CACHE", {})
    monkeypatch.setattr(
        pipeline,
        "run_agent_streaming",
        _capture_runner("PROBLEMS: none\nVERDICT: APPROVED\n"),
    )

    ctx = {
        "playlist": [
            {"id": "ok-1", "display_name": "Ok", "bpm": 120, "camelot_key": "1A"},
        ],
        # no dislike_ids, no user_ratings — anonymous CLI-style ctx
    }
    verdict, problems, structured = asyncio.run(
        pipeline.phase_critique(ctx, _noop_emit, memory_summary="")
    )
    assert verdict == "APPROVED"
    assert structured == []
