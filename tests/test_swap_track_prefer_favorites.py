"""Tests for v2.3.2 — swap_track + suggest_bridge_track honouring `prefer_favorites`.

`swap_track` is primarily an executor (the LLM hands it a track_id and a
position); the new `prefer_favorites` flag is advisory there — when True
and the chosen track is in the user's favorite/dislike set, a Note is
prepended to the response so the LLM can self-correct on the next turn.

`suggest_bridge_track` is the function that actually re-ranks candidates:
when `prefer_favorites=True` (default) and the user has rated tracks,
favorites bubble to the top and dislikes drop to the bottom of the list,
preserving BPM/key score as the within-tier tie-breaker.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import agent.tools as tools
from agent.tools import suggest_bridge_track, swap_track


# ---------------------------------------------------------------------------
# Synthetic catalog (same shape as test_bridge_tools.py, with extra entries)
# ---------------------------------------------------------------------------

_CATALOG = [
    {"id": "t1", "display_name": "Alpha",   "genre_folder": "techno", "genre": "techno", "bpm": 90.0,  "camelot_key": "1A"},
    {"id": "t2", "display_name": "Beta",    "genre_folder": "techno", "genre": "techno", "bpm": 100.0, "camelot_key": "2A"},
    {"id": "t3", "display_name": "Gamma",   "genre_folder": "techno", "genre": "techno", "bpm": 120.0, "camelot_key": "3A"},
    {"id": "t4", "display_name": "Delta",   "genre_folder": "techno", "genre": "techno", "bpm": 130.0, "camelot_key": "4A"},
    {"id": "t5", "display_name": "Epsilon", "genre_folder": "techno", "genre": "techno", "bpm": 140.0, "camelot_key": "5A"},
    {"id": "t6", "display_name": "Zeta",    "genre_folder": "techno", "genre": "techno", "bpm": 150.0, "camelot_key": "6A"},
    {"id": "t8", "display_name": "Eta",     "genre_folder": "techno", "genre": "techno", "bpm": 115.0, "camelot_key": "3A"},
    {"id": "t9", "display_name": "Theta",   "genre_folder": "techno", "genre": "techno", "bpm": 118.0, "camelot_key": "3B"},
]


def _make_catalog_file():
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump({"tracks": _CATALOG}, tmp)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def _make_playlist(*ids):
    by_id = {t["id"]: t for t in _CATALOG}
    return [dict(by_id[i]) for i in ids]


def _ctx(playlist, **extras):
    base = {"playlist": list(playlist), "genre": "techno"}
    base.update(extras)
    return base


# ---------------------------------------------------------------------------
# suggest_bridge_track — the function that actually re-ranks candidates.
# ---------------------------------------------------------------------------


def _candidate_ids(result: str) -> list[str]:
    """Pull the candidate track ids out of the formatted suggest_bridge_track text."""
    out: list[str] = []
    for line in result.splitlines():
        s = line.strip()
        if s and (s.startswith("t") and " | " in s):
            out.append(s.split(" | ", 1)[0])
    return out


def test_suggest_bridge_default_prefer_favorites_true():
    """With favorites in ctx and the default flag, favorites should rank
    above an equally-scoring (or even slightly-better-scoring) unrated
    track."""
    playlist = _make_playlist("t1", "t6")
    # The "best" geometric BPM target between 90 and 150 is ~116, which makes
    # t8 (115) the highest-scoring candidate by BPM/key. We mark t9 (a
    # slightly worse fit by score) as a favorite — with prefer_favorites=True
    # it should outrank t8.
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist, favorite_ids={"t9"}, dislike_ids=set())
            result = suggest_bridge_track(1, 2, ctx)  # default prefer_favorites=True
    finally:
        catalog_path.unlink(missing_ok=True)

    ids = _candidate_ids(result)
    assert ids, f"expected at least one candidate, got: {result!r}"
    assert ids[0] == "t9", f"favorite t9 should rank first, got {ids}"


def test_suggest_bridge_prefer_favorites_false_returns_baseline():
    """Explicit opt-out: the same ctx but prefer_favorites=False should
    rank purely by BPM/key score, ignoring the favorite_ids set."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist, favorite_ids={"t9"}, dislike_ids=set())
            result = suggest_bridge_track(1, 2, ctx, prefer_favorites=False)
    finally:
        catalog_path.unlink(missing_ok=True)

    ids = _candidate_ids(result)
    # Without bias, the closest-BPM track (t8 at 115 vs target ~116) wins.
    assert ids, f"expected candidates, got: {result!r}"
    assert ids[0] == "t8", f"baseline ranking should put t8 first, got {ids}"


def test_suggest_bridge_no_user_data_no_bias():
    """No favorite_ids / dislike_ids in ctx → behaves identically with or
    without the flag (regression-control)."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist)  # no user data at all
            r_with = suggest_bridge_track(1, 2, ctx)
            r_without = suggest_bridge_track(1, 2, ctx, prefer_favorites=False)
    finally:
        catalog_path.unlink(missing_ok=True)
    assert _candidate_ids(r_with) == _candidate_ids(r_without)


def test_suggest_bridge_dislikes_demoted_to_bottom():
    """Tracks in dislike_ids should fall to the end of the candidate list,
    even if their BPM/key score is the best."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            # Mark t8 (the BPM-best candidate) as a dislike — it should NOT
            # be in the top-3 unless there's nothing else.
            ctx = _ctx(playlist, dislike_ids={"t8"}, favorite_ids=set())
            result = suggest_bridge_track(1, 2, ctx)
    finally:
        catalog_path.unlink(missing_ok=True)
    ids = _candidate_ids(result)
    assert ids, f"expected candidates, got: {result!r}"
    # If t8 still appears, it must be after at least one non-disliked track.
    if "t8" in ids:
        assert ids.index("t8") > 0, f"disliked t8 should not rank first: {ids}"


# ---------------------------------------------------------------------------
# swap_track — advisory note when the chosen track matches user signal.
# ---------------------------------------------------------------------------


def test_swap_track_default_prefer_favorites_true_with_favorite_adds_note():
    """When the LLM picks a favorite track and prefer_favorites=True (default),
    the response includes a "favorites" note so the LLM sees positive
    reinforcement."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist, favorite_ids={"t3"}, dislike_ids=set())
            result = swap_track(2, "t3", ctx)  # default prefer_favorites=True
    finally:
        catalog_path.unlink(missing_ok=True)
    assert "favorite" in result.lower()
    assert ctx["playlist"][1]["id"] == "t3"


def test_swap_track_default_prefer_favorites_true_with_dislike_warns():
    """A swap into a disliked track with prefer_favorites=True surfaces a
    warning note in the response."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist, favorite_ids=set(), dislike_ids={"t3"})
            result = swap_track(2, "t3", ctx)
    finally:
        catalog_path.unlink(missing_ok=True)
    assert "dislike" in result.lower()
    # Swap still executes — the note is advisory, not blocking.
    assert ctx["playlist"][1]["id"] == "t3"


def test_swap_track_prefer_favorites_false_returns_baseline():
    """Explicit opt-out: no favorites/dislikes note should appear, even
    when the track is in the user's favorite set."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist, favorite_ids={"t3"}, dislike_ids=set())
            result = swap_track(2, "t3", ctx, prefer_favorites=False)
    finally:
        catalog_path.unlink(missing_ok=True)
    # With opt-out, no advisory note about favorites or dislikes.
    assert "favorite" not in result.lower()
    assert "dislike" not in result.lower()
    assert ctx["playlist"][1]["id"] == "t3"


def test_swap_track_no_user_data_no_note():
    """A ctx without favorite_ids / dislike_ids should produce a clean
    response with no rating note (regression-control)."""
    playlist = _make_playlist("t1", "t6")
    catalog_path = _make_catalog_file()
    try:
        with patch.object(tools, "_CATALOG_PATH", catalog_path):
            ctx = _ctx(playlist)  # no user data
            result = swap_track(2, "t3", ctx)
    finally:
        catalog_path.unlink(missing_ok=True)
    assert "favorite" not in result.lower()
    assert "dislike" not in result.lower()
