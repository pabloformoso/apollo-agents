"""Tests for the v3.6.4 textual-tool-call shim.

Small local models (gemma-4-e4b via LM Studio, observed live 2026-07-12)
answer tool-shaped turns with the literal text ``pick_next_track(...)``
and no structured ``tool_calls``. ``parse_textual_tool_call`` recovers
those; the ollama/openai agent loops execute the recovered call and
keep looping. Strictness matters as much as recovery: prose that merely
mentions tool syntax must NOT trigger execution.
"""
from __future__ import annotations

import json

import pytest

from agent.run import parse_textual_tool_call

TOOLS = {"extend_set", "pick_next_track", "emit_chat"}


# ---------------------------------------------------------------------------
# parse_textual_tool_call — recovery cases (all observed in live logs)
# ---------------------------------------------------------------------------

def test_parses_bare_call_with_mixed_literal_kwargs():
    got = parse_textual_tool_call(
        'pick_next_track(bpm_min=75, bpm_max=80, key="11B", mood="Deep focus piano")',
        TOOLS,
    )
    assert got == (
        "pick_next_track",
        {"bpm_min": 75, "bpm_max": 80, "key": "11B", "mood": "Deep focus piano"},
    )


def test_parses_emit_chat_with_awkward_text():
    got = parse_textual_tool_call(
        'emit_chat(text="Getting ready to drop the low end right here ? watch for it")',
        TOOLS,
    )
    assert got is not None and got[0] == "emit_chat"
    assert "low end" in got[1]["text"]


def test_parses_call_wrapped_in_inline_backticks():
    got = parse_textual_tool_call("`extend_set(track_id='abc-123')`", TOOLS)
    assert got == ("extend_set", {"track_id": "abc-123"})


def test_parses_call_in_fenced_code_block():
    text = '```python\nextend_set(track_id="abc-123")\n```'
    assert parse_textual_tool_call(text, TOOLS) == (
        "extend_set",
        {"track_id": "abc-123"},
    )


def test_parses_call_with_trailing_sentence_period():
    got = parse_textual_tool_call('extend_set(track_id="abc").', TOOLS)
    assert got == ("extend_set", {"track_id": "abc"})


def test_parses_surrounding_whitespace_and_newlines():
    got = parse_textual_tool_call('\n  extend_set(track_id="abc")\n', TOOLS)
    assert got == ("extend_set", {"track_id": "abc"})


def test_boolean_and_none_literals_survive():
    got = parse_textual_tool_call(
        "pick_next_track(bpm_min=70, prefer_fresh=True, key=None)", TOOLS
    )
    assert got == (
        "pick_next_track",
        {"bpm_min": 70, "prefer_fresh": True, "key": None},
    )


# ---------------------------------------------------------------------------
# parse_textual_tool_call — strictness (must NOT fire)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "(Keeping the flow steady.)",  # stage direction, observed constantly
        "(Let the groove ride.)",
        "I could call extend_set(track_id='x') here but I'll wait.",  # mid-prose
        "unknown_tool(track_id='x')",  # not a registered tool
        "extend_set('positional-id')",  # positional args are ambiguous
        "extend_set(track_id=get_id())",  # non-literal value
        "extend_set(**kwargs)",  # splat
        "extend_set(track_id='a'); emit_chat(text='b')",  # two statements
        "Plain sentence with no tool syntax at all.",
    ],
)
def test_refuses_non_calls_and_ambiguous_shapes(text):
    assert parse_textual_tool_call(text, TOOLS) is None


# ---------------------------------------------------------------------------
# Sync ollama loop integration — the shim executes and the loop continues
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, content: str | None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResponse:
    def __init__(self, msg):
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._scripted.pop(0))


class _FakeOpenAI:
    last_instance = None

    def __init__(self, *args, **kwargs):
        _FakeOpenAI.last_instance = self
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(_FakeOpenAI.scripted)

    scripted: list = []


def test_ollama_loop_executes_textualized_call_and_continues(monkeypatch):
    """Turn 1 returns the call as prose → shim executes the real tool and
    loops; turn 2 returns normal text → final answer. The transcript must
    contain a protocol-valid synthetic tool_calls pair."""
    import agent.run as run_mod

    executed: list = []

    def extend_set(track_id: str, context_variables: dict) -> str:
        executed.append(track_id)
        return f"Appended '{track_id}'."

    _FakeOpenAI.scripted = [
        _FakeMsg('extend_set(track_id="lofi-x-1")'),
        _FakeMsg("Done, queued it."),
    ]
    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "OpenAI", _FakeOpenAI)

    messages: list[dict] = [{"role": "user", "content": "playlist running low"}]
    final = run_mod._run_agent_ollama(
        "system", [extend_set], {"extend_set": extend_set}, messages, {}, 5
    )

    assert executed == ["lofi-x-1"]
    assert final == "Done, queued it."
    # Transcript: synthetic assistant tool_calls + matching tool result.
    assistant = next(m for m in messages if m.get("tool_calls"))
    tc = assistant["tool_calls"][0]
    assert tc["function"]["name"] == "extend_set"
    assert json.loads(tc["function"]["arguments"]) == {"track_id": "lofi-x-1"}
    tool_msg = next(m for m in messages if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == tc["id"]


def test_ollama_loop_plain_text_still_terminates(monkeypatch):
    """A normal text answer (no tool syntax) must break the loop exactly
    as before — the shim must not add turns."""
    import agent.run as run_mod

    _FakeOpenAI.scripted = [_FakeMsg("(Keeping the flow steady.)")]
    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "OpenAI", _FakeOpenAI)

    final = run_mod._run_agent_ollama(
        "system", [], {}, [{"role": "user", "content": "hi"}], {}, 5
    )
    assert final == "(Keeping the flow steady.)"
    assert len(_FakeOpenAI.last_instance.chat.completions.calls) == 1


def test_ollama_loop_shim_respects_max_turns(monkeypatch):
    """A model that textualizes on EVERY turn must still terminate at
    max_turns instead of looping forever."""
    import agent.run as run_mod

    def emit_chat(text: str, context_variables: dict) -> str:
        return "ok"

    _FakeOpenAI.scripted = [
        _FakeMsg('emit_chat(text="a")'),
        _FakeMsg('emit_chat(text="b")'),
        _FakeMsg('emit_chat(text="c")'),
    ]
    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "OpenAI", _FakeOpenAI)

    run_mod._run_agent_ollama(
        "system", [emit_chat], {"emit_chat": emit_chat},
        [{"role": "user", "content": "hi"}], {}, 3,
    )
    assert len(_FakeOpenAI.last_instance.chat.completions.calls) == 3


# ---------------------------------------------------------------------------
# Async web streaming loop integration
# ---------------------------------------------------------------------------

class _FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChunk:
    def __init__(self, delta):
        self.choices = [type("C", (), {"delta": delta})()]


class _FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _FakeAsyncCompletions:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.n_calls = 0

    async def create(self, **kwargs):
        self.n_calls += 1
        return _FakeAsyncStream(self._scripted.pop(0))


class _FakeAsyncOpenAI:
    last_instance = None
    scripted: list = []

    def __init__(self, *args, **kwargs):
        _FakeAsyncOpenAI.last_instance = self
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeAsyncCompletions(_FakeAsyncOpenAI.scripted)


def test_streaming_loop_recovers_textualized_call(monkeypatch):
    import asyncio

    from web.backend import pipeline as pl

    executed: list = []

    def pick_next_track(bpm_min: int, context_variables: dict) -> str:
        executed.append(bpm_min)
        return "id=lofi-pick-1"

    # Turn 1 streams the textualized call; turn 2 streams a normal reply.
    _FakeAsyncOpenAI.scripted = [
        [_FakeChunk(_FakeDelta(content="pick_next_track(bpm_min=75)"))],
        [_FakeChunk(_FakeDelta(content="Queued the pick."))],
    ]
    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "AsyncOpenAI", _FakeAsyncOpenAI)

    emitted: list[dict] = []

    async def emit(ev: dict) -> None:
        emitted.append(ev)

    async def _drive() -> str:
        return await pl._run_openai_streaming(
            "system", [pick_next_track],
            [{"role": "user", "content": "running low"}],
            {}, emit, 5, base_url="http://fake:1234/v1",
        )

    final = asyncio.run(_drive())

    assert executed == [75]
    assert final == "Queued the pick."
    types = [e.get("type") for e in emitted]
    assert "tool_call" in types
    assert "tool_result" in types
    tc = next(e for e in emitted if e.get("type") == "tool_call")
    assert tc["name"] == "pick_next_track"
    assert tc["input"] == {"bpm_min": 75}
