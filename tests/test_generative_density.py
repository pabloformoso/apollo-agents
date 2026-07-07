"""S-3 (#72): apply_density, new percussion roles, auto-fills. All deterministic."""

import random

import pytest

from agent.generative.interpreter import (
    DRUM_CHANNEL,
    DRUM_NOTES,
    TICKS_PER_BAR,
    apply_density,
    render,
)
from agent.generative.spec import DRUM_ROLES, NAMED_PATTERNS, PatternSpec, SpecError

from tests.test_generative_spec import valid_spec_dict


def hits(pattern: str) -> int:
    return sum(1 for ch in pattern if ch != ".")


def drum_ons(events, name, bar=None):
    out = [e for e in events
           if e.kind == "on" and e.channel == DRUM_CHANNEL and e.note == DRUM_NOTES[name]]
    if bar is not None:
        out = [e for e in out if bar * TICKS_PER_BAR <= e.tick < (bar + 1) * TICKS_PER_BAR]
    return out


# --- apply_density (pure function) ------------------------------------------------

def test_density_monotonic_note_count():
    pattern = NAMED_PATTERNS["garage"]
    counts = []
    for density in (0.0, 0.25, 0.5, 0.75, 1.0):
        counts.append(hits(apply_density(pattern, density, random.Random(9))))
    assert counts == sorted(counts)
    assert counts[0] == 0 and counts[-1] == 16


def test_density_removal_is_weakest_beat_first():
    # 4-on-floor (downbeats + beats): reducing to 2 hits must keep downbeats 0 and 8
    reduced = apply_density(NAMED_PATTERNS["4-on-floor"], 2 / 16, random.Random(1))
    assert reduced[0] == "x" and reduced[8] == "x"
    assert hits(reduced) == 2


def test_density_addition_fills_weak_positions_first():
    grown = apply_density(NAMED_PATTERNS["4-on-floor"], 8 / 16, random.Random(1))
    assert hits(grown) == 8
    # the original 4 hits are untouched
    for i in (0, 4, 8, 12):
        assert grown[i] == "x"
    # additions land on off-16ths (weakest class) before anything else
    added = [i for i in range(16) if grown[i] != "." and i not in (0, 4, 8, 12)]
    assert all(i % 2 == 1 for i in added)


def test_density_at_written_count_is_identity():
    pattern = NAMED_PATTERNS["garage"]  # 5 hits
    assert apply_density(pattern, hits(pattern) / 16, random.Random(3)) == pattern


def test_density_deterministic():
    pattern = NAMED_PATTERNS["shaker-groove"]
    assert (apply_density(pattern, 0.3, random.Random(5))
            == apply_density(pattern, 0.3, random.Random(5)))


# --- density through the spec/render path -------------------------------------------

def density_spec(density=None, fill="none", for_bars=4):
    d = valid_spec_dict(for_bars=for_bars)
    role = {"pattern": "garage", "vel": 90}
    if density is not None:
        role["density"] = density
    if fill != "none":
        role["fill"] = fill
    d["roles"] = {"hats": role}
    return PatternSpec.from_dict(d)


def test_render_event_count_monotonic_across_density_steps():
    counts = [len(drum_ons(render(density_spec(density=x), seed=7), "hats"))
              for x in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert counts == sorted(counts)


def test_absent_density_renders_byte_identical_to_today():
    d1 = valid_spec_dict()
    d2 = valid_spec_dict()  # same spec, no density/fill keys anywhere
    assert render(PatternSpec.from_dict(d1), 11) == render(PatternSpec.from_dict(d2), 11)


@pytest.mark.parametrize("bad", [-0.1, 1.5, "high", True])
def test_bad_density_rejected(bad):
    d = valid_spec_dict()
    d["roles"]["kick"] = {"pattern": "4-on-floor", "density": bad}
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


# --- fills ---------------------------------------------------------------------------

def test_fill_none_and_absent_render_identical():
    assert render(density_spec(fill="none"), 3) == render(density_spec(), 3)


def test_fill_confined_to_last_bar():
    plain = render(density_spec(), 3)
    filled = render(density_spec(fill="auto"), 3)
    for bar in range(3):  # bars 0-2: same hit positions (velocities may re-draw)
        assert ({e.tick for e in drum_ons(plain, "hats", bar)}
                == {e.tick for e in drum_ons(filled, "hats", bar)})
    assert len(drum_ons(filled, "hats", 3)) > len(drum_ons(plain, "hats", 3))


def test_fill_never_touches_kick_downbeat():
    d = valid_spec_dict(for_bars=2)
    d["roles"] = {"kick": {"pattern": "half-time", "fill": "auto", "vel": 110}}
    events = render(PatternSpec.from_dict(d), 3)
    last_bar = drum_ons(events, "kick", 1)
    # fills only add in steps 8-15; the downbeat hit at bar start is the written one
    assert all(e.tick == TICKS_PER_BAR or e.tick >= TICKS_PER_BAR + 8 * (TICKS_PER_BAR // 16)
               for e in last_bar)


@pytest.mark.parametrize("bad", ["yes", 1, "always"])
def test_bad_fill_rejected(bad):
    d = valid_spec_dict()
    d["roles"]["kick"] = {"pattern": "4-on-floor", "fill": bad}
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


# --- new roles ------------------------------------------------------------------------

def test_new_roles_validate_and_render():
    d = valid_spec_dict(for_bars=2)
    d["roles"] = {"perc": {"pattern": "rim-sync", "vel": 70},
                  "shaker": {"pattern": "shaker-groove", "vel": 50},
                  "clap": {"pattern": "clap-24", "vel": 85}}
    events = render(PatternSpec.from_dict(d), 0)
    for name in ("perc", "shaker", "clap"):
        assert name in DRUM_ROLES
        assert drum_ons(events, name), f"{name} rendered no events"


def test_new_roles_are_scale_exempt():
    d = valid_spec_dict()  # strict 8A key
    d["roles"]["shaker"] = {"pattern": "16ths", "vel": 40}
    PatternSpec.from_dict(d)  # must not raise


def test_new_roles_do_not_change_existing_spec_output():
    """FS1: pre-S-3 specs render byte-identical (role order kick/snare/hats first)."""
    spec = PatternSpec.from_dict(valid_spec_dict())
    events = render(spec, 42)
    assert events == render(spec, 42)
    assert not any(e.note in (37, 39, 70) for e in events if e.channel == DRUM_CHANNEL)


# --- mind vocabulary --------------------------------------------------------------------

def test_density_vocabulary_in_prompt():
    from agent.generative.mind import SYSTEM_PROMPT
    assert "density" in SYSTEM_PROMPT
    assert '"fill"' in SYSTEM_PROMPT or "fill" in SYSTEM_PROMPT
    assert "shaker" in SYSTEM_PROMPT
