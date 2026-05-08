"""Unit tests for ``pick_next_track`` (v2.5.2 — full-catalog search tool)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.tools import pick_next_track


_FAKE_CATALOG = [
    {
        "id": "lo-1",
        "display_name": "Calm Drift",
        "bpm": 95,
        "camelot_key": "8A",
        "duration_sec": 180,
        "genre": "lofi",
        "suno": {"prompt": "soft, ambient lofi", "tags": ["chill", "ambient"]},
    },
    {
        "id": "lo-2",
        "display_name": "Glass City",
        "bpm": 100,
        "camelot_key": "9A",
        "duration_sec": 240,
        "genre": "lofi",
        "suno": {"prompt": "warm groove"},
    },
    {
        "id": "te-1",
        "display_name": "Iron Pulse",
        "bpm": 128,
        "camelot_key": "8A",
        "duration_sec": 360,
        "genre": "techno",
        "suno": {"tags": ["driving", "dark"]},
    },
    {
        "id": "te-2",
        "display_name": "Neon Drift",
        "bpm": 130,
        "camelot_key": "9A",
        "duration_sec": 360,
        "genre": "techno",
    },
    {
        "id": "te-3",
        "display_name": "Steel Lattice",
        "bpm": 132,
        "camelot_key": "10A",
        "duration_sec": 360,
        "genre": "techno",
    },
    {
        # Track without bpm — should be filtered out unconditionally.
        "id": "no-bpm",
        "display_name": "Mystery",
        "bpm": None,
        "camelot_key": "8A",
        "duration_sec": 200,
        "genre": "techno",
    },
]


@pytest.fixture
def patched_catalog():
    """Stub ``web.backend.pipeline.load_catalog`` to return our fixture."""
    import web.backend.pipeline as pipeline

    with patch.object(
        pipeline, "load_catalog", return_value=(_FAKE_CATALOG, ["lofi", "techno"])
    ):
        yield


def test_pick_next_track_returns_matches_in_bpm_range(patched_catalog):
    out = pick_next_track(127.0, 133.0, {})
    assert "Iron Pulse" in out
    assert "Neon Drift" in out
    assert "Steel Lattice" in out
    # Out-of-range tracks must not appear.
    assert "Calm Drift" not in out
    assert "Glass City" not in out


def test_pick_next_track_no_matches_returns_friendly_message(patched_catalog):
    out = pick_next_track(200.0, 220.0, {})
    assert "No tracks" in out
    assert "200" in out and "220" in out


def test_pick_next_track_in_key_ranked_above_out_of_key(patched_catalog):
    """Two tracks at the requested mid-BPM, only one in-key — that one
    must be ranked first."""
    out = pick_next_track(127.0, 131.0, {}, key="9A")
    rows = [line for line in out.splitlines() if line.startswith("|") and "---" not in line]
    # Header is the first row, data starts at row 2.
    data_rows = rows[1:]
    # First data row must be the 9A track.
    first_data = data_rows[0]
    assert "9A" in first_data
    assert "Neon Drift" in first_data


def test_pick_next_track_out_of_key_excluded_when_key_given_and_track_lacks_key(
    patched_catalog,
):
    """A catalog entry without ``camelot_key`` must NOT match a key-filtered
    request (otherwise we'd risk loading silence / corrupt entries)."""
    catalog_with_no_key = list(_FAKE_CATALOG) + [
        {"id": "x-1", "display_name": "No Key", "bpm": 128, "camelot_key": None, "duration_sec": 300},
    ]
    import web.backend.pipeline as pipeline

    with patch.object(
        pipeline, "load_catalog", return_value=(catalog_with_no_key, ["lofi", "techno"])
    ):
        out = pick_next_track(127.0, 131.0, {}, key="9A")
    assert "No Key" not in out


def test_pick_next_track_mood_filter_matches_suno_prompt(patched_catalog):
    out = pick_next_track(94.0, 105.0, {}, mood="ambient")
    assert "Calm Drift" in out
    # "Glass City" lacks "ambient" in its prompt/tags.
    assert "Glass City" not in out


def test_pick_next_track_mood_filter_matches_tags(patched_catalog):
    out = pick_next_track(127.0, 133.0, {}, mood="driving")
    assert "Iron Pulse" in out


def test_pick_next_track_drops_entries_without_bpm(patched_catalog):
    out = pick_next_track(125.0, 135.0, {})
    assert "Mystery" not in out


def test_pick_next_track_swaps_inverted_bounds(patched_catalog):
    """``bpm_min > bpm_max`` is auto-corrected so the agent doesn't have to."""
    out = pick_next_track(133.0, 127.0, {})
    assert "Iron Pulse" in out


def test_pick_next_track_caps_at_five_results(patched_catalog):
    """The catalog has 6 candidates with BPM at all values; result must
    list at most 5 rows of data."""
    big_catalog = []
    for i in range(15):
        big_catalog.append(
            {
                "id": f"t{i}",
                "display_name": f"T{i}",
                "bpm": 128.0,
                "camelot_key": "8A",
                "duration_sec": 300,
            }
        )
    import web.backend.pipeline as pipeline

    with patch.object(pipeline, "load_catalog", return_value=(big_catalog, [])):
        out = pick_next_track(125.0, 130.0, {})
    rows = [line for line in out.splitlines() if line.startswith("|") and "---" not in line]
    # Header + at most 5 data rows.
    assert len(rows) - 1 <= 5


def test_pick_next_track_invalid_bpm_returns_friendly_message(patched_catalog):
    out = pick_next_track("nope", "also-nope", {})  # type: ignore[arg-type]
    assert "numeric" in out.lower()
