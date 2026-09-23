"""The planner never schedules a piece twice — not even to fill time.

Regression for the 2026-09-23 healing broadcast: a 5 h request against a
catalog whose BPM cluster held 28 pieces came back as those 28 looped
~3x into 79 slots. The endless engine's no-repeat window only guards
tracks IT appends, so the pre-looped playlist went straight to air and
replayed its first track after 90 minutes.

The fixture mirrors that catalog's shape: 28 pieces at 52-67 BPM (the
cluster the planner keeps) plus 24 at 72-98 BPM (outside it).
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

import agent.tools as tools


def _t(slug: str, bpm: float, dur: float = 200.0) -> dict:
    return {
        "id": f"healing--healing-{slug}",
        "display_name": slug.replace("_", " ").title(),
        "file": f"tracks/Healing/{slug}.wav",
        "genre_folder": "Healing",
        "genre": "Healing",
        "camelot_key": "8B",
        "bpm": bpm,
        "duration_sec": dur,
        "variant_of": None,
    }


IN_CLUSTER = [_t(f"calm_{i:02d}", 52.0 + (i % 16)) for i in range(28)]
OUT_OF_CLUSTER = [_t(f"fast_{i:02d}", 72.0 + i) for i in range(24)]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    def write(tracks: list[dict]) -> None:
        p = tmp_path / "tracks.json"
        p.write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
        monkeypatch.setattr(tools, "_CATALOG_PATH", p)
    return write


def _ids(ctx: dict) -> list[str]:
    return [t["id"] for t in ctx["playlist"]]


def test_five_hour_request_on_a_short_cluster_does_not_loop(catalog):
    catalog(IN_CLUSTER + OUT_OF_CLUSTER)
    ctx: dict = {}
    out = tools.propose_playlist("healing", 300, "focus at work", ctx)

    ids = _ids(ctx)
    repeats = {i: n for i, n in Counter(ids).items() if n > 1}
    assert not repeats, f"planner repeated tracks: {repeats}"
    # Every cluster piece is used once, and the header tells the truth
    # about the length instead of echoing the 300 min requested.
    assert len(ids) == len(IN_CLUSTER)
    assert "~93 min" in out
    assert "300 min requested" in out


def test_long_enough_catalog_still_stops_at_the_target(catalog):
    catalog(IN_CLUSTER)
    ctx: dict = {}
    out = tools.propose_playlist("healing", 30, "calm", ctx)

    ids = _ids(ctx)
    assert len(ids) == len(set(ids))
    # 200 s tracks: nine reach 30 min, and nothing past the target.
    assert len(ids) == 9
    assert "requested" not in out


def _playlist_ctx(catalog, n: int = 3) -> dict:
    catalog(IN_CLUSTER)
    return {"playlist": [dict(t) for t in IN_CLUSTER[:n]]}


def test_swap_rejects_a_track_already_in_the_playlist(catalog):
    ctx = _playlist_ctx(catalog)
    out = tools.swap_track(1, IN_CLUSTER[2]["id"], ctx)
    assert "NOT swapped" in out
    assert _ids(ctx) == [t["id"] for t in IN_CLUSTER[:3]]


def test_swap_into_its_own_slot_is_allowed(catalog):
    ctx = _playlist_ctx(catalog)
    out = tools.swap_track(2, IN_CLUSTER[1]["id"], ctx)
    assert "Swapped position 2" in out


def test_swap_with_a_fresh_track_works(catalog):
    ctx = _playlist_ctx(catalog)
    tools.swap_track(1, IN_CLUSTER[10]["id"], ctx)
    assert _ids(ctx)[0] == IN_CLUSTER[10]["id"]


def test_insert_bridge_rejects_a_track_already_in_the_playlist(catalog):
    ctx = _playlist_ctx(catalog)
    out = tools.insert_bridge_track(1, IN_CLUSTER[2]["id"], ctx)
    assert "NOT inserted" in out
    assert len(ctx["playlist"]) == 3
