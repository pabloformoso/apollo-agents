"""Unit tests for the pure helpers in ``web.backend.render``.

The async subprocess + SSE generator are covered separately in
``test_app_render.py`` against a fixture script. This file pins the
stage-mapping + pct + ETA + chapters + traversal logic in isolation so
regressions surface at the closest seam.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.backend import render


# ─── _v26_stage ──────────────────────────────────────────────────────


def test_v26_stage_simple_mappings():
    assert render._v26_stage({"stage": "loading_session", "message": ""}) == "stems"
    assert render._v26_stage({"stage": "mix_done", "message": ""}) == "crossfades"
    assert render._v26_stage({"stage": "export_audio", "message": ""}) == "master"
    assert render._v26_stage({"stage": "artwork", "message": ""}) == "cover"
    assert render._v26_stage({"stage": "render_video", "message": ""}) == "encode"
    assert render._v26_stage({"stage": "validate", "message": ""}) == "encode"


def test_v26_stage_mixing_first_two_tracks_are_stems():
    for i in (1, 2):
        event = {"stage": "mixing", "message": f"Mixing track {i}/8: foo"}
        assert render._v26_stage(event) == "stems"


def test_v26_stage_mixing_remaining_tracks_are_crossfades():
    for i in (3, 5, 8):
        event = {"stage": "mixing", "message": f"Mixing track {i}/8: foo"}
        assert render._v26_stage(event) == "crossfades"


def test_v26_stage_unparseable_mixing_message_defaults_to_stems():
    event = {"stage": "mixing", "message": "garbage no i/N"}
    assert render._v26_stage(event) == "stems"


def test_v26_stage_unknown_stage_falls_back_to_stems():
    assert render._v26_stage({"stage": "something_new", "message": ""}) == "stems"


# ─── _compute_pct ────────────────────────────────────────────────────


def test_compute_pct_fixed_stage_values():
    assert render._compute_pct({"stage": "loading_session", "message": ""}, 0) == 2.0
    assert render._compute_pct({"stage": "mix_done", "message": ""}, 30) == 55.0
    assert render._compute_pct({"stage": "export_audio", "message": ""}, 55) == 63.0
    assert render._compute_pct({"stage": "render_video", "message": ""}, 90) == 95.0
    assert render._compute_pct({"stage": "validate", "message": ""}, 95) == 98.0


def test_compute_pct_mixing_increases_monotonically_in_stems_band():
    """Tracks 1–2 should land between 5 and 30."""
    e1 = {"stage": "mixing", "message": "Mixing track 1/4: foo"}
    e2 = {"stage": "mixing", "message": "Mixing track 2/4: foo"}
    p1 = render._compute_pct(e1, 0)
    p2 = render._compute_pct(e2, p1)
    assert 5 <= p1 < p2 <= 30


def test_compute_pct_mixing_increases_monotonically_in_crossfades_band():
    e3 = {"stage": "mixing", "message": "Mixing track 3/4: foo"}
    e4 = {"stage": "mixing", "message": "Mixing track 4/4: foo"}
    p3 = render._compute_pct(e3, 30)
    p4 = render._compute_pct(e4, p3)
    assert 30 <= p3 < p4 <= 55


def test_compute_pct_artwork_track_increments_from_last():
    e = {"stage": "artwork_track", "message": "Artwork: foo"}
    assert render._compute_pct(e, 65) == 69.0
    # Capped at 85.
    assert render._compute_pct(e, 84) == 85.0
    assert render._compute_pct(e, 90) == 85.0


def test_compute_pct_unknown_stage_keeps_last():
    assert render._compute_pct({"stage": "weird", "message": ""}, 42.0) == 42.0


# ─── _eta ────────────────────────────────────────────────────────────


def test_eta_returns_none_below_threshold():
    import time
    now = time.time()
    assert render._eta(now - 1, 0) is None
    assert render._eta(now - 1, 4) is None


def test_eta_proportional_to_remaining_pct():
    import time
    now = time.time()
    # Elapsed ~10s at 50% pct → ETA ~10s (proportional).
    eta = render._eta(now - 10, 50)
    assert eta is not None
    assert 5 <= eta <= 15


def test_eta_floors_at_five_seconds():
    import time
    # Near-100% but with very short elapsed → still floors at 5.
    eta = render._eta(time.time() - 0.05, 99.9)
    assert eta == 5.0


def test_eta_caps_at_thirty_minutes():
    import time
    # Tiny pct over a long elapsed window pushes ETA above 1800s.
    eta = render._eta(time.time() - 600, 5.0)
    assert eta == 1800.0


# ─── _is_within (traversal defence) ──────────────────────────────────


def test_is_within_blocks_traversal_above_root(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    assert render._is_within(root / "session1" / "mix.mp4", root) is True
    # `..` escapes the root.
    escape = root / ".." / "secret.txt"
    assert render._is_within(escape, root) is False


def test_is_within_allows_subdirectories(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    target = root / "deep" / "nested" / "file.wav"
    assert render._is_within(target, root) is True


# ─── _collect_chapters ───────────────────────────────────────────────


def test_collect_chapters_missing_file_returns_empty(tmp_path):
    assert render._collect_chapters(tmp_path) == []


def test_collect_chapters_reads_transitions_list(tmp_path):
    (tmp_path / "transitions.json").write_text(json.dumps([
        {"display_name": "First", "camelot_key": "8A", "duration_sec": 240},
        {"display_name": "Second", "camelot_key": "9A", "duration_sec": 360},
        {"display_name": "Third", "camelot_key": "10A"},  # missing dur → 408 default
    ]))
    chs = render._collect_chapters(tmp_path)
    assert [c["title"] for c in chs] == ["First", "Second", "Third"]
    assert chs[0]["tMs"] == 0
    assert chs[1]["tMs"] == 240 * 1000
    assert chs[2]["tMs"] == (240 + 360) * 1000
    assert chs[0]["camelot"] == "8A"


def test_collect_chapters_accepts_dict_wrapped_payload(tmp_path):
    """Some v2.x writers wrap the list in ``{"transitions": [...]}``."""
    (tmp_path / "transitions.json").write_text(json.dumps({
        "transitions": [
            {"title": "T1", "duration_sec": 60},
        ]
    }))
    chs = render._collect_chapters(tmp_path)
    assert chs == [{"tMs": 0, "title": "T1", "camelot": None}]


def test_collect_chapters_falls_back_to_track_index_title(tmp_path):
    (tmp_path / "transitions.json").write_text(json.dumps([
        {"duration_sec": 100},
        {"duration_sec": 100},
    ]))
    chs = render._collect_chapters(tmp_path)
    assert chs[0]["title"] == "Track 1"
    assert chs[1]["title"] == "Track 2"


def test_collect_chapters_swallows_malformed_json(tmp_path):
    (tmp_path / "transitions.json").write_text("not-json{{{")
    assert render._collect_chapters(tmp_path) == []
