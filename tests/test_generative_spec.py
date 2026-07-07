"""A-1: pattern-spec schema + validator. Reject-and-hold semantics = SpecError."""

import pytest

from agent.generative.spec import (
    BassRole,
    DrumRole,
    NAMED_PATTERNS,
    PadRole,
    PatternSpec,
    SpecError,
    chord_to_midi,
    expand_pattern,
    note_to_midi,
)


def valid_spec_dict(**overrides) -> dict:
    d = {
        "for_bars": 8,
        "bpm": 122,
        "key": "8A",
        "roles": {
            "kick": {"pattern": "4-on-floor", "vel": 110},
            "hats": {"pattern": "x.x.xx.x", "swing": 0.12, "vel": 80},
            "bass": {"notes": [[0, "A1", 1.0], [3, "E2", 0.5]], "vel": 90},
            "pad": {"chord": "Am9", "voicing": "wide", "vel": 60},
        },
        "reason": "16 bars of plateau — add bass syncopation to lift before peak",
        "rethink_in_bars": 8,
    }
    d.update(overrides)
    return d


# --- happy path -----------------------------------------------------------

def test_valid_spec_parses():
    spec = PatternSpec.from_dict(valid_spec_dict())
    assert spec.for_bars == 8
    assert spec.bpm == 122.0
    assert spec.key == "8A"
    assert isinstance(spec.roles["kick"], DrumRole)
    assert isinstance(spec.roles["bass"], BassRole)
    assert isinstance(spec.roles["pad"], PadRole)
    assert spec.reason.startswith("16 bars")


def test_rethink_defaults_to_for_bars():
    d = valid_spec_dict()
    del d["rethink_in_bars"]
    assert PatternSpec.from_dict(d).rethink_in_bars == 8


def test_summary_mentions_every_role():
    s = PatternSpec.from_dict(valid_spec_dict()).summary()
    for token in ("122bpm", "8A", "kick=", "hats=", "bass=", "pad=Am9/wide"):
        assert token in s


# --- field validation ------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("for_bars", 0), ("for_bars", 33), ("for_bars", 2.5), ("for_bars", True),
    ("bpm", 59), ("bpm", 201), ("bpm", "fast"),
    ("key", "13A"), ("key", "0B"), ("key", "8C"), ("key", "Am"), ("key", ""),
    ("reason", ""), ("reason", "   "), ("reason", 42),
    ("rethink_in_bars", 0), ("rethink_in_bars", 40), ("rethink_in_bars", False),
    ("roles", {}), ("roles", "kick"),
])
def test_bad_fields_rejected(field, value):
    with pytest.raises(SpecError):
        PatternSpec.from_dict(valid_spec_dict(**{field: value}))


def test_non_dict_spec_rejected():
    with pytest.raises(SpecError):
        PatternSpec.from_dict("not a spec")


def test_unknown_role_rejected():
    d = valid_spec_dict()
    d["roles"]["theremin"] = {"pattern": "16ths"}
    with pytest.raises(SpecError, match="unknown role"):
        PatternSpec.from_dict(d)


@pytest.mark.parametrize("bad_role", [
    {"pattern": "x.y."},          # bad char
    {"pattern": "x.x.x"},         # length 5 doesn't divide 16
    {"pattern": ""},              # empty
    {"pattern": "16ths", "vel": 0},
    {"pattern": "16ths", "vel": 128},
    {"pattern": "16ths", "vel": 90.5},
    {"pattern": "16ths", "swing": 0.6},
    {"pattern": "16ths", "swing": -0.1},
])
def test_bad_drum_role_rejected(bad_role):
    d = valid_spec_dict()
    d["roles"]["kick"] = bad_role
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


@pytest.mark.parametrize("bad_notes", [
    [],                                # empty
    [[0, "A1"]],                       # missing duration
    [[16, "A1", 1.0]],                 # step out of range
    [[-1, "A1", 1.0]],
    [[0, "H1", 1.0]],                  # bad note name
    [[0, "A1", 0]],                    # zero duration
    [[0, "A1", 5.0]],                  # > 4 beats
    "A1",                              # not a list
])
def test_bad_bass_notes_rejected(bad_notes):
    d = valid_spec_dict()
    d["roles"]["bass"] = {"notes": bad_notes}
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


@pytest.mark.parametrize("bad_pad", [
    {"chord": "Hm9"},
    {"chord": ""},
    {"chord": "Am9", "voicing": "spread"},
    {"chord": "Am9", "vel": 200},
])
def test_bad_pad_rejected(bad_pad):
    d = valid_spec_dict()
    d["roles"]["pad"] = bad_pad
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


# --- helpers ---------------------------------------------------------------

def test_named_patterns_expand_to_16_steps():
    for name in NAMED_PATTERNS:
        assert len(expand_pattern(name)) == 16


def test_short_patterns_expand():
    assert expand_pattern("x...") == "x" + "." * 15
    assert len(expand_pattern("x.x.xx.x")) == 16
    assert expand_pattern("xxxx") == "x...x...x...x..."   # == 4-on-floor


def test_note_to_midi():
    assert note_to_midi("C4") == 60
    assert note_to_midi("A1") == 33
    assert note_to_midi("F#1") == 30
    assert note_to_midi("Bb2") == 46


@pytest.mark.parametrize("bad", ["", "H1", "A", "A#", "C99"])
def test_note_to_midi_rejects(bad):
    with pytest.raises(SpecError):
        note_to_midi(bad)


def test_chord_to_midi_close_and_wide():
    close = chord_to_midi("Am", "close")
    assert close == [57, 60, 64]  # A3 C4 E4
    wide = chord_to_midi("Am", "wide")
    assert wide[0] == close[0] - 12
    assert wide[1:] == close[1:]


def test_chord_qualities():
    assert len(chord_to_midi("Am9")) == 5
    assert len(chord_to_midi("Cmaj7")) == 4
    assert len(chord_to_midi("F#m7")) == 4


@pytest.mark.parametrize("bad", ["", "Hm", "Aminor", "A#x7"])
def test_chord_to_midi_rejects(bad):
    with pytest.raises(SpecError):
        chord_to_midi(bad)


# --- controls role (v0.2: CC control lane) -----------------------------------

def test_controls_role_parses():
    d = valid_spec_dict()
    d["roles"]["controls"] = {"ramps": [
        {"cc": 74, "from": 0.3, "to": 0.9, "start_bar": 0, "over_bars": 8},
        {"cc": 1, "from": 0.5, "to": 0.5, "start_bar": 4, "over_bars": 2, "channel": 1},
    ]}
    spec = PatternSpec.from_dict(d)
    ramps = spec.roles["controls"].ramps
    assert len(ramps) == 2
    assert ramps[0].cc == 74 and ramps[0].to_val == 0.9
    assert ramps[1].channel == 1
    assert "controls=[cc74:0.30->0.90" in spec.summary()


@pytest.mark.parametrize("bad_ramp", [
    {"cc": 128, "from": 0, "to": 1},           # cc out of range
    {"cc": -1, "from": 0, "to": 1},
    {"cc": 1, "from": 1.5, "to": 0.5},          # from out of range
    {"cc": 1, "from": 0.5, "to": -0.1},         # to out of range
    {"cc": 1, "from": 0, "to": 1, "start_bar": -1},
    {"cc": 1, "from": 0, "to": 1, "over_bars": 0},
    {"cc": 1, "from": 0, "to": 1, "channel": 16},
    "cc74",                                      # not an object
])
def test_bad_control_ramp_rejected(bad_ramp):
    d = valid_spec_dict()
    d["roles"]["controls"] = {"ramps": [bad_ramp]}
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)


def test_controls_requires_nonempty_ramps():
    d = valid_spec_dict()
    d["roles"]["controls"] = {"ramps": []}
    with pytest.raises(SpecError):
        PatternSpec.from_dict(d)
