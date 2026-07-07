"""Camelot key -> scale pitch classes (M-3). The key finally gets teeth.

A-side = natural minor (aeolian), B-side = major (ionian) — the same
convention tracks.json uses. Minor keys also admit the raised 7th
(harmonic minor leading tone): a V7 chord in a minor key is idiomatic,
not an accident, and rejecting it would fight the mind for no musical
reason.

Pure lookup tables + set math. No I/O.
"""

from __future__ import annotations

from .spec import SpecError

# Camelot number -> tonic pitch class (C=0). 8A = A minor, 8B = C major.
_MINOR_TONICS = {1: 8, 2: 3, 3: 10, 4: 5, 5: 0, 6: 7, 7: 2, 8: 9, 9: 4, 10: 11, 11: 6, 12: 1}
_MAJOR_TONICS = {1: 11, 2: 6, 3: 1, 4: 8, 5: 3, 6: 10, 7: 5, 8: 0, 9: 7, 10: 2, 11: 9, 12: 4}

_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)

_PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def camelot_scale(key: str) -> frozenset[int]:
    """Pitch classes allowed in a Camelot key.

    Minor (A-side) includes the harmonic-minor leading tone, so an
    8A scale is A natural minor plus G#.
    """
    try:
        number, side = int(key[:-1]), key[-1]
    except (ValueError, IndexError):
        raise SpecError(f"invalid Camelot key: {key!r}")
    if side == "A":
        tonic = _MINOR_TONICS.get(number)
        steps = _MINOR_STEPS
    elif side == "B":
        tonic = _MAJOR_TONICS.get(number)
        steps = _MAJOR_STEPS
    else:
        tonic = None
    if tonic is None:
        raise SpecError(f"invalid Camelot key: {key!r}")
    pcs = {(tonic + s) % 12 for s in steps}
    if side == "A":
        pcs.add((tonic + 11) % 12)  # raised 7th
    return frozenset(pcs)


def key_name(key: str) -> str:
    """'8A' -> 'A minor' — for prompts and error messages."""
    number, side = int(key[:-1]), key[-1]
    if side == "A":
        return f"{_PC_NAMES[_MINOR_TONICS[number]]} minor"
    return f"{_PC_NAMES[_MAJOR_TONICS[number]]} major"


def pc_name(pc: int) -> str:
    return _PC_NAMES[pc % 12]
