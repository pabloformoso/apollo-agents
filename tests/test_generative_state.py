"""A-5 (minimal): musical-state serializer."""

import json

from agent.generative.spec import PatternSpec
from agent.generative.state import MAX_RECENT_REASONS, build_state, to_prompt

from tests.test_generative_spec import valid_spec_dict


def test_state_shape():
    spec = PatternSpec.from_dict(valid_spec_dict())
    state = build_state(spec, bars_elapsed=24, intent="darker", recent_reasons=["r1", "r2"])
    assert state["now_playing"] == spec.summary()
    assert state["bars_elapsed"] == 24
    assert state["standing_intent"] == "darker"
    assert state["recent_reasons"] == ["r1", "r2"]
    assert "clock_p99_jitter_ms" not in state


def test_empty_intent_gets_a_default():
    spec = PatternSpec.from_dict(valid_spec_dict())
    state = build_state(spec, 0, "   ", [])
    assert "keep the groove" in state["standing_intent"]


def test_reasons_truncated_to_last_n():
    spec = PatternSpec.from_dict(valid_spec_dict())
    reasons = [f"r{i}" for i in range(20)]
    state = build_state(spec, 0, "x", reasons)
    assert state["recent_reasons"] == reasons[-MAX_RECENT_REASONS:]


def test_jitter_included_when_given():
    spec = PatternSpec.from_dict(valid_spec_dict())
    state = build_state(spec, 0, "x", [], jitter_ms=1.25)
    assert state["clock_p99_jitter_ms"] == 1.25


def test_to_prompt_is_json():
    spec = PatternSpec.from_dict(valid_spec_dict())
    state = build_state(spec, 8, "build", ["r"])
    assert json.loads(to_prompt(state)) == state
