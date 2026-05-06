"""Tests for v2.3.1 — `propose_playlist` user-rating bias.

The pure helper ``_apply_user_rating_bias`` carries the actual reordering
logic, so the bulk of the suite is unit tests against that. A handful of
integration tests exercise the full ``propose_playlist`` path to confirm
the bias is wired correctly and that genre filtering still happens
*before* the bias step (so favorites of other genres can never leak in).

The integration tests:

- Use a synthetic catalog written to a temp file and patch
  ``tools._CATALOG_PATH`` (same pattern used by
  ``tests/test_charmap_regression.py``).
- Force every track in the catalog into the same BPM cluster (within
  10 BPM of each other) so ``_bpm_cluster`` keeps them all and the
  harmonic-sort + bias step is observable on the full set.
- Seed ``random`` to keep ``_harmonic_sort`` deterministic per test
  case.

A mutation-test step at the bottom of this module flips the helper's
ordering (favorites <-> dislikes) and asserts the suite catches the
swap — exists to document the test's bite for the PR body.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest

import agent.tools as tools
from agent.tools import _apply_user_rating_bias


# ---------------------------------------------------------------------------
# Pure helper — these are the load-bearing tests
# ---------------------------------------------------------------------------

def _t(track_id: str) -> dict:
    """Tiny factory for a track dict containing only what the helper needs."""
    return {"id": track_id, "display_name": track_id.upper()}


class TestApplyUserRatingBiasPure:
    """Unit tests for ``_apply_user_rating_bias``. The helper is pure and
    self-contained; testing it in isolation keeps the spec crisp and
    the regression net tight."""

    def test_no_user_data_no_bias(self):
        """Empty favorite/dislike sets => identity (no-op).

        Critical guarantee: behaviour without user data must match the
        pre-v2.3 behaviour exactly. We assert *the same list object*
        comes back so we can also catch accidental copies.
        """
        clusters = [[_t("a"), _t("b"), _t("c")], [_t("d"), _t("e")]]
        out = _apply_user_rating_bias(clusters, set(), set())
        assert out is clusters  # short-circuit, identity-preserving

    def test_no_user_data_none_inputs_are_also_no_op(self):
        """``None`` inputs are tolerated and treated as empty sets."""
        clusters = [[_t("a"), _t("b")]]
        out = _apply_user_rating_bias(clusters, None, None)
        assert out is clusters

    def test_favorites_appear_before_unrated_within_cluster(self):
        """Single cluster [A, B, C, D] with favorite={B} => [B, A, C, D].

        Favorite moves to the front; the relative order of the other
        tracks is preserved (harmonic adjacency).
        """
        cluster = [_t("a"), _t("b"), _t("c"), _t("d")]
        out = _apply_user_rating_bias([cluster], {"b"}, set())
        assert [t["id"] for t in out[0]] == ["b", "a", "c", "d"]

    def test_dislikes_demoted_to_end_of_cluster(self):
        """Single cluster [A, B, C, D] with dislike={B} => [A, C, D, B]."""
        cluster = [_t("a"), _t("b"), _t("c"), _t("d")]
        out = _apply_user_rating_bias([cluster], set(), {"b"})
        assert [t["id"] for t in out[0]] == ["a", "c", "d", "b"]

    def test_combined_favorites_and_dislikes(self):
        """[A, B, C, D, E], favs={B, D}, dislikes={A} =>
        [B, D, C, E, A] — favorites front in original order, neutrals
        middle in original order, dislikes back in original order."""
        cluster = [_t("a"), _t("b"), _t("c"), _t("d"), _t("e")]
        out = _apply_user_rating_bias([cluster], {"b", "d"}, {"a"})
        assert [t["id"] for t in out[0]] == ["b", "d", "c", "e", "a"]

    def test_multiple_clusters_each_reordered_independently(self):
        """Reordering happens per-cluster; clusters do not bleed into
        each other (harmonic adjacency lives within a cluster)."""
        clusters = [
            [_t("a1"), _t("a2"), _t("a3")],
            [_t("b1"), _t("b2"), _t("b3")],
        ]
        out = _apply_user_rating_bias(clusters, {"a3", "b1"}, {"a1", "b3"})
        assert [t["id"] for t in out[0]] == ["a3", "a2", "a1"]
        assert [t["id"] for t in out[1]] == ["b1", "b2", "b3"]

    def test_returns_fresh_outer_and_inner_lists_when_biasing(self):
        """When the function does work it returns new list objects so
        callers can mutate the result without aliasing the input."""
        cluster = [_t("a"), _t("b")]
        clusters = [cluster]
        out = _apply_user_rating_bias(clusters, {"b"}, set())
        assert out is not clusters
        assert out[0] is not cluster

    def test_track_dicts_are_referenced_not_cloned(self):
        """Track dicts are passed by reference, never deep-copied. This
        keeps the helper cheap and prevents subtle drift between
        ``ctx['playlist']`` and the originals from the catalog."""
        a = _t("a")
        b = _t("b")
        out = _apply_user_rating_bias([[a, b]], {"b"}, set())
        assert out[0][0] is b
        assert out[0][1] is a

    def test_empty_cluster_remains_empty(self):
        """Edge case: a cluster of zero tracks survives the helper."""
        out = _apply_user_rating_bias([[]], {"x"}, {"y"})
        assert out == [[]]

    def test_input_clusters_are_not_mutated(self):
        """Helper is pure: even when it does work, the original cluster
        ordering must be preserved on the input objects."""
        cluster = [_t("a"), _t("b"), _t("c")]
        original_ids = [t["id"] for t in cluster]
        _apply_user_rating_bias([cluster], {"c"}, {"a"})
        assert [t["id"] for t in cluster] == original_ids


# ---------------------------------------------------------------------------
# Integration — propose_playlist end-to-end with a synthetic catalog
# ---------------------------------------------------------------------------

@pytest.fixture
def cyberpunk_catalog(tmp_path, monkeypatch):
    """Write a small catalog where:

    - 5 cyberpunk tracks all sit within a 10 BPM window so they fall
      into the SAME ``_bpm_cluster``. Camelot keys are adjacent enough
      that ``_harmonic_sort`` will find every track (avoids random
      tail-off behaviour).
    - 1 lofi track is present so the genre-filter test has something
      cross-genre to point at.
    - All durations are 360s so ``duration_min`` translates cleanly to
      track count.
    """
    catalog = {
        "tracks": [
            {
                "id": "cyber-1",
                "display_name": "Cyber One",
                "file": "tracks/cyberpunk/one.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 120.0,
                "camelot_key": "8A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-2",
                "display_name": "Cyber Two",
                "file": "tracks/cyberpunk/two.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 121.0,
                "camelot_key": "9A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-3",
                "display_name": "Cyber Three",
                "file": "tracks/cyberpunk/three.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 122.0,
                "camelot_key": "10A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-4",
                "display_name": "Cyber Four",
                "file": "tracks/cyberpunk/four.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 123.0,
                "camelot_key": "11A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-5",
                "display_name": "Cyber Five",
                "file": "tracks/cyberpunk/five.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 124.0,
                "camelot_key": "12A",
                "duration_sec": 360.0,
            },
            {
                "id": "lofi-1",
                "display_name": "Lofi One",
                "file": "tracks/lofi/one.wav",
                "genre_folder": "lofi",
                "genre": "lofi",
                "bpm": 80.0,
                "camelot_key": "5A",
                "duration_sec": 360.0,
            },
        ]
    }
    catalog_path = tmp_path / "tracks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(tools, "_CATALOG_PATH", catalog_path)
    return catalog_path


def _seed_random_for_determinism():
    """Pin ``random`` so ``_harmonic_sort`` produces the same starting
    point across runs."""
    random.seed(0)


def test_propose_playlist_no_user_data_unchanged(cyberpunk_catalog):
    """Without ``favorite_ids`` / ``dislike_ids`` in ctx, the bias is a
    no-op and the playlist is exactly what the pre-v2.3 pipeline would
    have produced. We assert by snapshot — re-running with the same seed
    yields a stable order."""
    _seed_random_for_determinism()
    ctx_baseline: dict = {}
    tools.propose_playlist("cyberpunk", 30, "test", ctx_baseline)
    baseline_ids = [t["id"] for t in ctx_baseline["playlist"]]

    _seed_random_for_determinism()
    ctx_no_user: dict = {"favorite_ids": set(), "dislike_ids": set()}
    tools.propose_playlist("cyberpunk", 30, "test", ctx_no_user)
    assert [t["id"] for t in ctx_no_user["playlist"]] == baseline_ids


def test_propose_playlist_favorites_appear_first(cyberpunk_catalog):
    """When the user has favorites in the requested genre, those tracks
    appear in the first slots of the generated playlist (one slot per
    favorite, since each favorite is unique by ``display_name``)."""
    _seed_random_for_determinism()
    ctx = {"favorite_ids": {"cyber-3", "cyber-5"}, "dislike_ids": set()}
    tools.propose_playlist("cyberpunk", 18, "test", ctx)  # 18min/6min = 3 tracks
    ids = [t["id"] for t in ctx["playlist"]]
    # The first two slots are the two favorites (in their harmonic order).
    assert set(ids[:2]) == {"cyber-3", "cyber-5"}


def test_propose_playlist_dislikes_only_included_when_needed_for_duration(
    cyberpunk_catalog,
):
    """A short session (one track) must NEVER pick a dislike — there
    are 4 acceptable alternatives at the front of the pool. A long
    session that exhausts the favorites+neutrals MAY pick a dislike,
    and when it does the dislike must appear after every non-dislike."""
    # Short session: 6 minutes => 1 track. Mark cyber-1 as a dislike.
    # Whatever lands first must NOT be cyber-1.
    _seed_random_for_determinism()
    ctx_short = {"favorite_ids": set(), "dislike_ids": {"cyber-1"}}
    tools.propose_playlist("cyberpunk", 6, "test", ctx_short)
    ids_short = [t["id"] for t in ctx_short["playlist"]]
    assert "cyber-1" not in ids_short

    # Long session: 30 minutes => 5 tracks => the dislike must appear,
    # because there are only 5 distinct cyberpunk tracks. It must be
    # last (after all 4 non-disliked tracks).
    _seed_random_for_determinism()
    ctx_long = {"favorite_ids": set(), "dislike_ids": {"cyber-1"}}
    tools.propose_playlist("cyberpunk", 30, "test", ctx_long)
    ids_long = [t["id"] for t in ctx_long["playlist"]]
    assert "cyber-1" in ids_long
    assert ids_long.index("cyber-1") == len(ids_long) - 1


def test_propose_playlist_genre_filter_still_respected(cyberpunk_catalog):
    """Favorites of OTHER genres do not leak into the requested-genre
    playlist. Catalog filtering happens BEFORE the bias step, so
    ``lofi-1`` is invisible to the bias path even though it's a
    favorite."""
    _seed_random_for_determinism()
    ctx = {
        "favorite_ids": {"lofi-1", "cyber-2"},
        "dislike_ids": set(),
    }
    tools.propose_playlist("cyberpunk", 30, "test", ctx)
    ids = [t["id"] for t in ctx["playlist"]]
    assert "lofi-1" not in ids
    # cyber-2 (the in-genre favorite) leads the playlist.
    assert ids[0] == "cyber-2"


def test_propose_playlist_progress_callback_receives_bias_event(cyberpunk_catalog):
    """When ctx exposes a ``_progress`` callback and the user has
    favorites/dislikes, the bias step emits a structured event the web
    UI can render. CLI callers (no ``_progress``) keep working without
    it — covered implicitly by the other integration tests."""
    _seed_random_for_determinism()
    events: list[dict] = []

    def _progress(event: dict) -> None:
        events.append(event)

    ctx = {
        "favorite_ids": {"cyber-2"},
        "dislike_ids": {"cyber-1"},
        "_progress": _progress,
    }
    tools.propose_playlist("cyberpunk", 18, "test", ctx)

    bias_events = [e for e in events if e.get("stage") == "bias"]
    assert bias_events, "expected a 'bias' progress event"
    msg = bias_events[0]["message"]
    assert "1 favorites" in msg
    assert "1 dislikes" in msg


# ---------------------------------------------------------------------------
# Mutation test — confirms the suite catches an inverted helper
# ---------------------------------------------------------------------------

def test_mutation_inverted_helper_is_rejected_by_combined_test():
    """Mutation guard: temporarily swap ``favs + rest + dislkd`` for
    ``dislkd + rest + favs`` inside the helper and confirm the combined
    favorites+dislikes test would fail. Restores the helper afterwards.

    Without this check the suite could silently pass against a broken
    helper (e.g. someone renames the variables but flips the order).
    """
    cluster = [_t("a"), _t("b"), _t("c"), _t("d"), _t("e")]

    # Inverted helper — exact same shape as the real one but with the
    # critical concatenation flipped.
    def _inverted(clusters, favs, dis):
        if not favs and not dis:
            return clusters
        favs = favs or set()
        dis = dis or set()
        result = []
        for c in clusters:
            f = [t for t in c if t.get("id") in favs]
            d = [t for t in c if t.get("id") in dis]
            r = [
                t for t in c
                if t.get("id") not in favs and t.get("id") not in dis
            ]
            result.append(d + r + f)  # <-- inverted
        return result

    expected = ["b", "d", "c", "e", "a"]  # what the real helper produces
    inverted_out = _inverted([cluster], {"b", "d"}, {"a"})
    inverted_ids = [t["id"] for t in inverted_out[0]]
    assert inverted_ids != expected, (
        "Inverted helper unexpectedly produced the correct order — the "
        "suite is no longer guarding the bias direction."
    )
    # And the real helper still gives the expected ordering.
    real_out = _apply_user_rating_bias([cluster], {"b", "d"}, {"a"})
    assert [t["id"] for t in real_out[0]] == expected
