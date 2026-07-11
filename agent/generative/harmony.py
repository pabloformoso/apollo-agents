"""Voice leading: choose chord voicings that move minimally between changes (M-1).

Pure functions, no I/O, no randomness — the single highest musical-value
piece of v3.0. When a progression moves Am9 -> Fmaj7, the ear wants each
voice to step to its nearest chord tone, not the whole hand to jump to
root position.

Algorithm: enumerate every voicing of the target chord within RANGE
(each pitch class placed in any octave), score each candidate by the sum
of distances from its notes to the nearest note of the previous voicing,
and return the cheapest. Ties break to the lexicographically lowest
voicing, so the result is fully deterministic (FS1).
"""

from __future__ import annotations

import itertools

from .spec import chord_to_midi

RANGE_LO, RANGE_HI = 36, 84  # C2..C6 — pads live here


def chord_pitch_classes(chord: str) -> list[int]:
    """Distinct pitch classes of a chord, in chord-tone order."""
    seen = []
    for note in chord_to_midi(chord, "close"):
        pc = note % 12
        if pc not in seen:
            seen.append(pc)
    return seen


def _octave_options(pc: int) -> list[int]:
    return [n for n in range(RANGE_LO + ((pc - RANGE_LO) % 12), RANGE_HI + 1, 12)]


def _movement_cost(candidate: tuple[int, ...], prev: list[int]) -> int:
    return sum(min(abs(note - p) for p in prev) for note in candidate)


def voice_lead(prev: list[int], chord: str) -> list[int]:
    """Voicing of `chord` minimizing total voice movement from `prev`.

    prev: the previous voicing (MIDI notes). Empty prev -> close voicing.
    Returns ascending, duplicate-free MIDI notes, one per pitch class.
    """
    if not prev:
        return chord_to_midi(chord, "close")

    best: tuple[int, ...] | None = None
    best_cost = None
    options = [_octave_options(pc) for pc in chord_pitch_classes(chord)]
    for combo in itertools.product(*options):
        ordered = tuple(sorted(combo))
        if len(set(ordered)) != len(ordered):
            continue
        cost = _movement_cost(ordered, prev)
        if best_cost is None or cost < best_cost or (cost == best_cost and ordered < best):
            best, best_cost = ordered, cost
    return list(best)
