"""One definition per genre, and nothing half-defined.

A genre used to live in six places across three files, and five of the six
omissions failed SILENTLY: no BPM window poisons tempo matching, no theme
falls back to `abstract` without a word, no style prompt makes ACE generate
off-genre, no neighbours means an endless set cannot widen. Only the theme
mirror had a parity test — and it caught a real drift on 2026-09-08.

These tests replace six-way manual vigilance with one contract: every genre
the catalog actually uses is COMPLETE, and the four legacy names are views
of the same data rather than copies of it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from agent import genres, live_engine, tools  # noqa: E402

CATALOG = ROOT / "tracks" / "tracks.json"
needs_catalog = pytest.mark.skipif(
    not CATALOG.exists(), reason="tracks.json is not in git — main checkout only"
)


@pytest.fixture(autouse=True)
def _no_installation_genres():
    """Every test starts from the shipped defaults alone."""
    genres.register_loader(None)
    yield
    genres.register_loader(None)


def _catalog_folders() -> set[str]:
    raw = json.loads(CATALOG.read_text())
    tracks = raw["tracks"] if isinstance(raw, dict) else raw
    return {
        (t.get("genre_folder") or "").strip().lower()
        for t in tracks
        if t.get("genre_folder")
    }


# --- the contract ---------------------------------------------------------

@needs_catalog
def test_every_catalog_genre_is_completely_defined():
    """The one assertion that replaces six-way manual vigilance."""
    incomplete = {
        g: genres.missing_fields(g)
        for g in sorted(_catalog_folders())
        if not genres.is_defined(g)
    }
    assert not incomplete, f"genres missing fields: {incomplete}"


def test_no_shipped_genre_is_half_defined():
    """A partial default is the silent failure this module exists to stop."""
    partial = {
        g: genres.missing_fields(g)
        for g in genres.GENRE_DEFAULTS
        # 'lofi' is a legacy alias of 'lofi - ambient': no catalog folder
        # uses it, and it deliberately has no neighbours, so an unmapped
        # genre simply cannot widen.
        if g != "lofi" and not genres.is_defined(g)
    }
    assert not partial, f"incomplete definitions: {partial}"


def test_every_theme_points_at_a_real_artwork_template():
    """An unknown artwork_style falls back to 'abstract' SILENTLY."""
    for g, theme in genres.themes().items():
        style = theme.get("artwork_style")
        assert style in main.ARTWORK_PROMPTS, f"{g} -> unknown style {style!r}"


def test_neighbours_are_symmetric():
    for g, ns in genres.neighbours().items():
        for n in ns:
            assert g in genres.neighbours().get(n, frozenset()), (
                f"{g} -> {n} is not mirrored back"
            )


def test_the_calm_cluster_cannot_reach_a_dancefloor():
    """Regression for the 2026-09-07 broadcast: techno on a meditation set."""
    loud = {"techno", "synthware", "cyberpunk", "deep house"}
    for calm in ("healing", "aural", "lofi - ambient"):
        assert not (genres.neighbours()[calm] & loud), calm


# --- the legacy names are VIEWS, not copies -------------------------------

def test_the_two_bpm_mirrors_are_the_same_object():
    """They drifted as literals. Identity is the strongest guarantee."""
    assert main.BPM_GENRE_RANGES is tools._BPM_GENRE_RANGES


def test_the_two_theme_mirrors_are_the_same_object():
    assert main.GENRE_THEMES is tools.GENRE_THEMES


def test_the_views_are_read_only():
    """These used to be dicts — a caller could reconfigure the process."""
    with pytest.raises(TypeError):
        main.BPM_GENRE_RANGES["x"] = (1, 2)  # type: ignore[index]


def test_the_views_still_behave_like_dicts():
    """~40 call sites use .get/.items/in/[] and must not change."""
    assert main.BPM_GENRE_RANGES.get("healing") == (50, 100)
    assert "healing" in main.BPM_GENRE_RANGES
    assert main.BPM_GENRE_RANGES["healing"] == (50, 100)
    assert dict(main.BPM_GENRE_RANGES) == main.BPM_GENRE_RANGES
    assert len(list(main.GENRE_THEMES.items())) == len(genres.themes())


def test_values_survived_the_consolidation():
    """Pinned so a future edit to a window is deliberate, not incidental.

    A changed BPM window silently re-tags a whole genre on the next
    catalog build.
    """
    assert main.BPM_GENRE_RANGES["healing"] == (50, 100)
    assert main.BPM_GENRE_RANGES["aural"] == (48, 96)
    assert main.BPM_GENRE_RANGES["synthware"] == (85, 170)
    assert main.GENRE_THEMES["healing"]["artwork_style"] == "healing-aura"
    assert tools.GENRE_STYLE_PROMPTS["healing"].startswith("healing meditation")
    assert "synthware" not in live_engine.GENRE_NEIGHBOURS["soul jazz"]


# --- layer 2: genres this installation added ------------------------------

def _added(**over):
    base = {
        "bpm": (55, 110),
        "theme": {"artwork_style": "abstract"},
        "style_prompt": "my own sound",
        "neighbours": frozenset({"healing"}),
    }
    base.update(over)
    return {"my ambient": base}


def test_an_added_genre_appears_without_a_restart():
    """The point of the whole layer: the UI adds one, the process sees it."""
    assert "my ambient" not in main.BPM_GENRE_RANGES
    genres.register_loader(lambda: _added())
    assert main.BPM_GENRE_RANGES["my ambient"] == (55, 110)
    assert "my ambient" in tools.GENRE_THEMES
    assert tools.GENRE_STYLE_PROMPTS["my ambient"] == "my own sound"


def test_an_added_genre_gets_its_adjacency_mirrored_back():
    """A UI cannot be expected to also edit the genre on the other side.

    Left one-way, widening works in one direction only — a set anchored on
    healing could reach the new genre and never come back, which is exactly
    the one-way door that put techno on a meditation broadcast.
    """
    genres.register_loader(lambda: _added())
    assert "my ambient" in live_engine.GENRE_NEIGHBOURS["healing"]


def test_an_override_is_merged_per_field_not_per_genre():
    """Changing one number must not require re-supplying everything."""
    genres.register_loader(lambda: {"healing": {"bpm": (40, 80)}})
    assert main.BPM_GENRE_RANGES["healing"] == (40, 80)
    # ...and the shipped theme and prompt survive.
    assert main.GENRE_THEMES["healing"]["artwork_style"] == "healing-aura"
    assert tools.GENRE_STYLE_PROMPTS["healing"].startswith("healing meditation")


def test_a_null_field_does_not_erase_a_shipped_one():
    """A UI that sends a partial row must not blank out a default."""
    genres.register_loader(lambda: {"healing": {"bpm": None, "theme": None}})
    assert main.BPM_GENRE_RANGES["healing"] == (50, 100)
    assert main.GENRE_THEMES["healing"]["artwork_style"] == "healing-aura"


def test_a_broken_loader_degrades_to_the_defaults():
    """A broken database must not take the CLI down — defaults still work."""
    def boom():
        raise RuntimeError("no database here")

    genres.register_loader(boom)
    assert main.BPM_GENRE_RANGES["healing"] == (50, 100)
    assert len(main.BPM_GENRE_RANGES) == len(genres.GENRE_DEFAULTS)


def test_a_blank_genre_name_is_ignored():
    genres.register_loader(lambda: {"   ": {"bpm": (1, 2)}})
    assert len(main.BPM_GENRE_RANGES) == len(genres.GENRE_DEFAULTS)


def test_an_added_name_is_normalised_like_every_other_lookup():
    genres.register_loader(lambda: {"  My AMBIENT  ": {"bpm": (55, 110)}})
    assert main.BPM_GENRE_RANGES["my ambient"] == (55, 110)


def test_no_loader_means_defaults_only():
    assert dict(genres.all_genres()) == dict(genres.GENRE_DEFAULTS)
