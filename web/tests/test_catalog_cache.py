"""Tests for the in-memory catalog cache (issue #17).

Hydrating GET /api/playlists/{id} previously called load_catalog() once per
request, which re-read tracks/tracks.json (~534 KB) and rebuilt a by-id
dict. The cache memoizes both, keyed on (mtime, size) so external rebuilds
(e.g. `python main.py --build-catalog`) still invalidate correctly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def real_catalog(tmp_path, monkeypatch):
    """Point pipeline at a tmp tracks/tracks.json with two entries.

    Crucially, this fixture does NOT monkeypatch load_catalog itself — it
    only repoints _PROJECT_DIR so the real (cached) implementation runs.
    """
    from web.backend import pipeline

    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    catalog_path = tracks_dir / "tracks.json"
    catalog_path.write_text(json.dumps({
        "tracks": [
            {
                "id": "lofi--alpha",
                "display_name": "Alpha",
                "file": "lofi/alpha.wav",
                "genre_folder": "lofi",
                "genre": "lofi",
                "camelot_key": "8A",
                "bpm": 90,
            },
            {
                "id": "house--beta",
                "display_name": "Beta",
                "file": "house/beta.wav",
                "genre_folder": "house",
                "genre": "house",
                "camelot_key": "9A",
                "bpm": 124,
            },
        ],
    }), encoding="utf-8")

    monkeypatch.setattr(pipeline, "_PROJECT_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "_CATALOG_CACHE", None, raising=False)
    return {"catalog_path": catalog_path, "tmp_root": tmp_path}


def _wrap_disk_reader(monkeypatch, pipeline_mod) -> dict:
    """Wrap pipeline._read_catalog_from_disk to count invocations.

    The cache is a hit when this counter does NOT advance between calls.
    """
    real = pipeline_mod._read_catalog_from_disk
    counter = {"n": 0}

    def counting_reader():
        counter["n"] += 1
        return real()

    monkeypatch.setattr(pipeline_mod, "_read_catalog_from_disk", counting_reader)
    return counter


def test_load_catalog_caches_by_mtime_size(real_catalog, monkeypatch):
    """A second call against an unchanged file must NOT hit disk again."""
    from web.backend import pipeline

    counter = _wrap_disk_reader(monkeypatch, pipeline)

    tracks1, _ = pipeline.load_catalog(None)
    assert len(tracks1) == 2
    first_calls = counter["n"]
    assert first_calls == 1, "first call should have read the file exactly once"

    tracks2, _ = pipeline.load_catalog(None)
    assert len(tracks2) == 2
    assert counter["n"] == first_calls, "second call should be a cache hit"


def test_load_catalog_invalidates_on_mtime_change(real_catalog, monkeypatch):
    """Touching the file (changing mtime) must force a re-read."""
    from web.backend import pipeline

    counter = _wrap_disk_reader(monkeypatch, pipeline)

    pipeline.load_catalog(None)
    first_calls = counter["n"]

    # Bump mtime by 5 seconds so it definitely registers even on filesystems
    # with 1s mtime resolution.
    catalog_path: Path = real_catalog["catalog_path"]
    stat = catalog_path.stat()
    new_time = stat.st_mtime + 5
    os.utime(catalog_path, (new_time, new_time))

    pipeline.load_catalog(None)
    assert counter["n"] > first_calls, (
        "cache should have invalidated after mtime bump"
    )


def test_load_catalog_invalidates_on_size_change(real_catalog, monkeypatch):
    """Rewriting the file with a different size must force a re-read.

    Covers the case where two writes happen within the same mtime tick on
    a filesystem with 1s mtime resolution — the size component of the
    cache key still detects the change.
    """
    from web.backend import pipeline

    counter = _wrap_disk_reader(monkeypatch, pipeline)

    pipeline.load_catalog(None)
    first_calls = counter["n"]

    catalog_path: Path = real_catalog["catalog_path"]
    new_payload = json.dumps({
        "tracks": [
            {"id": "lofi--alpha", "display_name": "Alpha", "genre_folder": "lofi"},
        ],
    })
    catalog_path.write_text(new_payload, encoding="utf-8")
    # The new payload is much shorter, so size definitely changes.

    tracks, _ = pipeline.load_catalog(None)
    assert counter["n"] > first_calls
    assert len(tracks) == 1


def test_get_track_by_id_returns_correct_track(real_catalog):
    from web.backend import pipeline

    track = pipeline.get_track_by_id("lofi--alpha")
    assert track is not None
    assert track["display_name"] == "Alpha"
    assert track["bpm"] == 90


def test_get_track_by_id_returns_none_for_missing(real_catalog):
    from web.backend import pipeline

    assert pipeline.get_track_by_id("nonexistent") is None


def test_get_track_by_id_warm_then_cold(real_catalog, monkeypatch):
    """get_track_by_id should warm the cache by itself (no prior load)."""
    from web.backend import pipeline

    # Force a cold start.
    monkeypatch.setattr(pipeline, "_CATALOG_CACHE", None, raising=False)

    track = pipeline.get_track_by_id("house--beta")
    assert track is not None
    assert track["bpm"] == 124


def test_get_track_by_id_returns_none_when_catalog_missing(tmp_path, monkeypatch):
    """If tracks.json doesn't exist, get_track_by_id swallows the error
    so /api/playlists/{id} can fall back to the `missing=True` placeholder
    rather than 500."""
    from web.backend import pipeline

    monkeypatch.setattr(pipeline, "_PROJECT_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "_CATALOG_CACHE", None, raising=False)

    assert pipeline.get_track_by_id("anything") is None
