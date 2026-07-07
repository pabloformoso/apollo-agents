"""A-2: spec -> MIDI event stream. Determinism (FS1), swing, humanization bounds."""

from agent.generative.interpreter import (
    ACCENT_BOOST,
    BASS_CHANNEL,
    DRUM_CHANNEL,
    DRUM_NOTES,
    PAD_CHANNEL,
    TICKS_PER_BAR,
    TICKS_PER_BEAT,
    TICKS_PER_STEP,
    VEL_JITTER,
    render,
    total_ticks,
)
from agent.generative.spec import PatternSpec

from tests.test_generative_spec import valid_spec_dict


def make_spec(**overrides) -> PatternSpec:
    return PatternSpec.from_dict(valid_spec_dict(**overrides))


def only(events, **filters):
    return [e for e in events
            if all(getattr(e, k) == v for k, v in filters.items())]


# --- determinism (FS1) ------------------------------------------------------

def test_same_spec_same_seed_identical():
    spec = make_spec()
    assert render(spec, seed=42) == render(spec, seed=42)


def test_different_seed_differs():
    spec = make_spec()
    assert render(spec, seed=1) != render(spec, seed=2)


def test_role_dict_order_does_not_matter():
    d1 = valid_spec_dict()
    d2 = valid_spec_dict()
    d2["roles"] = dict(reversed(list(d2["roles"].items())))
    assert render(PatternSpec.from_dict(d1), 7) == render(PatternSpec.from_dict(d2), 7)


# --- placement --------------------------------------------------------------

def test_four_on_floor_kick_lands_on_beats():
    spec = make_spec(for_bars=2)
    ons = only(render(spec, 0), kind="on", channel=DRUM_CHANNEL, note=DRUM_NOTES["kick"])
    assert [e.tick for e in ons] == [
        0, TICKS_PER_BEAT, 2 * TICKS_PER_BEAT, 3 * TICKS_PER_BEAT,
        TICKS_PER_BAR, TICKS_PER_BAR + TICKS_PER_BEAT,
        TICKS_PER_BAR + 2 * TICKS_PER_BEAT, TICKS_PER_BAR + 3 * TICKS_PER_BEAT,
    ]


def test_swing_delays_odd_steps_only():
    d = valid_spec_dict(for_bars=1)
    d["roles"] = {"hats": {"pattern": "xx" + "." * 14, "swing": 0.5, "vel": 80}}
    d["reason"] = "swing test"
    ons = only(render(PatternSpec.from_dict(d), 0), kind="on")
    # step 0 on the grid; step 1 delayed by 0.5 * TICKS_PER_STEP = 3 ticks
    assert ons[0].tick == 0
    assert ons[1].tick == TICKS_PER_STEP + TICKS_PER_STEP // 2


def test_bass_note_duration_in_beats():
    spec = make_spec(for_bars=1)
    ons = only(render(spec, 0), kind="on", channel=BASS_CHANNEL)
    offs = only(render(spec, 0), kind="off", channel=BASS_CHANNEL)
    # first bass note: step 0, A1 (33), 1.0 beats
    assert ons[0].tick == 0 and ons[0].note == 33
    matching_off = [e for e in offs if e.note == 33][0]
    assert matching_off.tick == TICKS_PER_BEAT


def test_pad_sustains_the_whole_bar():
    spec = make_spec(for_bars=2)
    events = render(spec, 0)
    ons = only(events, kind="on", channel=PAD_CHANNEL)
    offs = only(events, kind="off", channel=PAD_CHANNEL)
    assert {e.tick for e in ons} == {0, TICKS_PER_BAR}
    assert {e.tick for e in offs} == {TICKS_PER_BAR - 1, 2 * TICKS_PER_BAR - 1}
    # Am9 wide = 5 notes per bar
    assert len(ons) == 10


def test_omitted_role_is_silent():
    d = valid_spec_dict()
    d["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 110}}
    events = render(PatternSpec.from_dict(d), 0)
    assert only(events, channel=BASS_CHANNEL) == []
    assert only(events, channel=PAD_CHANNEL) == []


# --- humanization bounds -----------------------------------------------------

def test_velocity_jitter_bounded():
    spec = make_spec()
    for seed in range(10):
        for e in only(render(spec, seed), kind="on", channel=DRUM_CHANNEL, note=DRUM_NOTES["kick"]):
            assert abs(e.velocity - 110) <= VEL_JITTER


def test_accent_boosts_velocity():
    d = valid_spec_dict(for_bars=1)
    d["roles"] = {"kick": {"pattern": "X" + "." * 15, "vel": 100}}
    vels = [only(render(PatternSpec.from_dict(d), s), kind="on")[0].velocity for s in range(10)]
    assert all(abs(v - (100 + ACCENT_BOOST)) <= VEL_JITTER for v in vels)


def test_velocity_always_valid_midi():
    d = valid_spec_dict(for_bars=1)
    d["roles"] = {"kick": {"pattern": "X" * 16, "vel": 127}, "hats": {"pattern": "x" * 16, "vel": 1}}
    for seed in range(20):
        for e in only(render(PatternSpec.from_dict(d), seed), kind="on"):
            assert 1 <= e.velocity <= 127


# --- structure ----------------------------------------------------------------

def test_every_on_has_an_off():
    events = render(make_spec(), 3)
    per_note = {}
    for e in events:
        on, off = per_note.setdefault((e.channel, e.note), [0, 0])
        per_note[(e.channel, e.note)] = [on + (e.kind == "on"), off + (e.kind == "off")]
    for (channel, note), (ons, offs) in per_note.items():
        assert ons == offs, f"unbalanced note ch{channel}/{note}: {ons} ons vs {offs} offs"


def test_events_sorted_and_within_phrase():
    spec = make_spec()
    events = render(spec, 0)
    assert events == sorted(events)
    assert events[-1].tick <= total_ticks(spec)


def test_total_ticks():
    assert total_ticks(make_spec(for_bars=8)) == 8 * TICKS_PER_BAR


# --- controls (CC lane) --------------------------------------------------------

def make_controls_spec(ramps, for_bars=4):
    d = valid_spec_dict(for_bars=for_bars)
    d["roles"] = {"kick": {"pattern": "4-on-floor", "vel": 110}, "controls": {"ramps": ramps}}
    return PatternSpec.from_dict(d)


def test_cc_ramp_hits_endpoints():
    spec = make_controls_spec([{"cc": 74, "from": 0.0, "to": 1.0, "start_bar": 0, "over_bars": 4}])
    ccs = only(render(spec, 0), kind="cc", note=74)
    assert ccs[0].tick == 0 and ccs[0].velocity == 0
    assert ccs[-1].tick == 4 * TICKS_PER_BAR and ccs[-1].velocity == 127
    vels = [e.velocity for e in ccs]
    assert vels == sorted(vels)          # monotonic rise
    assert len(vels) == len(set(vels))   # deduped


def test_cc_ramp_clipped_to_phrase_end():
    spec = make_controls_spec([{"cc": 1, "from": 0.0, "to": 1.0, "start_bar": 2, "over_bars": 30}],
                              for_bars=4)
    ccs = only(render(spec, 0), kind="cc", note=1)
    assert ccs[0].tick == 2 * TICKS_PER_BAR
    assert ccs[-1].tick <= 4 * TICKS_PER_BAR


def test_cc_ramp_past_phrase_dropped():
    spec = make_controls_spec([{"cc": 1, "from": 0.0, "to": 1.0, "start_bar": 10, "over_bars": 2}],
                              for_bars=4)
    assert only(render(spec, 0), kind="cc") == []


def test_cc_events_deterministic_and_seed_independent():
    spec = make_controls_spec([{"cc": 74, "from": 0.2, "to": 0.8, "start_bar": 0, "over_bars": 4}])
    ccs1 = only(render(spec, 1), kind="cc")
    ccs2 = only(render(spec, 99), kind="cc")
    assert ccs1 == ccs2  # control curves carry no humanization


def test_flat_ramp_emits_single_value():
    spec = make_controls_spec([{"cc": 1, "from": 0.5, "to": 0.5, "start_bar": 0, "over_bars": 4}])
    ccs = only(render(spec, 0), kind="cc", note=1)
    assert len(ccs) == 1 and ccs[0].velocity == 64
