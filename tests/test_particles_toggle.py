"""Tests for when beat-reactive particles are drawn.

Particles were designed to give a STATIC artwork backdrop some life. Over
a video backdrop they read as dirt on the lens rather than atmosphere —
the footage already moves — so they default to OFF whenever video loops
are in play (2026-08-22, on the first healing render with real video
backgrounds).

The resolution is deliberately three-state: an explicit theme value wins
in BOTH directions, and only its absence falls back to the backdrop kind.
"""
from __future__ import annotations

import pytest


def _resolve(theme_value, video_loops):
    """Mirror of the resolution in generate_video."""
    particles_on = theme_value
    if particles_on is None:
        particles_on = video_loops is None
    return particles_on


class TestDefaultByBackdrop:

    def test_on_for_static_artwork(self):
        assert _resolve(None, None) is True

    def test_off_for_video_backdrop(self):
        assert _resolve(None, ["a loop"]) is False

    def test_off_even_for_a_single_loop(self):
        assert _resolve(None, ["one"]) is False


class TestExplicitThemeWins:

    def test_theme_can_force_particles_on_over_video(self):
        """An operator who wants them over footage must be able to say so."""
        assert _resolve(True, ["a loop"]) is True

    def test_theme_can_force_particles_off_over_artwork(self):
        assert _resolve(False, None) is False

    @pytest.mark.parametrize("loops", [None, ["a loop"]])
    def test_explicit_value_ignores_the_backdrop(self, loops):
        assert _resolve(True, loops) is True
        assert _resolve(False, loops) is False


class TestWiring:

    def test_generate_video_reads_the_theme_key(self):
        """The key must be 'particles' — a rename would silently re-enable them."""
        import inspect

        import main

        src = inspect.getsource(main.generate_video)
        assert 'theme.get("particles")' in src

    def test_draw_is_guarded(self):
        import inspect

        import main

        src = inspect.getsource(main.generate_video)
        i = src.index("if particles_on:")
        j = src.index("_draw_particles(")
        assert i < j, "the draw call must sit inside the guard"

    def test_particle_state_is_not_built_when_off(self):
        """Skipping the draw is not enough — the setup cost should go too."""
        import inspect

        import main

        src = inspect.getsource(main.generate_video)
        assert "particles = stamps = scatter_table = None" in src

    def test_default_theme_leaves_particles_unset(self):
        """No explicit key means the backdrop decides."""
        import main

        assert main.DEFAULT_THEME.get("particles") is None
