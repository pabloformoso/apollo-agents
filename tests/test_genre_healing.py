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
  - main.py <-> agent/tools.py parity for the genre dicts, which both now
    re-export from agent/genre_config.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    """main.py and agent/tools.py must expose the same genre tables.

    They used to hold independent copies and drifted: tools.py sat a whole
    release without ``cocktail house`` or ``soul jazz``, which flattened the
    arranger's energy curve for those genres and wrote an empty theme into
    web-rendered sessions. Both now re-export agent/genre_config.py, so these
    tests double as a guard against anyone reintroducing a local literal.
    """

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

    def test_shared_genres_do_not_disagree(self):
        """Where both sides know a genre, the ranges must be identical."""
        from agent.tools import _BPM_GENRE_RANGES

        shared = set(_BPM_GENRE_RANGES) & set(BPM_GENRE_RANGES)
        for genre in shared:
            assert _BPM_GENRE_RANGES[genre] == BPM_GENRE_RANGES[genre], genre

    def test_bpm_range_key_sets_are_identical(self):
        """Not just the overlap — neither side may know a genre the other doesn't.

        A genre missing from tools.py falls back to the (60, 200) energy
        window, which silently squashes the arranger's dynamic range instead
        of failing. Key-set equality is what makes that unrepresentable.
        """
        from agent.tools import _BPM_GENRE_RANGES

        assert set(_BPM_GENRE_RANGES) == set(BPM_GENRE_RANGES)

    def test_theme_key_sets_are_identical(self):
        """A genre missing here writes ``{}`` into the draft session theme."""
        from agent.tools import GENRE_THEMES as TOOLS_THEMES

        assert set(TOOLS_THEMES) == set(GENRE_THEMES)

    def test_themes_are_complete_not_a_subset(self):
        """tools.py used to carry a 2-field subset of each theme.

        The render endpoint writes this dict straight into the draft
        session, so a trimmed copy shipped partial colors downstream.
        """
        from agent.tools import GENRE_THEMES as TOOLS_THEMES

        assert TOOLS_THEMES == GENRE_THEMES

    def test_both_sides_are_the_same_object(self):
        """Identity, not just equality — proves there is one source of truth.

        Equality would still pass if someone pasted a fresh literal back
        into either file; identity only holds while both import
        agent/genre_config.py.
        """
        from agent import genre_config
        from agent.tools import GENRE_THEMES as TOOLS_THEMES
        from agent.tools import _BPM_GENRE_RANGES

        assert _BPM_GENRE_RANGES is genre_config.BPM_GENRE_RANGES
        assert BPM_GENRE_RANGES is genre_config.BPM_GENRE_RANGES
        assert TOOLS_THEMES is genre_config.GENRE_THEMES
        assert GENRE_THEMES is genre_config.GENRE_THEMES


class TestGenreConfigIsDependencyFree:
    """The shared module must stay importable without the render stack.

    agent/tools.py imports it at module scope and the web backend reaches it
    from there; if it ever grows an ``import main`` (or any transitive pull of
    librosa/moviepy) that import cost lands on every agent process. Extracting
    the dicts was only worth doing because this stays true.
    """

    HEAVY = ("librosa", "moviepy", "main", "pydub", "soundfile")

    def test_imports_without_heavy_deps(self):
        # Tagged lines, not positional ones: "nothing leaked" prints an empty
        # value, and a bare blank line is indistinguishable from stray output.
        code = (
            "import sys, agent.genre_config as gc;"
            f"print('LEAKED:' + ','.join(m for m in {self.HEAVY!r} if m in sys.modules));"
            "print('COUNTS:%d %d' % (len(gc.BPM_GENRE_RANGES), len(gc.GENRE_THEMES)))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr

        def _tagged(tag: str) -> str:
            for line in proc.stdout.splitlines():
                if line.startswith(tag):
                    return line[len(tag):].strip()
            raise AssertionError(f"no {tag} line in: {proc.stdout!r}")

        assert _tagged("LEAKED:") == "", (
            f"genre_config pulled in {_tagged('LEAKED:')}"
        )
        # Sanity: the subprocess really loaded populated tables, so an import
        # that silently produced empty dicts can't pass as "nothing leaked".
        assert _tagged("COUNTS:") == f"{len(BPM_GENRE_RANGES)} {len(GENRE_THEMES)}"

    def test_every_theme_genre_has_a_bpm_range(self):
        """The two tables are edited together; a themed genre with no range
        still detects BPM against the wide default and mis-tags its catalog."""
        assert set(GENRE_THEMES) <= set(BPM_GENRE_RANGES)
