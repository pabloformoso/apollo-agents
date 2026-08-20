"""Tests for the per-theme video background darkening.

Themes carried a single ``bg_darken`` used for BOTH backdrops, but the
two need very different treatment: AI artwork is a dark, low-contrast
still, while a video loop moves and can hold pure white highlights right
behind the title.

Measured on the first real video render (2026-08-20, healing over a
cosmic Veo clip): with the theme's artwork-tuned 0.85, stars behind the
title peaked at luminance **254** against a title at 197 — brighter than
the text meant to sit on top of them. The pipeline already had the right
value for video in ``VIDEO_BG_DARKEN`` (0.35, commented "darker =
overlays more readable"); the theme was simply overriding it.
"""
from __future__ import annotations

import pytest

from main import (
    DEFAULT_THEME,
    GENRE_THEMES,
    VIDEO_BG_DARKEN,
    _get_session_theme,
)


class TestDefault:

    def test_default_theme_carries_the_video_value(self):
        assert DEFAULT_THEME["video_bg_darken"] == VIDEO_BG_DARKEN

    def test_a_theme_without_it_inherits_the_default(self):
        """Backwards compatible: only healing opts in so far."""
        theme = _get_session_theme({"genre": "techno"})
        assert theme["video_bg_darken"] == VIDEO_BG_DARKEN

    def test_every_genre_resolves_a_video_darken(self):
        """No genre may reach the renderer without one — it is a KeyError
        at the call site, mid-render, after the audio is already mixed."""
        for genre in GENRE_THEMES:
            assert "video_bg_darken" in _get_session_theme({"genre": genre})


class TestHealing:

    def test_healing_opts_into_its_own_value(self):
        assert _get_session_theme({"genre": "healing"})["video_bg_darken"] == 0.45

    def test_it_is_darker_than_the_artwork_value(self):
        """The whole point: video must be pushed further down than artwork."""
        theme = _get_session_theme({"genre": "healing"})
        assert theme["video_bg_darken"] < theme["bg_darken"]

    def test_artwork_darkening_is_untouched(self):
        """Static-artwork renders must look exactly as they did before."""
        assert _get_session_theme({"genre": "healing"})["bg_darken"] == 0.85


class TestOverrides:

    def test_a_session_can_override_it(self):
        theme = _get_session_theme(
            {"genre": "healing", "theme": {"video_bg_darken": 0.2}}
        )
        assert theme["video_bg_darken"] == 0.2

    def test_overriding_one_does_not_move_the_other(self):
        theme = _get_session_theme(
            {"genre": "healing", "theme": {"bg_darken": 0.5}}
        )
        assert theme["bg_darken"] == 0.5
        assert theme["video_bg_darken"] == 0.45


@pytest.mark.parametrize("genre", list(GENRE_THEMES))
def test_values_stay_in_range(genre):
    """A multiplier outside 0..1 would brighten or invert the backdrop."""
    theme = _get_session_theme({"genre": genre})
    assert 0.0 < theme["video_bg_darken"] <= 1.0
