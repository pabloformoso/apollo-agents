"""Motif memory (S-5 / #74): represent, compare and classify melodic variation.

A motif is the shape of a lead line: pitch intervals + rhythm, independent
of absolute pitch. The mind is instructed to VARY the previous motif
(transpose / invert / augment / answer) instead of reinventing every phrase;
classify_variation makes that relationship machine-checkable.

Pure functions over LeadRole note tuples (step, midi, beats).
"""

from __future__ import annotations

Note = tuple[int, int, float]  # (step, midi, beats)


def motif_of(notes) -> dict:
    """Extract the pitch/rhythm shape of a note list, absolute-pitch-free."""
    ordered = sorted(notes, key=lambda n: n[0])
    steps = [n[0] for n in ordered]
    return {
        "intervals": [b[1] - a[1] for a, b in zip(ordered, ordered[1:])],
        "rhythm": [b - a for a, b in zip(steps, steps[1:])],
        "durations": [n[2] for n in ordered],
    }


def classify_variation(notes_a, notes_b) -> dict | str:
    """How does motif B relate to motif A?

    Returns {"transpose": semitones} (0 = identical), {"invert": True},
    {"augment": ratio}, or "unrelated". Checked in priority order —
    a transposition is also reported as such when the offset is 0.
    """
    if not notes_a or not notes_b or len(notes_a) != len(notes_b):
        return "unrelated"
    a, b = motif_of(notes_a), motif_of(notes_b)
    ordered_a = sorted(notes_a, key=lambda n: n[0])
    ordered_b = sorted(notes_b, key=lambda n: n[0])

    if a["rhythm"] == b["rhythm"] and a["durations"] == b["durations"]:
        if a["intervals"] == b["intervals"]:
            return {"transpose": ordered_b[0][1] - ordered_a[0][1]}
        if any(a["intervals"]) and b["intervals"] == [-i for i in a["intervals"]]:
            return {"invert": True}

    if a["intervals"] == b["intervals"] and a["rhythm"] and all(r > 0 for r in a["rhythm"]):
        ratios = {rb / ra for ra, rb in zip(a["rhythm"], b["rhythm"]) if ra > 0}
        dur_ratios = {db / da for da, db in zip(a["durations"], b["durations"]) if da > 0}
        if len(ratios) == 1 and ratios != {1.0} and (not dur_ratios or dur_ratios == ratios):
            return {"augment": ratios.pop()}

    return "unrelated"
