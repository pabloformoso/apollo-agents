"""v2.5.2 — environment_changed event flow through the LiveDJ async loop.

We don't exercise the LLM (it's stubbed). We just verify:
  - The async loop accepts an ``environment_changed`` event.
  - The formatted turn surfaces the event so the system prompt has
    something to react to.
  - The mocked LLM is called with messages that include the
    ENVIRONMENT_CHANGED line.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent import live_dj


def _make_engine():
    engine = MagicMock()
    engine.get_state.return_value = {
        "state": "playing",
        "position_sec": 30.0,
        "current_track": {"display_name": "T1", "bpm": 124.0, "camelot_key": "8A", "hot_cues": []},
        "next_track": {"display_name": "T2", "bpm": 126.0, "camelot_key": "9A", "hot_cues": []},
        "seconds_to_crossfade": 60.0,
        "playlist_remaining": 1,
    }
    return engine


@pytest.mark.asyncio
async def test_environment_changed_triggers_llm_turn(monkeypatch):
    """An ``environment_changed`` event in the queue must cause the agent
    loop to call ``run_agent_streaming`` with a turn that mentions the
    event."""
    captured: dict = {}

    async def fake_runner(system, tools, messages, ctx, emit, max_turns=5):
        captured["messages"] = messages
        captured["ctx"] = ctx
        return "Lifting the energy."

    # The async loop imports run_agent_streaming via the web pipeline —
    # patch it where it's looked up.
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "run_agent_streaming", fake_runner)

    queue: asyncio.Queue = asyncio.Queue()
    emitted: list[dict] = []

    async def emit(payload: dict) -> None:
        emitted.append(payload)

    # Push the synthetic event. The agent loop processes it on the first
    # turn; ``max_idle_loops=2`` lets the loop exit cleanly afterwards
    # (no further events arrive in the meantime).
    await queue.put(
        {
            "type": "environment_changed",
            "rms_db_delta": 8.5,
            "rms_db_mean": -45.0,
            "voice_likelihood": None,
        }
    )

    engine = _make_engine()
    ctx: dict = {}
    await live_dj.run_live_session_async(
        playlist=[{"id": "T1"}, {"id": "T2"}],
        context_variables=ctx,
        engine=engine,
        emit=emit,
        command_queue=queue,
        max_idle_loops=2,
    )

    # The runner must have been called once and seen the event in its turn.
    assert "messages" in captured
    last_user = next(
        (m for m in reversed(captured["messages"]) if m["role"] == "user"),
        None,
    )
    assert last_user is not None
    assert "ENVIRONMENT_CHANGED" in last_user["content"]
    assert "+8.5" in last_user["content"] or "8.5" in last_user["content"]


@pytest.mark.asyncio
async def test_environment_changed_emits_assistant_chat_event(monkeypatch):
    """The assistant's reply text propagates back over the WS as a
    ``live_message`` event so the UI's command log can display it."""

    async def fake_runner(system, tools, messages, ctx, emit, max_turns=5):
        return "Lifting the energy."

    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "run_agent_streaming", fake_runner)

    queue: asyncio.Queue = asyncio.Queue()
    emitted: list[dict] = []

    async def emit(payload: dict) -> None:
        emitted.append(payload)

    await queue.put({"type": "environment_changed", "rms_db_delta": 8.0})

    engine = _make_engine()
    await live_dj.run_live_session_async(
        playlist=[{"id": "T1"}],
        context_variables={},
        engine=engine,
        emit=emit,
        command_queue=queue,
        max_idle_loops=2,
    )

    types = [e.get("type") for e in emitted]
    assert "live_message" in types
    msg = next(e for e in emitted if e.get("type") == "live_message")
    assert msg["role"] == "assistant"
    assert "energy" in msg["content"]
