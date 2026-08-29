"""
Tests for the ``healing`` genre registration.

Healing is binaural meditation / drone material: no percussive transient for
librosa to lock onto, so raw detections land 2-4 octaves above the real pulse.
The genre therefore leans harder on ``BPM_GENRE_RANGES`` than the beat-driven
genres do, and its theme introduces a new artwork preset.

Covers:
  - BPM octave correction into the healing window (the failure mode that
    tagged aural drones at techno tempo before its range existed)
  - The one-octave-wide window invariant that makes the ladder unambiguous
  - Theme resolution through _get_session_theme, including the capital-H
    ``tracks/Healing`` folder name
  - The new ``healing-aura`` artwork prompt, and a guard that no genre
    theme points at a non-existent artwork style
  - main.py <-> agent/tools.py parity for the duplicated genre dicts
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np

import main
from main import (
    ARTWORK_PROMPTS,
    BPM_GENRE_RANGES,
    GENRE_THEMES,
    _get_session_theme,
    detect_bpm,
)


def _patched_detect(raw_bpm: float, genre_folder: str = "") -> float:
    """Run detect_bpm() with librosa mocked to return a fixed raw_bpm."""
    sr = 22050
    y = np.zeros(sr, dtype=np.float32)
    with patch("main.librosa.load", return_value=(y, sr)), \
         patch("main.librosa.beat.beat_track") as mock_bt:
        mock_bt.return_value = (np.array(raw_bpm), np.array([]))
        return detect_bpm("fake.wav", genre_folder)


class TestHealingBpmRange:

    def test_range_registered(self):
        assert BPM_GENRE_RANGES["healing"] == (50, 100)

    def test_quadrupled_detection_picks_quarter(self):
        """232 BPM on a drone is a 4x read of a 58 BPM pulse."""
        assert _patched_detect(232.0, "healing") == 58.0

    def test_doubled_detection_picks_half(self):
        """A 148 read halves to 74 — inside the window, near the midpoint."""
        assert _patched_detect(148.0, "healing") == 74.0

    def test_in_range_value_unchanged(self):
        """68 already sits in the window: keep it, don't ladder to 34 or 136."""
        assert _patched_detect(68.0, "healing") == 68.0

    def test_capital_folder_name_resolves(self):
        """The folder on disk is ``tracks/Healing`` — lookup must be case-insensitive.

        Regression guard: every other genre folder is lowercase, so a
        case-sensitive lookup would silently skip the ladder for this
        genre only and hand back raw 4x BPMs.
        """
        assert _patched_detect(232.0, "Healing") == 58.0

    def test_extreme_detection_surfaces_unclamped(self, capsys):
        """When no rung fits, the value must surface — never clamped to 100.

        Reaching this needs an absurd raw read (>400), because the ladder
        spans 4 octaves and the window is 1. 420 -> quarter is 105, still
        above the window, so 105 is reported as-is rather than lied down
        to the 100 ceiling.
        """
        assert _patched_detect(420.0, "healing") == 105.0
        assert "[BPM out-of-range]" in capsys.readouterr().out

    def test_plausible_detections_always_find_a_rung(self, capsys):
        """No realistic librosa read can escape the window.

        The ladder covers [raw/4, raw*4] — 4 octaves — and the window is
        one octave, so any raw between 12.5 and 400 has a rung inside it.
        This is what makes the range load-bearing for a genre whose raw
        detections routinely land at 3-4x the real pulse.
        """
        lo, hi = BPM_GENRE_RANGES["healing"]
        for raw in (13.0, 40.0, 58.0, 110.0, 175.0, 232.0, 301.0, 399.0):
            assert lo <= _patched_detect(raw, "healing") <= hi, raw
        assert "[BPM out-of-range]" not in capsys.readouterr().out

    def test_window_is_exactly_one_octave(self):
        """hi == 2*lo keeps the octave ladder unambiguous.

        The ladder tie-breaks on distance to the midpoint. A window wider
        than 2:1 lets two rungs qualify at once, so the picked octave stops
        being a property of the audio and becomes a property of where the
        midpoint happens to fall.
        """
        lo, hi = BPM_GENRE_RANGES["healing"]
        assert hi == 2 * lo

    def test_at_most_one_ladder_rung_lands_in_range(self):
        """Exercises the invariant above across the real candidate ladder."""
        lo, hi = BPM_GENRE_RANGES["healing"]
        for raw in (37.0, 58.0, 74.0, 99.0, 148.0, 232.0, 301.0):
            in_range = [
                raw * f for f in (0.25, 0.5, 1.0, 2.0, 4.0) if lo <= raw * f <= hi
            ]
            assert len(in_range) <= 1, f"raw={raw} matched {in_range}"


class TestHealingTheme:

    def test_theme_registered(self):
        assert GENRE_THEMES["healing"]["artwork_style"] == "healing-aura"

    def test_session_theme_applies_genre_colors(self):
        theme = _get_session_theme({"genre": "healing"})
        assert theme["title_color"] == "#9FE0D0"
        assert theme["waveform_color"] == [159, 224, 208]
        assert theme["artwork_style"] == "healing-aura"

    def test_session_theme_capital_genre(self):
        """``genre`` is stored title-cased ("Healing") by build_catalog."""
        theme = _get_session_theme({"genre": "Healing"})
        assert theme["artwork_style"] == "healing-aura"

    def test_session_override_beats_genre_default(self):
        theme = _get_session_theme(
            {"genre": "healing", "theme": {"title_color": "#FFFFFF"}}
        )
        assert theme["title_color"] == "#FFFFFF"
        # Untouched genre fields survive the partial override
        assert theme["artwork_style"] == "healing-aura"

    def test_theme_has_every_field_the_renderer_reads(self):
        """A partial theme silently inherits mismatched defaults downstream."""
        expected = {
            "artwork_style", "title_color", "title_stroke_color",
            "bg_color", "waveform_color", "particle_color",
            "bg_darken", "title_font_size",
        }
        assert expected <= set(GENRE_THEMES["healing"])


class TestHealingArtworkPrompt:

    def test_prompt_registered(self):
        assert "healing-aura" in ARTWORK_PROMPTS

    def test_prompt_interpolates_track_name(self):
        prompt = ARTWORK_PROMPTS["healing-aura"].format(track_name="Amber Bloom")
        assert "Amber Bloom" in prompt

    def test_prompt_excludes_text_and_people(self):
        """Every other preset ends with this constraint; artwork is a backdrop."""
        prompt = ARTWORK_PROMPTS["healing-aura"]
        assert "No text" in prompt
        assert "no people" in prompt

    def test_every_genre_theme_points_at_a_real_style(self):
        """_generate_artwork falls back to "abstract" on an unknown style.

        That fallback is silent, so a typo'd artwork_style costs a whole
        session's artwork before anyone notices. Assert the mapping closes.
        """
        for genre, theme in GENRE_THEMES.items():
            style = theme.get("artwork_style")
            assert style in ARTWORK_PROMPTS, f"{genre} -> unknown style {style!r}"


class TestAgentToolsParity:
    """agent/tools.py keeps its own copies of both dicts; they must agree."""

    def test_bpm_range_matches_main(self):
        from agent.tools import _BPM_GENRE_RANGES

        assert _BPM_GENRE_RANGES["healing"] == BPM_GENRE_RANGES["healing"]

    def test_theme_artwork_style_matches_main(self):
        from agent.tools import GENRE_THEMES as TOOLS_THEMES

        assert (
            TOOLS_THEMES["healing"]["artwork_style"]
            == GENRE_THEMES["healing"]["artwork_style"]
        )

    def test_theme_title_color_matches_main(self):
        from agent.tools import GENRE_THEMES as TOOLS_THEMES

        assert (
            TOOLS_THEMES["healing"]["title_color"]
            == GENRE_THEMES["healing"]["title_color"]
        )

    def test_bpm_ranges_are_fully_in_sync(self):
        """``_BPM_GENRE_RANGES`` must equal ``BPM_GENRE_RANGES`` exactly.

        This used to only check the overlap, which guarded against a
        value disagreeing but not against a genre going missing entirely
        — and that's exactly how the two dicts drifted: tools.py silently
        lost "lofi", "cocktail house", and "soul jazz" (measured
        2026-08-29) without a single test failing, because the old
        assertion iterated only the shared keys. Pin full equality — same
        key set, same values — so any future drift (missing genre or
        disagreeing window) fails loudly in CI instead of degrading the
        web generator's bpm default silently.
        """
        from agent.tools import _BPM_GENRE_RANGES

        assert set(_BPM_GENRE_RANGES) == set(BPM_GENRE_RANGES), (
            "key sets differ — only in agent.tools: "
            f"{sorted(set(_BPM_GENRE_RANGES) - set(BPM_GENRE_RANGES))}; "
            f"only in main: {sorted(set(BPM_GENRE_RANGES) - set(_BPM_GENRE_RANGES))}"
        )
        for genre, window in BPM_GENRE_RANGES.items():
            assert _BPM_GENRE_RANGES[genre] == window, genre

    def test_genre_themes_are_fully_in_sync(self):
        """agent.tools ``GENRE_THEMES`` must equal main's exactly — every field.

        The theme drift was worse than the BPM one: tools.py was missing
        the same three genres ("lofi", "cocktail house", "soul jazz") AND
        every entry it did have carried only 2 of the 8+ theme fields
        (measured 2026-08-29) — while the spot-checks above only ever
        compared healing's artwork_style and title_color, so none of it
        failed a test. Full equality matters more here than for the BPM
        windows: this copy is written into the draft session.json's
        "theme" block, which _get_session_theme applies as its TOP layer,
        above main.py's own genre defaults — a value that drifts in
        agent/tools.py doesn't merely degrade, it silently overrides the
        canonical theme at render time.
        """
        from agent.tools import GENRE_THEMES as TOOLS_THEMES

        assert set(TOOLS_THEMES) == set(GENRE_THEMES), (
            "key sets differ — only in agent.tools: "
            f"{sorted(set(TOOLS_THEMES) - set(GENRE_THEMES))}; "
            f"only in main: {sorted(set(GENRE_THEMES) - set(TOOLS_THEMES))}"
        )
        for genre, theme in GENRE_THEMES.items():
            assert TOOLS_THEMES[genre] == theme, genre
