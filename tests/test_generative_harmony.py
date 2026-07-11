"""M-1: voice leading. Pure, deterministic, movement-minimal."""

import pytest

from agent.generative.harmony import (
    RANGE_HI,
    RANGE_LO,
    chord_pitch_classes,
    voice_lead,
)
from agent.generative.spec import SpecError, chord_to_midi


def movement(prev, new):
    return sum(min(abs(n - p) for p in prev) for n in new)


def test_pitch_classes_distinct_and_ordered():
    assert chord_pitch_classes("Am") == [9, 0, 4]
    assert len(chord_pitch_classes("Am9")) == 5


def test_empty_prev_gives_close_voicing():
    assert voice_lead([], "Am") == chord_to_midi("Am", "close")


def test_deterministic():
    prev = chord_to_midi("Am9", "wide")
    assert voice_lead(prev, "Fmaj7") == voice_lead(prev, "Fmaj7")


def test_same_chord_stays_put():
    prev = chord_to_midi("Am", "close")  # [57, 60, 64]
    led = voice_lead(prev, "Am")
    assert led == prev  # zero movement is the cheapest voicing of the same chord


def test_movement_never_worse_than_root_position():
    progressions = [("Am9", "Fmaj7"), ("Cmaj7", "Em7"), ("Am", "G"), ("Fmaj7", "Am9")]
    for a, b in progressions:
        prev = chord_to_midi(a, "close")
        led = voice_lead(prev, b)
        root = chord_to_midi(b, "close")
        assert movement(prev, led) <= movement(prev, root)


def test_result_ascending_unique_in_range():
    prev = chord_to_midi("Am9", "wide")
    for chord in ("Fmaj7", "Cmaj7", "Em7", "G", "Dm7"):
        led = voice_lead(prev, chord)
        assert led == sorted(led)
        assert len(set(led)) == len(led)
        assert all(RANGE_LO <= n <= RANGE_HI for n in led)
        assert sorted(n % 12 for n in led) == sorted(chord_pitch_classes(chord))
        prev = led


def test_neighbour_chords_move_by_steps_not_jumps():
    # Am -> G: every voice should find a tone within a 3rd (4 semitones)
    prev = chord_to_midi("Am", "close")
    led = voice_lead(prev, "G")
    assert movement(prev, led) <= len(led) * 4


def test_invalid_chord_raises():
    with pytest.raises(SpecError):
        voice_lead([57, 60, 64], "Hm7")
