"""Instant control layer: intent matching + live CC ramps (no I/O, no LLM)."""

import pytest

from agent.generative.controls import (
    CC_BRIGHTNESS,
    CC_ENERGY,
    DEFAULT_LEVELS,
    LiveControls,
    match_intent,
)
from agent.generative.interpreter import TICKS_PER_BAR, TICKS_PER_STEP


# --- match_intent ------------------------------------------------------------

def test_darker_targets_both_ccs_low():
    targets = match_intent("darker")
    assert targets[CC_ENERGY] < 0.5 and targets[CC_BRIGHTNESS] < 0.5


def test_match_is_substring_and_case_insensitive():
    assert match_intent("BUILD to a peak now") is not None
    assert match_intent("Make it DARKER please") is not None


def test_specific_keyword_wins_over_prefix():
    # "darker" must match before "dark"
    assert match_intent("darker") == match_intent("go darker")
    assert match_intent("darker")[CC_BRIGHTNESS] == 0.15


def test_unknown_intent_returns_none():
    assert match_intent("play some jazz") is None
    assert match_intent("") is None


# --- LiveControls -------------------------------------------------------------

def collect(live: LiveControls, from_tick: int, to_tick: int):
    events = []
    for t in range(from_tick, to_tick):
        events.extend(live.on_tick(t))
    return events


def test_no_ramp_no_events():
    live = LiveControls()
    assert collect(live, 0, TICKS_PER_BAR) == []


def test_unmatched_trigger_returns_false_and_stays_silent():
    live = LiveControls()
    assert live.trigger("polka time", 0) is False
    assert collect(live, 0, TICKS_PER_BAR) == []


def test_ramp_reaches_target_within_ramp_bars():
    live = LiveControls(ramp_bars=1.0)
    assert live.trigger("darker", 0) is True
    events = collect(live, 0, TICKS_PER_BAR + TICKS_PER_STEP)
    energy = [e for e in events if e.note == CC_ENERGY]
    assert energy[0].velocity == round(127 * DEFAULT_LEVELS[CC_ENERGY])
    assert energy[-1].velocity == round(127 * 0.25)
    # monotonic descent, deduped
    vels = [e.velocity for e in energy]
    assert vels == sorted(vels, reverse=True)
    assert len(vels) == len(set(vels))


def test_events_only_on_step_boundaries():
    live = LiveControls()
    live.trigger("build", 0)
    for e in collect(live, 0, TICKS_PER_BAR):
        assert e.tick % TICKS_PER_STEP == 0
        assert e.kind == "cc"


def test_retrigger_mid_ramp_starts_from_current_level():
    live = LiveControls(ramp_bars=1.0)
    live.trigger("peak", 0)  # ramping up toward 1.0
    collect(live, 0, TICKS_PER_BAR // 2)
    mid_level = live.levels[CC_ENERGY]
    live.trigger("darker", TICKS_PER_BAR // 2)  # reverse from wherever we are
    # tick 48 itself dedupes (same value as the up-ramp just sent) — look at
    # the first couple of steps: the descent continues from mid_level, no jump.
    events = collect(live, TICKS_PER_BAR // 2, TICKS_PER_BAR // 2 + 2 * TICKS_PER_STEP)
    first = [e for e in events if e.note == CC_ENERGY][0]
    assert abs(first.velocity - 127 * mid_level) <= 6  # one step of descent, no jump


def test_ramp_finishes_and_stops_emitting():
    live = LiveControls(ramp_bars=0.5)
    live.trigger("calm", 0)
    collect(live, 0, TICKS_PER_BAR)
    # ramp done — no further events
    assert collect(live, TICKS_PER_BAR, 2 * TICKS_PER_BAR) == []
    assert live.levels[CC_ENERGY] == pytest.approx(0.3)


def test_values_always_7bit():
    live = LiveControls(ramp_bars=1.0)
    live.trigger("peak", 0)
    for e in collect(live, 0, 2 * TICKS_PER_BAR):
        assert 0 <= e.velocity <= 127
