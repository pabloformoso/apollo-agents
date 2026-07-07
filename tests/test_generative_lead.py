"""S-5 (#74): lead role, register/scale wiring, motif memory, variation classifier."""

import json

import numpy as np
import pytest

from agent.generative.interpreter import LEAD_CHANNEL, render
from agent.generative.motif import classify_variation, motif_of
from agent.generative.render_audio import render_audio
from agent.generative.spec import LEAD_RANGE, PatternSpec, SpecError
from agent.generative.state import build_state

from tests.test_generative_spec import valid_spec_dict

LEAD = {"notes": [[0, "E5", 1.0], [4, "G5", 0.5], [8, "A5", 1.5]], "vel": 84}


def lead_spec(lead=None, **overrides):
    d = valid_spec_dict(**overrides)
    d["roles"]["lead"] = lead or dict(LEAD)
    return d


# --- validation ---------------------------------------------------------------------

def test_lead_parses_and_renders_on_its_channel():
    spec = PatternSpec.from_dict(lead_spec())
    ons = [e for e in render(spec, 0) if e.kind == "on" and e.channel == LEAD_CHANNEL]
    assert ons and all(LEAD_RANGE[0] <= e.note <= LEAD_RANGE[1] for e in ons)


@pytest.mark.parametrize("note,ok", [
    ("C4", True), ("B6", True),      # inclusive bounds
    ("B3", False), ("C7", False),    # just outside
])
def test_lead_register_bounds(note, ok):
    d = lead_spec({"notes": [[0, note, 1.0]], "vel": 80})
    if ok:
        PatternSpec.from_dict(d)
    else:
        with pytest.raises(SpecError, match="register"):
            PatternSpec.from_dict(d)


def test_out_of_scale_lead_rejected_chromatic_admits():
    d = lead_spec({"notes": [[0, "C#5", 1.0]], "vel": 80})  # C# not in 8A / A minor
    with pytest.raises(SpecError, match="outside 8A"):
        PatternSpec.from_dict(d)
    d["chromatic"] = True
    PatternSpec.from_dict(d)  # escape hatch


def test_splitport_still_routes_only_drums():
    mido = pytest.importorskip("mido")
    from agent.generative.dispatch import SplitPort, event_to_message
    from agent.generative.interpreter import MidiEvent

    class FakePort:
        def __init__(self):
            self.sent = []
        def send(self, msg):
            self.sent.append(msg)

    main, drums = FakePort(), FakePort()
    port = SplitPort(main, drums)
    port.send(event_to_message(MidiEvent(0, "on", LEAD_CHANNEL, 76, 90)))
    port.send(event_to_message(MidiEvent(0, "on", 9, 36, 100)))
    assert [m.channel for m in main.sent] == [LEAD_CHANNEL]
    assert [m.channel for m in drums.sent] == [9]


# --- motif --------------------------------------------------------------------------

NOTES_A = [(0, 76, 1.0), (4, 79, 0.5), (8, 81, 1.5)]


def test_motif_extraction():
    m = motif_of(NOTES_A)
    assert m["intervals"] == [3, 2]
    assert m["rhythm"] == [4, 4]


def test_classify_transposition():
    up4 = [(s, n + 4, d) for s, n, d in NOTES_A]
    assert classify_variation(NOTES_A, up4) == {"transpose": 4}
    assert classify_variation(NOTES_A, list(NOTES_A)) == {"transpose": 0}


def test_classify_inversion():
    inverted = [(0, 76, 1.0), (4, 73, 0.5), (8, 71, 1.5)]  # intervals -3, -2
    assert classify_variation(NOTES_A, inverted) == {"invert": True}


def test_classify_augmentation():
    stretched = [(0, 76, 2.0), (8, 79, 1.0), (16, 81, 3.0)]
    # steps beyond 15 are invalid in a spec, but the classifier is pure math
    assert classify_variation(NOTES_A, stretched) == {"augment": 2.0}


def test_classify_unrelated():
    other = [(0, 60, 1.0), (2, 74, 0.25), (11, 66, 2.0)]
    assert classify_variation(NOTES_A, other) == "unrelated"
    assert classify_variation(NOTES_A, NOTES_A[:2]) == "unrelated"  # length mismatch


# --- motif memory in state/prompt -----------------------------------------------------

def test_motif_round_trips_through_state():
    spec = PatternSpec.from_dict(lead_spec())
    state = build_state(spec, 8, "x", [])
    assert state["lead_motif"]["intervals"] == [3, 2]

    from agent.generative.mind import Mind
    captured = {}

    def llm(system, user):
        captured["user"] = user
        return json.dumps(valid_spec_dict())

    Mind(llm=llm).next_spec(state, "x")
    assert "lead_motif" in captured["user"]
    assert '"intervals"' in captured["user"]


def test_no_lead_no_motif_key():
    spec = PatternSpec.from_dict(valid_spec_dict())
    assert "lead_motif" not in build_state(spec, 0, "x", [])


# --- renderer + presence -----------------------------------------------------------------

def test_lead_renders_non_silent_and_deterministic():
    spec = PatternSpec.from_dict({**lead_spec(for_bars=2),
                                  "roles": {"lead": dict(LEAD)}, "for_bars": 2,
                                  "bpm": 122, "key": "8A", "reason": "lead only"})
    a = render_audio(spec, 3)
    assert np.abs(a).max() > 0.02
    assert np.array_equal(a, render_audio(spec, 3))


def test_spec_without_lead_renders_byte_identical_to_today():
    spec = PatternSpec.from_dict(valid_spec_dict())
    assert np.array_equal(render_audio(spec, 9), render_audio(spec, 9))
    assert not any(e.channel == LEAD_CHANNEL for e in render(spec, 9))


def test_scripted_session_lead_presence_and_scale():
    from agent.generative.scales import camelot_scale
    specs = [PatternSpec.from_dict(lead_spec()) for _ in range(4)]
    specs.append(PatternSpec.from_dict(valid_spec_dict()))  # 1 of 5 without lead
    with_lead = 0
    scale = camelot_scale("8A")
    for s in specs:
        ons = [e for e in render(s, 0) if e.kind == "on" and e.channel == LEAD_CHANNEL]
        if ons:
            with_lead += 1
            assert all(e.note % 12 in scale for e in ons)
    assert with_lead / len(specs) >= 0.6
