"""M-5: feel — timing slop + ghost notes. Deterministic, bounded, opt-in."""

import pytest

from agent.generative.interpreter import (
    DRUM_CHANNEL,
    DRUM_NOTES,
    GHOST_VEL_RATIO,
    SLOP_MAX_TICKS,
    TICKS_PER_STEP,
    VEL_JITTER,
    render,
)
from agent.generative.spec import FeelSpec, PatternSpec, SpecError

from tests.test_generative_spec import valid_spec_dict


def feel_spec(timing_slop=0.0, ghost_notes=0.0, **overrides):
    d = valid_spec_dict(**overrides)
    d["feel"] = {"timing_slop": timing_slop, "ghost_notes": ghost_notes}
    return PatternSpec.from_dict(d)


def drum_ons(events, name):
    return [e for e in events
            if e.kind == "on" and e.channel == DRUM_CHANNEL and e.note == DRUM_NOTES[name]]


# --- validation ------------------------------------------------------------------

def test_feel_defaults_to_zero():
    spec = PatternSpec.from_dict(valid_spec_dict())
    assert spec.feel == FeelSpec()


def test_feel_parses():
    spec = feel_spec(0.5, 0.4)
    assert spec.feel.timing_slop == 0.5
    assert spec.feel.ghost_notes == 0.4


@pytest.mark.parametrize("bad", [
    {"timing_slop": 1.5},
    {"timing_slop": -0.1},
    {"ghost_notes": 2},
    {"ghost_notes": True},
    "sloppy",
])
def test_bad_feel_rejected(bad):
    d = valid_spec_dict()
    d["feel"] = bad
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


# --- determinism -------------------------------------------------------------------

def test_feel_render_deterministic():
    spec = feel_spec(0.6, 0.5)
    assert render(spec, seed=7) == render(spec, seed=7)


def test_zero_feel_identical_to_no_feel():
    """feel: {0, 0} must render byte-identical to a spec without feel."""
    plain = PatternSpec.from_dict(valid_spec_dict())
    zeroed = feel_spec(0.0, 0.0)
    for seed in range(5):
        assert render(plain, seed) == render(zeroed, seed)


# --- timing slop ---------------------------------------------------------------------

def test_slop_shifts_at_most_one_tick_and_only_off_grid_roles():
    d = valid_spec_dict(for_bars=4)
    d["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 110},
                  "hats": {"pattern": "x" * 16, "vel": 60}}  # no swing
    d["feel"] = {"timing_slop": 1.0}
    events = render(PatternSpec.from_dict(d), 3)
    for e in drum_ons(events, "hats"):
        assert e.tick % TICKS_PER_STEP in (0, SLOP_MAX_TICKS, TICKS_PER_STEP - SLOP_MAX_TICKS)
    # the kick anchors: always exactly on the grid
    for e in drum_ons(events, "kick"):
        assert e.tick % TICKS_PER_STEP == 0


def test_slop_actually_moves_something():
    d = valid_spec_dict(for_bars=8)
    d["roles"] = {"hats": {"pattern": "x" * 16, "vel": 60}}
    d["feel"] = {"timing_slop": 1.0}
    events = render(PatternSpec.from_dict(d), 3)
    assert any(e.tick % TICKS_PER_STEP != 0 for e in drum_ons(events, "hats"))


# --- ghost notes ------------------------------------------------------------------------

def test_ghosts_are_quiet_and_extra():
    d = valid_spec_dict(for_bars=8)
    d["roles"] = {"hats": {"pattern": "x...x...x...x...", "vel": 100}}
    base_count = 4 * 8
    d["feel"] = {"ghost_notes": 1.0}
    events = render(PatternSpec.from_dict(d), 3)
    ons = drum_ons(events, "hats")
    ghosts = [e for e in ons if e.velocity <= int(100 * GHOST_VEL_RATIO) + VEL_JITTER]
    assert len(ons) > base_count          # something was added
    assert len(ghosts) == len(ons) - base_count  # and everything added is quiet


def test_no_ghosts_on_the_kick():
    d = valid_spec_dict(for_bars=8)
    d["roles"] = {"kick": {"pattern": "x...x...x...x...", "vel": 110}}
    d["feel"] = {"ghost_notes": 1.0}
    events = render(PatternSpec.from_dict(d), 3)
    assert len(drum_ons(events, "kick")) == 4 * 8  # exactly the written hits


def test_ghost_density_bounded():
    d = valid_spec_dict(for_bars=8)
    d["roles"] = {"snare": {"pattern": "....x.......x...", "vel": 80}}
    d["feel"] = {"ghost_notes": 1.0}
    events = render(PatternSpec.from_dict(d), 3)
    written = 2 * 8
    ons = drum_ons(events, "snare")
    empty_steps = 14 * 8
    # at most ~GHOST_DENSITY of empty steps become ghosts (loose statistical bound)
    assert written < len(ons) <= written + int(empty_steps * 0.4)


def test_every_ghost_velocity_is_valid_midi():
    d = valid_spec_dict(for_bars=8)
    d["roles"] = {"hats": {"pattern": "x.x.x.x.x.x.x.x.", "vel": 3}}
    d["feel"] = {"ghost_notes": 1.0, "timing_slop": 1.0}
    for seed in range(5):
        for e in drum_ons(render(PatternSpec.from_dict(d), seed), "hats"):
            assert 1 <= e.velocity <= 127
