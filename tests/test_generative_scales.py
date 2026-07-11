"""M-3: Camelot -> scale mapping, guardrail validation, chromatic escape hatch.
M-6: genre packs — every starter must validate and carry a brief."""

import pytest

from agent.generative.genres import GENRE_PACKS, genre_prompt_section
from agent.generative.scales import camelot_scale, key_name, pc_name
from agent.generative.spec import PatternSpec, SpecError

from tests.test_generative_spec import valid_spec_dict

A_MINOR = {9, 11, 0, 2, 4, 5, 7}  # A B C D E F G


# --- camelot_scale ------------------------------------------------------------

def test_8a_is_a_minor_plus_leading_tone():
    assert camelot_scale("8A") == A_MINOR | {8}  # + G#


def test_8b_is_c_major():
    assert camelot_scale("8B") == {0, 2, 4, 5, 7, 9, 11}


def test_all_24_keys_have_valid_scales():
    for n in range(1, 13):
        for side in "AB":
            scale = camelot_scale(f"{n}{side}")
            assert len(scale) == (8 if side == "A" else 7)  # minor gets the raised 7th


def test_adjacent_camelot_keys_share_all_but_one_pc():
    # The whole point of the Camelot wheel: neighbours are one accidental apart.
    for n in range(1, 13):
        neighbour = n % 12 + 1
        overlap = camelot_scale(f"{n}B") & camelot_scale(f"{neighbour}B")
        assert len(overlap) == 6, f"{n}B vs {neighbour}B"


def test_relative_major_minor_share_natural_scale():
    # 8A (Am) natural notes == 8B (C) notes; 8A only adds G#
    assert camelot_scale("8A") - {8} == camelot_scale("8B")


@pytest.mark.parametrize("bad", ["", "13A", "0B", "8C", "AA"])
def test_invalid_key_raises(bad):
    with pytest.raises(SpecError):
        camelot_scale(bad)


def test_key_and_pc_names():
    assert key_name("8A") == "A minor"
    assert key_name("8B") == "C major"
    assert pc_name(8) == "G#"


# --- guardrails in PatternSpec -------------------------------------------------

def test_in_scale_spec_passes():
    PatternSpec.from_dict(valid_spec_dict())  # 8A, all-diatonic — must not raise


def test_out_of_scale_bass_rejected():
    d = valid_spec_dict()
    d["roles"]["bass"] = {"notes": [[0, "C#2", 1.0]], "vel": 80}  # C# not in A minor
    with pytest.raises(SpecError, match="outside 8A"):
        PatternSpec.from_dict(d)


def test_out_of_scale_chord_rejected():
    d = valid_spec_dict()
    d["roles"]["pad"] = {"chord": "Dbmaj7"}  # Db not in A minor
    with pytest.raises(SpecError, match="outside 8A"):
        PatternSpec.from_dict(d)


def test_harmonic_minor_leading_tone_allowed():
    d = valid_spec_dict()
    d["roles"]["pad"] = {"chord": "E7"}  # G# = raised 7th of Am — idiomatic V7
    PatternSpec.from_dict(d)  # must not raise


def test_chromatic_escape_hatch():
    d = valid_spec_dict(chromatic=True)
    d["roles"]["bass"] = {"notes": [[0, "C#2", 1.0]], "vel": 80}
    spec = PatternSpec.from_dict(d)
    assert spec.chromatic is True


def test_chromatic_must_be_boolean():
    with pytest.raises(SpecError, match="chromatic"):
        PatternSpec.from_dict(valid_spec_dict(chromatic="yes"))


def test_guardrail_error_names_the_offender():
    d = valid_spec_dict()
    d["roles"]["bass"] = {"notes": [[0, "D#2", 1.0]], "vel": 80}
    with pytest.raises(SpecError, match="D#.*A minor"):
        PatternSpec.from_dict(d)


# --- genre packs (M-6) -----------------------------------------------------------

def test_every_genre_starter_validates():
    for genre, pack in GENRE_PACKS.items():
        spec = PatternSpec.from_dict(pack["starter"])
        assert spec.reason, genre


def test_every_genre_has_a_brief_with_tempo_guidance():
    for genre, pack in GENRE_PACKS.items():
        assert "GENRE" in pack["brief"], genre
        assert "BPM" in pack["brief"], genre


def test_genre_prompt_section_embeds_brief_and_example():
    section = genre_prompt_section("lofi")
    assert "lofi" in section
    assert '"bpm": 78' in section  # the starter doubles as the few-shot example


def test_unknown_genre_gives_empty_section():
    assert genre_prompt_section("polka") == ""
