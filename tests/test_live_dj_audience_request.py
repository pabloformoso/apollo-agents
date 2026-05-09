"""v2.5.2 — audience_request_batch flow through the LiveDJ async loop.

We mock the LLM so the test is deterministic. The mock decides whether
to call ``emit_chat`` (the polite-rejection path) or ``queue_swap`` (the
acceptance path) based on the request text.

The pipeline-level ``_live_relay`` already converts raw ``user_msg``
items into batched ``audience_request_batch`` events. These tests poke
the agent loop directly with a pre-batched event so the assertion is
about the agent's reaction, not the batching logic (covered separately
by ``test_perception_buffer.py``).
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
    engine.queue_swap.return_value = "swapped"
    return engine


@pytest.mark.asyncio
async def test_audience_request_reaches_agent_with_batch_event(monkeypatch):
    """The agent's turn must include the batched requests so the prompt
    can decide rejection vs acceptance."""
    captured: dict = {}

    async def fake_runner(system, tools, messages, ctx, emit, max_turns=5):
        captured["messages"] = messages
        return "I hear you."

    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "run_agent_streaming", fake_runner)

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(payload: dict) -> None:
        pass

    await queue.put(
        {
            "type": "audience_request_batch",
            "requests": [
                {"text": "play more techno"},
                {"text": "drop the bass"},
            ],
        }
    )

    engine = _make_engine()
    await live_dj.run_live_session_async(
        playlist=[{"id": "T1"}],
        context_variables={},
        engine=engine,
        emit=emit,
        command_queue=queue,
        max_idle_loops=2,
    )

    last_user = next(
        (m for m in reversed(captured["messages"]) if m["role"] == "user"),
        None,
    )
    assert last_user is not None
    assert "AUDIENCE_REQUEST_BATCH" in last_user["content"]
    assert "play more techno" in last_user["content"]
    assert "drop the bass" in last_user["content"]


@pytest.mark.asyncio
async def test_audience_request_rejection_via_emit_chat(monkeypatch):
    """A "polite reject" mock LLM must produce a ``dj_chat`` WS event but
    NOT call any engine action — proving the agent can acknowledge a
    request without committing to it."""

    async def fake_runner(system, tools, messages, ctx, emit, max_turns=5):
        # Simulate the LLM calling emit_chat directly. We invoke the tool
        # function the same way run_agent_streaming would.
        from agent.tools import emit_chat

        emit_chat("Heard you — staying the course.", ctx)
        return "Heard."

    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "run_agent_streaming", fake_runner)

    queue: asyncio.Queue = asyncio.Queue()
    emitted: list[dict] = []

    async def emit(payload: dict) -> None:
        emitted.append(payload)

    await queue.put(
        {
            "type": "audience_request_batch",
            "requests": [{"text": "anything you got that slaps?"}],
        }
    )

    engine = _make_engine()
    ctx: dict = {"_event_emitter": emit}
    await live_dj.run_live_session_async(
        playlist=[{"id": "T1"}],
        context_variables=ctx,
        engine=engine,
        emit=emit,
        command_queue=queue,
        max_idle_loops=2,
    )

    types = [e.get("type") for e in emitted]
    assert "dj_chat" in types
    chat = next(e for e in emitted if e.get("type") == "dj_chat")
    assert "staying the course" in chat["text"].lower()
    # Engine actions must NOT have been called.
    engine.queue_swap.assert_not_called()
    engine.skip_track.assert_not_called()
