"""ACE-Step ``metas.keyscale`` -> Camelot. The inverse of ``generative/scales.py``.

ACE-Step reports the key it actually generated in as ``metas.keyscale``
("A Minor", "C# Major", "Ab minor" — spelling and case vary with the LM
that formats the request). The catalog stores Camelot ("8A"), which is
what every harmonic-mixing path in Apollo reads. This module is the
bridge, and it is the whole reason ``--ingest`` never has to guess a
key: the generator already knows it, and guessed metadata is exactly
how the catalog got poisoned BPMs and live genre drift.

Convention — identical to ``tracks.json`` and
``agent/generative/scales.py``: the A-side is natural minor (aeolian),
the B-side is major (ionian). 8A = A minor, 8B = C major. The tables
below are the exact inverses of that module's ``_MINOR_TONICS`` /
``_MAJOR_TONICS``; ``tests/test_keyscale.py`` asserts the round-trip so
the two can never drift apart.

Pure lookup tables and one regex. No I/O and no third-party imports —
like ``agent/track_identity.py`` this stays importable on a host with
nothing installed, because ``--ingest`` runs where madmom does not.
"""
from __future__ import annotations

import re

# Pitch class of each natural note (C = 0), the same numbering
# ``generative/scales.py`` uses.
_NATURAL_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# Pitch class -> Camelot number. Inverse of scales._MINOR_TONICS /
# scales._MAJOR_TONICS. Enharmonics collapse for free: Ab and G# are
# both pitch class 8, so both land on 1A.
_MINOR_PC_TO_NUMBER = {8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7, 9: 8, 4: 9, 11: 10, 6: 11, 1: 12}
_MAJOR_PC_TO_NUMBER = {11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7, 0: 8, 7: 9, 2: 10, 9: 11, 4: 12}

# Mode words we accept. ``aeolian``/``ionian`` are in because
# ``generative/scales.py`` names the sides that way and an LM that has
# read music theory will occasionally use them.
#
# Deliberately NOT accepted: a bare "m" / "M" suffix ("Am", "AM").
# Case is the only thing separating minor from major there, and this
# parser is case-tolerant by contract — so those two forms are
# genuinely ambiguous and get refused rather than silently guessed.
_MINOR_MODES = frozenset({"minor", "min", "aeolian"})
_MAJOR_MODES = frozenset({"major", "maj", "ionian"})

# Note letter, optional accidental, then the mode word. The accidental
# class is matched CASE-SENSITIVELY: "b" is flat, "B" is the note B, and
# there is no way to tell "AB minor" apart from "Ab minor" once case is
# folded. Flats must therefore be lowercase ``b`` (or the unicode ♭).
_KEYSCALE_RE = re.compile(r"^([A-Ga-g])([#b]?) *([A-Za-z]+)$")


def keyscale_to_camelot(keyscale: str) -> str:
    """Parse an ACE-Step ``metas.keyscale`` string into a Camelot key.

    Accepts the forms the generator actually emits — "A Minor",
    "C# Major", "Ab minor" — tolerant of case, surrounding and internal
    whitespace, ``-``/``_`` separators, and unicode ♯/♭ accidentals.
    Enharmonic spellings agree by construction (``G# Minor`` and
    ``Ab Minor`` are both 1A) because the lookup is keyed on pitch
    class, not on the letter.

    Raises ``ValueError`` naming the offending input when it cannot be
    parsed — never a silent fallback. A wrong key is worse than no
    ingest: it survives into the catalog and steers every harmonic pick
    that touches the track.
    """
    if not isinstance(keyscale, str) or not keyscale.strip():
        raise ValueError(
            f"unparseable keyscale: {keyscale!r} — expected something like "
            f"'A Minor', 'C# Major' or 'Ab minor'"
        )

    text = keyscale.replace("♯", "#").replace("♭", "b")
    # Collapse separators so "A  minor", "A-minor" and "a_MINOR" all
    # reduce to the single-space form the regex expects.
    text = re.sub(r"[\s_\-]+", " ", text).strip()

    match = _KEYSCALE_RE.match(text)
    if not match:
        raise ValueError(
            f"unparseable keyscale: {keyscale!r} — expected something like "
            f"'A Minor', 'C# Major' or 'Ab minor'"
        )

    letter, accidental, mode_word = match.groups()
    mode = mode_word.lower()
    if mode in _MINOR_MODES:
        table, side = _MINOR_PC_TO_NUMBER, "A"
    elif mode in _MAJOR_MODES:
        table, side = _MAJOR_PC_TO_NUMBER, "B"
    else:
        raise ValueError(
            f"unparseable keyscale: {keyscale!r} — mode {mode_word!r} is neither "
            f"major nor minor (accepted: "
            f"{', '.join(sorted(_MAJOR_MODES | _MINOR_MODES))})"
        )

    step = {"#": 1, "b": -1, "": 0}[accidental]
    pitch_class = (_NATURAL_PC[letter.upper()] + step) % 12
    return f"{table[pitch_class]}{side}"
