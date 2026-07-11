"""C-2: slow plane. LLM transport is mocked — these tests exercise the
JSON extraction, validation, retry-once, and reject-and-hold contract."""

import json

import pytest

from agent.generative.mind import Mind, MindError, SYSTEM_PROMPT, _extract_json
from agent.generative.spec import PatternSpec

from tests.test_generative_spec import valid_spec_dict


def make_state() -> dict:
    return {"now_playing": "seed", "bars_elapsed": 8,
            "standing_intent": "darker", "recent_reasons": ["seed groove"]}


# --- _extract_json -------------------------------------------------------------

def test_extracts_bare_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extracts_fenced_json():
    assert _extract_json('Here you go:\n```json\n{"a": 1}\n```\nEnjoy!') == {"a": 1}


def test_extracts_json_with_surrounding_prose():
    assert _extract_json('Sure! {"a": {"b": 2}} — done.') == {"a": {"b": 2}}


@pytest.mark.parametrize("bad", ["no json here", '{"unbalanced": {', '{"bad": json}'])
def test_extract_rejects_garbage(bad):
    with pytest.raises(MindError):
        _extract_json(bad)


# --- Mind.next_spec -------------------------------------------------------------

def test_happy_path_returns_validated_spec():
    calls = []

    def llm(system, user):
        calls.append((system, user))
        return json.dumps(valid_spec_dict())

    spec = Mind(llm=llm).next_spec(make_state(), "darker")
    assert isinstance(spec, PatternSpec)
    assert len(calls) == 1
    assert calls[0][0] == SYSTEM_PROMPT
    assert "darker" in calls[0][1]
    assert "seed groove" in calls[0][1]  # state is serialized into the prompt


def test_retries_once_with_the_validation_error():
    replies = [json.dumps(valid_spec_dict(bpm=999)),  # invalid: bpm out of range
               json.dumps(valid_spec_dict())]
    prompts = []

    def llm(system, user):
        prompts.append(user)
        return replies[len(prompts) - 1]

    spec = Mind(llm=llm).next_spec(make_state(), "build")
    assert isinstance(spec, PatternSpec)
    assert len(prompts) == 2
    assert "rejected" in prompts[1] and "bpm" in prompts[1]


def test_two_failures_raise_mind_error():
    def llm(system, user):
        return "I would love to help but I cannot produce JSON today."

    with pytest.raises(MindError, match="failed twice"):
        Mind(llm=llm).next_spec(make_state(), "x")


def test_invalid_spec_twice_raises():
    def llm(system, user):
        return json.dumps(valid_spec_dict(key="Zmin"))

    with pytest.raises(MindError):
        Mind(llm=llm).next_spec(make_state(), "x")


def test_fenced_reply_accepted():
    def llm(system, user):
        return f"```json\n{json.dumps(valid_spec_dict())}\n```"

    assert isinstance(Mind(llm=llm).next_spec(make_state(), "x"), PatternSpec)


# --- v3.0 slice 2: genre packs reach the system prompt (M-6) --------------------

def test_genre_brief_lands_in_system_prompt():
    captured = {}

    def llm(system, user):
        captured["system"] = system
        return json.dumps(valid_spec_dict())

    Mind(llm=llm, genre="lofi").next_spec(make_state(), "x")
    assert "GENRE: lofi hip-hop" in captured["system"]
    assert '"bpm": 78' in captured["system"]          # few-shot example present
    assert captured["system"].startswith(SYSTEM_PROMPT)  # base contract intact


def test_no_genre_keeps_bare_prompt():
    captured = {}

    def llm(system, user):
        captured["system"] = system
        return json.dumps(valid_spec_dict())

    Mind(llm=llm).next_spec(make_state(), "x")
    assert captured["system"] == SYSTEM_PROMPT


def test_retry_uses_the_genre_prompt_too():
    systems = []
    replies = [json.dumps(valid_spec_dict(bpm=999)), json.dumps(valid_spec_dict())]

    def llm(system, user):
        systems.append(system)
        return replies[len(systems) - 1]

    Mind(llm=llm, genre="ambient").next_spec(make_state(), "x")
    assert len(systems) == 2 and systems[0] == systems[1]
    assert "GENRE: ambient" in systems[1]
