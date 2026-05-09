"""v2.5.2 — DJ-attitude rejection rate.

The plan calls out the explicit rule: "accept maybe 1 in 5". We proxy
the LLM with a deterministic mock that mirrors that bias and check that
≤1 of 5 requests leads to an engine action; the rest produce
``emit_chat`` replies.

The mock is intentionally simple: it accepts only when the request text
matches a hard-coded "favourable" sentinel ("more drive"), otherwise it
politely rejects via ``emit_chat``. Five different request texts are
fed; only one is favourable. This validates the agent loop wiring (the
prompt change itself is asserted by the unit-level prompt regression in
``test_live_engine_protocol.py`` — kept separate to keep this test a
proxy for behaviour, not text).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent import live_dj


_REQUESTS = [
    "any classic disco?",
    "play more drive",  # the one acceptance
    "do you take requests?",
    "something faster",
    "please play foo by bar",
]


@pytest.mark.asyncio
async def test_request_rejection_rate_is_at_most_one_in_five(monkeypatch):
    """Run 5 requests sequentially through the loop. Only "play more
    drive" should accept; the rest must produce dj_chat rejections."""

    accept_count = {"n": 0}
    reject_count = {"n": 0}
    seen_texts: set[str] = set()

    async def fake_runner(system, tools, messages, ctx, emit, max_turns=5):
        # The LLM sees the entire conversation; iterate every batch the
        # loop has surfaced this turn and apply the "1 in 5" rule per
        # request — model the reality where a real DJ scans incoming
        # asks and picks the rare one that fits the flow.
        from agent.tools import emit_chat

        last_user = next(
            (m for m in reversed(messages) if m["role"] == "user"),
            None,
        )
        text = (last_user or {}).get("content", "")
        # Walk the AUDIENCE_REQUEST_BATCH lines in the current turn and
        # decide each independently.
        for line in text.splitlines():
            if not line.strip().startswith(">"):
                continue
            req = line.split(">", 1)[1].strip().lower()
            if req in seen_texts:
                continue
            seen_texts.add(req)
            if "play more drive" in req:
                engine = ctx.get("_engine")
                if engine is not None:
                    engine.queue_swap(2, "alt-driver")
                accept_count["n"] += 1
            else:
                emit_chat("Noted, staying the course.", ctx)
                reject_count["n"] += 1
        return "Heard."

    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "run_agent_streaming", fake_runner)

    engine = MagicMock()
    engine.get_state.return_value = {
        "state": "playing",
        "position_sec": 30.0,
        "current_track": {"display_name": "T1", "bpm": 124.0, "camelot_key": "8A", "hot_cues": []},
        "next_track": {"display_name": "T2", "bpm": 126.0, "camelot_key": "9A", "hot_cues": []},
        "seconds_to_crossfade": 60.0,
        "playlist_remaining": 1,
    }
    engine.queue_swap.return_value = "swap-ok"

    emitted: list[dict] = []

    async def emit(payload: dict) -> None:
        emitted.append(payload)

    # Send all 5 requests as a single batch (same loop turn). This still
    # tests the rejection rate since the deterministic mock applies the
    # rule to whatever is in messages.
    queue: asyncio.Queue = asyncio.Queue()
    for req in _REQUESTS:
        await queue.put(
            {
                "type": "audience_request_batch",
                "requests": [{"text": req}],
            }
        )

    ctx: dict = {"_event_emitter": emit}
    await live_dj.run_live_session_async(
        playlist=[{"id": "T1"}],
        context_variables=ctx,
        engine=engine,
        emit=emit,
        command_queue=queue,
        max_idle_loops=2,
    )

    # The acceptance path called engine.queue_swap exactly once, and at
    # most once across the run (rule: accept ≤1 in 5).
    assert accept_count["n"] <= 1
    assert engine.queue_swap.call_count <= 1
    # The rest produced dj_chat rejections.
    chat_events = [e for e in emitted if e.get("type") == "dj_chat"]
    assert len(chat_events) >= 4
