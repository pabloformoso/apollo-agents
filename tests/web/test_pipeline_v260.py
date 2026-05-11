"""Unit tests for the v2.6.0 pieces of ``web.backend.pipeline`` —
``compute_set_health`` (pure) and ``run_planning_from_brief`` (async
coroutine that auto-chains plan + critique). The full pipeline phases
are stubbed via ``mock_pipeline`` so this stays a unit test, not an
LLM integration."""
from __future__ import annotations

import asyncio

import pytest

from web.backend import pipeline
from web.backend.session_store import Session


# ─── compute_set_health ──────────────────────────────────────────────


def test_set_health_full_for_zero_problems():
    assert pipeline.compute_set_health([]) == 100
    assert pipeline.compute_set_health(None) == 100


def test_set_health_subtracts_six_per_problem():
    assert pipeline.compute_set_health([{}]) == 94
    assert pipeline.compute_set_health([{}, {}, {}]) == 82
    # 17 problems → 100 - 102 → clamped to 0
    assert pipeline.compute_set_health([{}] * 17) == 0


def test_set_health_never_goes_below_zero():
    # 50 problems would naively be -200 — must clamp to 0.
    assert pipeline.compute_set_health([{}] * 50) == 0


# ─── run_planning_from_brief ─────────────────────────────────────────


@pytest.fixture
def emitted(monkeypatch):
    """Capture every event emitted by the bridge so assertions can
    inspect the phase-progression sequence."""
    return []


def _make_session(brief: str = "30 min lofi for a rainy garden") -> Session:
    s = Session("sess-test", user_id=1)
    s.context_variables["brief_text"] = brief
    return s


async def test_run_planning_from_brief_happy_path(mock_pipeline, emitted):
    """When the parser pinned a valid genre, the bridge skips
    phase_genre_guard and chains plan → critique → checkpoint2."""
    s = _make_session()
    s.context_variables["genre"] = "lofi - ambient"

    async def emit(data):
        emitted.append(data)

    await pipeline.run_planning_from_brief(s, emit)

    assert s.phase == "checkpoint2"
    assert s.context_variables.get("playlist")  # fake_plan populated it
    assert s.critic_verdict == "APPROVED"
    assert s.set_health == 100

    # Bridge emits at minimum: phase_start planning + phase_complete planning
    # + phase_start critique + phase_complete critique.
    types = [(e.get("type"), e.get("phase")) for e in emitted]
    assert ("phase_start", "planning") in types
    assert ("phase_complete", "planning") in types
    assert ("phase_start", "critique") in types
    assert ("phase_complete", "critique") in types


async def test_run_planning_from_brief_falls_back_to_genre_guard(
    mock_pipeline, emitted,
):
    """If the parser couldn't pin a genre, the bridge calls
    phase_genre_guard with the brief text — which then resolves and
    drives plan + critique."""
    s = _make_session("a session of lofi tracks")
    # No `genre` in ctx → fallback path.

    async def emit(data):
        emitted.append(data)

    await pipeline.run_planning_from_brief(s, emit)

    assert s.phase == "checkpoint2"
    # The fake genre guard sets genre based on the brief content.
    assert s.context_variables.get("genre") == "lofi - ambient"
    # The bridge announces the genre confirmation.
    types = [(e.get("type"), e.get("phase")) for e in emitted]
    assert ("phase_complete", "genre") in types


async def test_run_planning_from_brief_stalls_on_unresolved_genre(
    mock_pipeline, emitted,
):
    """When the guard returns None (genre still ambiguous), the bridge
    leaves phase='genre' so the user's next message on /curate via the
    WS dispatcher resumes the chain."""
    # The fake guard returns None for "garbage" / "xyzzy" inputs.
    s = _make_session("xyzzy garbage")

    async def emit(data):
        emitted.append(data)

    await pipeline.run_planning_from_brief(s, emit)

    assert s.phase == "genre"
    assert not s.context_variables.get("playlist")
    # No phase_complete for planning/critique because we never got there.
    types = [(e.get("type"), e.get("phase")) for e in emitted]
    assert ("phase_complete", "planning") not in types


async def test_run_planning_from_brief_hydrates_user_id(mock_pipeline, emitted):
    s = _make_session()
    s.context_variables["genre"] = "techno"
    # user_id should be injected from session.user_id on first run.
    s.user_id = 42

    async def emit(data):
        emitted.append(data)

    await pipeline.run_planning_from_brief(s, emit)
    assert s.context_variables["user_id"] == 42
