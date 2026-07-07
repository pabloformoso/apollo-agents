"""A-4: event -> mido message conversion and phrase playback (fake port).

Skipped wholesale when the optional `synth` group (mido) is not installed —
dispatch.py is the only module allowed to need it.
"""

import threading

import pytest

mido = pytest.importorskip("mido")

from agent.generative.clock import Clock
from agent.generative.dispatch import all_notes_off, event_to_message, play_events
from agent.generative.interpreter import MidiEvent, render, total_ticks
from agent.generative.spec import PatternSpec

from tests.test_generative_spec import valid_spec_dict


class FakePort:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


def fast_clock(bpm=200):
    """Real Clock but with no-op sleep — playback finishes instantly."""
    return Clock(bpm, time_fn=_counter(), sleep_fn=lambda s: None, spin_threshold=0.0)


def _counter():
    state = {"t": 0.0}

    def time_fn():
        state["t"] += 1.0  # each read jumps far past any deadline
        return state["t"]

    return time_fn


# --- event_to_message ------------------------------------------------------------

def test_note_on_conversion():
    msg = event_to_message(MidiEvent(0, "on", 9, 36, 110))
    assert msg.type == "note_on" and msg.channel == 9 and msg.note == 36 and msg.velocity == 110


def test_note_off_conversion():
    msg = event_to_message(MidiEvent(5, "off", 0, 33, 0))
    assert msg.type == "note_off" and msg.note == 33


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        event_to_message(MidiEvent(0, "bend", 0, 33, 0))


# --- play_events ------------------------------------------------------------------

def test_play_events_sends_everything_in_order():
    spec = PatternSpec.from_dict(valid_spec_dict(for_bars=1))
    events = render(spec, 0)
    port = FakePort()
    play_events(events, fast_clock(), port, total_ticks(spec))
    assert len(port.sent) == len(events)
    ons = [m for m in port.sent if m.type == "note_on"]
    assert len(ons) == sum(1 for e in events if e.kind == "on")


def test_play_events_stop_event_silences_notes():
    spec = PatternSpec.from_dict(valid_spec_dict(for_bars=4))
    events = render(spec, 0)
    port = FakePort()
    stop = threading.Event()
    stop.set()  # stop before the first tick
    play_events(events, fast_clock(), port, total_ticks(spec), stop_event=stop)
    # nothing played, but all-notes-off flushed on every channel
    cc123 = [m for m in port.sent if m.type == "control_change" and m.control == 123]
    assert len(cc123) == 3


def test_all_notes_off_targets_channels():
    port = FakePort()
    all_notes_off(port, channels=(0, 9))
    assert [m.channel for m in port.sent] == [0, 9]
    assert all(m.control == 123 for m in port.sent)
