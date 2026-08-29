"""Tests for `agent.keyscale.keyscale_to_camelot` — ACE-Step's
`metas.keyscale` string into the Camelot key the catalog stores.

The full 24-row wheel, both enharmonic spellings of every black note,
tolerance of the shapes an LM actually emits, and a round-trip against
`agent/generative/scales.py` so the two directions cannot drift.
"""
from __future__ import annotations

import pytest

from agent.generative import scales
from agent.keyscale import (
    _MAJOR_PC_TO_NUMBER,
    _MINOR_PC_TO_NUMBER,
    keyscale_to_camelot,
)

# The wheel exactly as the ACE-Step spec's table states it
# (docs/ACE-STEP-API-SPEC.md §5): minor -> A-side, major -> B-side.
MINOR_ROWS = [
    ("Ab Minor", "1A"), ("G# Minor", "1A"),
    ("Eb Minor", "2A"), ("D# Minor", "2A"),
    ("Bb Minor", "3A"), ("A# Minor", "3A"),
    ("F Minor", "4A"),
    ("C Minor", "5A"),
    ("G Minor", "6A"),
    ("D Minor", "7A"),
    ("A Minor", "8A"),
    ("E Minor", "9A"),
    ("B Minor", "10A"),
    ("F# Minor", "11A"), ("Gb Minor", "11A"),
    ("C# Minor", "12A"), ("Db Minor", "12A"),
]

MAJOR_ROWS = [
    ("B Major", "1B"),
    ("F# Major", "2B"), ("Gb Major", "2B"),
    ("Db Major", "3B"), ("C# Major", "3B"),
    ("Ab Major", "4B"), ("G# Major", "4B"),
    ("Eb Major", "5B"), ("D# Major", "5B"),
    ("Bb Major", "6B"), ("A# Major", "6B"),
    ("F Major", "7B"),
    ("C Major", "8B"),
    ("G Major", "9B"),
    ("D Major", "10B"),
    ("A Major", "11B"),
    ("E Major", "12B"),
]


class TestTable:
    @pytest.mark.parametrize(("keyscale", "expected"), MINOR_ROWS)
    def test_minor_side(self, keyscale, expected):
        assert keyscale_to_camelot(keyscale) == expected

    @pytest.mark.parametrize(("keyscale", "expected"), MAJOR_ROWS)
    def test_major_side(self, keyscale, expected):
        assert keyscale_to_camelot(keyscale) == expected

    def test_all_24_camelot_keys_are_reachable(self):
        produced = {keyscale_to_camelot(k) for k, _ in MINOR_ROWS + MAJOR_ROWS}
        expected = {f"{n}{side}" for n in range(1, 13) for side in ("A", "B")}
        assert produced == expected

    def test_enharmonics_agree(self):
        # Same pitch, different spelling -> the same Camelot cell.
        for sharp, flat in [
            ("G# Minor", "Ab Minor"), ("D# Minor", "Eb Minor"),
            ("A# Minor", "Bb Minor"), ("F# Minor", "Gb Minor"),
            ("C# Minor", "Db Minor"), ("C# Major", "Db Major"),
            ("G# Major", "Ab Major"), ("D# Major", "Eb Major"),
            ("A# Major", "Bb Major"), ("F# Major", "Gb Major"),
        ]:
            assert keyscale_to_camelot(sharp) == keyscale_to_camelot(flat), sharp


class TestTolerance:
    @pytest.mark.parametrize("form", [
        "A Minor", "a minor", "A MINOR", "  A   Minor  ", "A-minor", "a_MINOR",
        "AMinor", "A min", "A Aeolian", "A\tminor",
    ])
    def test_minor_spellings(self, form):
        assert keyscale_to_camelot(form) == "8A"

    @pytest.mark.parametrize("form", ["C Major", "c major", "C maj", "C Ionian", "C-MAJOR"])
    def test_major_spellings(self, form):
        assert keyscale_to_camelot(form) == "8B"

    def test_unicode_accidentals(self):
        assert keyscale_to_camelot("C♯ Major") == "3B"   # C sharp
        assert keyscale_to_camelot("A♭ Minor") == "1A"   # A flat


class TestRefusals:
    @pytest.mark.parametrize("garbage", [
        "", "   ", "H Minor", "A Dorian", "Minor", "A", "8A", "A Minorish",
        "banana", "A# # Minor", "Am", "AM", "1 Minor", None, 42, [],
    ])
    def test_unparseable_raises(self, garbage):
        with pytest.raises(ValueError):
            keyscale_to_camelot(garbage)

    def test_message_names_the_offending_input(self):
        with pytest.raises(ValueError, match="Dorian"):
            keyscale_to_camelot("A Dorian")
        with pytest.raises(ValueError, match="banana"):
            keyscale_to_camelot("banana")

    def test_ambiguous_m_suffix_is_refused_not_guessed(self):
        # "Am"/"AM" differ only by case, and this parser is case-tolerant
        # by contract — guessing either way would sometimes store the
        # wrong key, which then steers every harmonic pick.
        for form in ("Am", "AM", "Cm"):
            with pytest.raises(ValueError):
                keyscale_to_camelot(form)


class TestConsistencyWithScales:
    """`agent/generative/scales.py` walks Camelot -> pitch classes; this
    module walks the name back to Camelot. They must agree."""

    def test_round_trip_through_scales_key_name(self):
        for number in range(1, 13):
            for side in ("A", "B"):
                key = f"{number}{side}"
                assert keyscale_to_camelot(scales.key_name(key)) == key

    def test_tables_are_exact_inverses(self):
        assert _MINOR_PC_TO_NUMBER == {pc: n for n, pc in scales._MINOR_TONICS.items()}
        assert _MAJOR_PC_TO_NUMBER == {pc: n for n, pc in scales._MAJOR_TONICS.items()}

    def test_tonic_is_in_its_own_scale(self):
        # Cross-check through the other module's real API: the parsed
        # key's scale must contain the pitch class we parsed from.
        for keyscale, camelot in MINOR_ROWS + MAJOR_ROWS:
            assert keyscale_to_camelot(keyscale) == camelot
            pcs = scales.camelot_scale(camelot)
            tonic = scales._MINOR_TONICS if camelot.endswith("A") else scales._MAJOR_TONICS
            assert tonic[int(camelot[:-1])] in pcs
