"""Tests for v2.5.0 — environment-aware soft bias in ``propose_playlist``.

The pure helper ``_apply_environment_bias`` carries the actual reordering
logic (BPM-based proxy for energy archetype). Most of this suite hits the
helper directly so the spec stays crisp; the bottom of the file contains
a single integration test that confirms the bias is wired into
``propose_playlist`` AFTER the user-rating bias (favorites stay first).

Conventions match ``tests/test_propose_playlist_bias.py``:
- a ``_t(track_id, bpm=)`` factory keeps fixtures terse;
- the integration test seeds ``random`` via the helper used in v2.3.1.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import agent.tools as tools
from agent.tools import (
    _apply_environment_bias,
    _classify_environment,
)


# ---------------------------------------------------------------------------
# Pure helper — these are the load-bearing tests
# ---------------------------------------------------------------------------

def _t(track_id: str, bpm: float | None = 0.0) -> dict:
    """Tiny factory for a track dict. ``bpm=None`` simulates a catalog
    entry with the BPM column unset (which the helper must tolerate)."""
    return {"id": track_id, "display_name": track_id.upper(), "bpm": bpm}


class TestClassifyEnvironment:
    """``_classify_environment`` is the deterministic glue between free
    text and an energy archetype. We pin the boundaries explicitly."""

    def test_empty_returns_none(self):
        assert _classify_environment("") is None
        assert _classify_environment(None) is None
        assert _classify_environment("   ") is None

    def test_unspecified_sentinel_returns_none(self):
        assert _classify_environment("unspecified") is None
        assert _classify_environment("UNSPECIFIED") is None
        assert _classify_environment("  unspecified  ") is None

    def test_high_energy_keywords(self):
        for kw in ("loud", "crowded", "club", "bar", "party", "warehouse", "festival"):
            assert _classify_environment(kw) == "high", kw

    def test_low_energy_keywords(self):
        for kw in ("intimate", "listening", "home", "phones", "headphones", "quiet"):
            assert _classify_environment(kw) == "low", kw

    def test_mid_energy_keywords(self):
        for kw in ("outdoor", "cafe", "morning", "background", "casual"):
            assert _classify_environment(kw) == "mid", kw

    def test_unknown_keyword_returns_none(self):
        assert _classify_environment("smoky") is None
        assert _classify_environment("smoky room") is None
        assert _classify_environment("xyzzy") is None

    def test_keyword_match_is_case_insensitive(self):
        assert _classify_environment("LOUD") == "high"
        assert _classify_environment("Intimate") == "low"
        assert _classify_environment("Cafe") == "mid"

    def test_high_wins_when_multiple_archetypes_present(self):
        """Order of checks is high → low → mid; the first hit wins. We
        document this here so future authors don't accidentally flip the
        priority and silently change behaviour."""
        assert _classify_environment("loud intimate cafe") == "high"

    def test_punctuation_and_phrases_are_tokenized(self):
        assert _classify_environment("smoky club, low light") == "high"
        assert _classify_environment("at-home, on phones") == "low"


class TestApplyEnvironmentBiasPure:
    """Unit tests for ``_apply_environment_bias``."""

    def test_no_environment_no_bias(self):
        clusters = [[_t("a", 100), _t("b", 130), _t("c", 110), _t("d", 140)]]
        out = _apply_environment_bias(clusters, "")
        assert out is clusters

    def test_unspecified_no_bias(self):
        clusters = [[_t("a", 100), _t("b", 130)]]
        out = _apply_environment_bias(clusters, "unspecified")
        assert out is clusters

    def test_unrecognized_keyword_no_bias(self):
        """``"smoky"`` matches none of the keyword sets → no-op (clusters
        returned by identity)."""
        clusters = [[_t("a", 100), _t("b", 130)]]
        out = _apply_environment_bias(clusters, "smoky")
        assert out is clusters

    def test_high_energy_keywords_bias_toward_high_bpm(self):
        """A=100, B=130, C=110, D=140 with env "loud crowded bar"
        → output puts {B, D} before {A, C} within the cluster."""
        cluster = [_t("a", 100), _t("b", 130), _t("c", 110), _t("d", 140)]
        out = _apply_environment_bias([cluster], "loud crowded bar")
        ids = [t["id"] for t in out[0]]
        assert ids.index("d") < ids.index("a")
        assert ids.index("d") < ids.index("c")
        assert ids.index("b") < ids.index("a")
        assert ids.index("b") < ids.index("c")
        # Stable, deterministic order: descending BPM => D, B, C, A.
        assert ids == ["d", "b", "c", "a"]

    def test_low_energy_keywords_bias_toward_low_bpm(self):
        """Same A, B, C, D but env "intimate listening" → A, C before B, D."""
        cluster = [_t("a", 100), _t("b", 130), _t("c", 110), _t("d", 140)]
        out = _apply_environment_bias([cluster], "intimate listening")
        ids = [t["id"] for t in out[0]]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("d")
        assert ids.index("c") < ids.index("b")
        assert ids.index("c") < ids.index("d")
        # Ascending BPM, missing-BPM tracks pushed to the back.
        assert ids == ["a", "c", "b", "d"]

    def test_mid_keywords_bias_toward_median_bpm(self):
        """Mid archetype prefers tracks closest to the cluster's median.
        Cluster [80, 90, 100, 110, 130] median = 100, so 100 leads,
        followed by neighbors 90 / 110 (tied distance), etc."""
        cluster = [
            _t("a", 80),
            _t("b", 90),
            _t("c", 100),
            _t("d", 110),
            _t("e", 130),
        ]
        out = _apply_environment_bias([cluster], "outdoor cafe morning")
        ids = [t["id"] for t in out[0]]
        # The median (100) is first; the highest-distance track (130) is last.
        assert ids[0] == "c"
        assert ids[-1] == "e"

    def test_keyword_match_is_case_insensitive(self):
        cluster = [_t("a", 100), _t("b", 130)]
        out = _apply_environment_bias([cluster], "LOUD CROWDED")
        ids = [t["id"] for t in out[0]]
        assert ids == ["b", "a"]

    def test_missing_bpm_treated_as_zero_and_demoted(self):
        """A track with bpm=None must not bubble to the front in the
        low-energy archetype; the helper coerces missing BPM to 0 and
        sorts those tracks to the back."""
        cluster = [_t("a", 100), _t("b", None), _t("c", 90)]
        out = _apply_environment_bias([cluster], "intimate listening")
        ids = [t["id"] for t in out[0]]
        # Real-BPM tracks come first ascending; missing-BPM track is last.
        assert ids[0] == "c"
        assert ids[1] == "a"
        assert ids[-1] == "b"

    def test_empty_cluster_remains_empty(self):
        out = _apply_environment_bias([[]], "loud crowded bar")
        assert out == [[]]

    def test_returns_fresh_lists_when_biasing(self):
        cluster = [_t("a", 100), _t("b", 130)]
        clusters = [cluster]
        out = _apply_environment_bias(clusters, "loud")
        assert out is not clusters
        assert out[0] is not cluster

    def test_input_clusters_are_not_mutated(self):
        cluster = [_t("a", 100), _t("b", 130), _t("c", 110)]
        original_ids = [t["id"] for t in cluster]
        _apply_environment_bias([cluster], "loud crowded bar")
        assert [t["id"] for t in cluster] == original_ids

    def test_multiple_clusters_each_reordered_independently(self):
        clusters = [
            [_t("a1", 100), _t("a2", 140)],
            [_t("b1", 90), _t("b2", 130)],
        ]
        out = _apply_environment_bias(clusters, "loud crowded bar")
        assert [t["id"] for t in out[0]] == ["a2", "a1"]
        assert [t["id"] for t in out[1]] == ["b2", "b1"]


# ---------------------------------------------------------------------------
# Integration — propose_playlist + env bias respects user-rating bias
# ---------------------------------------------------------------------------

@pytest.fixture
def cyberpunk_catalog(tmp_path, monkeypatch):
    """Catalog identical in shape to ``tests/test_propose_playlist_bias.py``
    but with a wider BPM spread so the env bias can reorder visibly."""
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
                "bpm": 122.0,
                "camelot_key": "9A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-3",
                "display_name": "Cyber Three",
                "file": "tracks/cyberpunk/three.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 124.0,
                "camelot_key": "10A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-4",
                "display_name": "Cyber Four",
                "file": "tracks/cyberpunk/four.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 126.0,
                "camelot_key": "11A",
                "duration_sec": 360.0,
            },
            {
                "id": "cyber-5",
                "display_name": "Cyber Five",
                "file": "tracks/cyberpunk/five.wav",
                "genre_folder": "cyberpunk",
                "genre": "cyberpunk",
                "bpm": 128.0,
                "camelot_key": "12A",
                "duration_sec": 360.0,
            },
        ]
    }
    catalog_path = tmp_path / "tracks.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(tools, "_CATALOG_PATH", catalog_path)
    return catalog_path


def _seed_random_for_determinism():
    random.seed(0)


def test_combined_with_user_rating_bias(cyberpunk_catalog):
    """Favorites still come first within their cluster, env bias only
    reorders the non-favorite remainder.

    Setup:
      - Favorite: cyber-1 (lowest BPM, 120) — would normally drop to back
        under a HIGH-energy env bias.
      - Env: "loud crowded bar" → high energy.

    Expectation: cyber-1 leads the playlist (favorite invariant). The
    remaining tracks among themselves are ordered descending by BPM, so
    cyber-5 (128) > cyber-4 (126) > cyber-3 (124) > cyber-2 (122).
    """
    _seed_random_for_determinism()
    ctx = {
        "favorite_ids": {"cyber-1"},
        "dislike_ids": set(),
        "environment": "loud crowded bar",
    }
    tools.propose_playlist("cyberpunk", 30, "test", ctx)
    ids = [t["id"] for t in ctx["playlist"]]
    # Favorite invariant: cyber-1 first.
    assert ids[0] == "cyber-1"
    # Environment reorders the remainder descending by BPM.
    assert ids[1:] == ["cyber-5", "cyber-4", "cyber-3", "cyber-2"]


def test_no_environment_in_ctx_falls_back_to_no_op(cyberpunk_catalog):
    """``ctx`` without the ``environment`` key (legacy callers) still works
    and produces a playlist identical to the pre-v2.5 baseline."""
    _seed_random_for_determinism()
    ctx_baseline: dict = {}
    tools.propose_playlist("cyberpunk", 30, "test", ctx_baseline)
    baseline_ids = [t["id"] for t in ctx_baseline["playlist"]]

    _seed_random_for_determinism()
    ctx_unspecified = {"environment": "unspecified"}
    tools.propose_playlist("cyberpunk", 30, "test", ctx_unspecified)
    assert [t["id"] for t in ctx_unspecified["playlist"]] == baseline_ids


def test_environment_progress_event_emitted(cyberpunk_catalog):
    """When the environment classifies into an archetype and a
    ``_progress`` callback is in ctx, the bias step emits an ``env_bias``
    event the web UI can render."""
    _seed_random_for_determinism()
    events: list[dict] = []

    def _progress(event: dict) -> None:
        events.append(event)

    ctx = {
        "favorite_ids": set(),
        "dislike_ids": set(),
        "environment": "loud crowded bar",
        "_progress": _progress,
    }
    tools.propose_playlist("cyberpunk", 18, "test", ctx)

    env_events = [e for e in events if e.get("stage") == "env_bias"]
    assert env_events, "expected an 'env_bias' progress event"
    assert "loud crowded bar" in env_events[0]["message"]
