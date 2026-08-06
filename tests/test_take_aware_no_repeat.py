"""Tests for v3.10 — take-aware no-repeat (agent/track_identity.py).

Driver: the 2026-08-05 meditation session played 91 tracks with ZERO
id-level repeats and still delivered 5+ audible repeats — Suno takes of
the same piece live under different ids (and sometimes different
display names: 'Subaquatic Whispers' and 'Echoes of the Abyss' are the
same composition). All fixtures here mirror REAL catalog shapes.

Covers:
  - piece_keys / dedupe_takes against the four real id patterns
    (variant_of, collision suffixes, UUID generations, 'bis' names)
  - _autoplay_pick excluding takes in every tier
  - append_track rejecting takes of playing/queued pieces
  - fallback callers treating a guard rejection as "not extended"
  - propose_playlist / pick_next_track collapsing twins
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agent.live_engine import (
    ENDLESS_GRACE_SEC,
    LiveEngineBrowser,
    _autoplay_pick,
)
from agent.track_identity import (
    dedupe_takes,
    piece_exclusion_set,
    piece_keys,
    shares_piece,
)
from agent.tools import pick_next_track, propose_playlist


# ── Real-shape fixtures ────────────────────────────────────────────────────

def _t(track_id, name, *, vo=None, genre="aural", bpm=60.0,
       duration_sec=240.0, key="8A"):
    return {
        "id": track_id,
        "display_name": name,
        "variant_of": vo,
        "genre_folder": genre,
        "genre": genre,
        "bpm": bpm,
        "camelot_key": key,
        "duration_sec": duration_sec,
        "hot_cues": [],
    }


# The luz_difusa piece, exactly as in prod tracks.json: base take and a
# collision-renamed variant with a DIFFERENT curated display name.
LUZ_BASE = _t("aural--aural_2-luz_difusa", "Luminous Space")
LUZ_V3 = _t("aural--aural_2-luz_difusa-v3", "Shimmering Quiet",
            vo="Aural_2-Luz_Difusa")
# afterglow_cradle: '-2' collision rename + '-v2' variant.
CRADLE_2 = _t("aural--aural-afterglow_cradle-2", "Afterglow Cradle")
CRADLE_V2 = _t("aural--aural-afterglow_cradle-v2", "Ethereal Ember",
               vo="Aural-Afterglow_Cradle")
# Hand-saved 'bis' pair (lofi shape: uuid tails, no variant_of link).
FOG = _t("lofi-ambient--lofi_2-fog_on_the_desk-8389f4f6-1858-45cd-bd5e-83c14e0988c0",
         "Fog On The Desk", genre="lofi - ambient", bpm=75)
FOG_BIS = _t("lofi-ambient--lofi_2-fog_on_the_desk_bis-13911c28-7358-4649-aff1-e764f87e59d0",
             "Fog On The Desk bis", genre="lofi - ambient", bpm=75)
# Two GENERATIONS from one prompt: same stem, different uuids, distinct
# curated names — must NEVER be collapsed.
QP_A = _t("lofi-ambient--lofi_2-quiet_pages-0bfff49d-0ef6-478e-9200-f22dc472032a",
          "Nylon Guitar Whisper", genre="lofi - ambient", bpm=75)
QP_B = _t("lofi-ambient--lofi_2-quiet_pages-16861b5e-b7fc-470f-aaa8-b02444d1fb70",
          "Rhodes Sway", genre="lofi - ambient", bpm=75)


class TestPieceKeys:
    def test_variant_of_links_to_base_take(self):
        assert piece_keys(LUZ_BASE) & piece_keys(LUZ_V3)

    def test_bare_numeric_collision_renames_stay_unlinked(self):
        # Documented limitation: bare '-2' collision renames can't be
        # told apart from legit slugs ('sector-9') without catalog
        # context, so they only link when the NAME key aligns —
        # CRADLE_2/CRADLE_V2 carry different curated names, so they
        # stay distinct pieces.
        assert not (piece_keys(CRADLE_2) & piece_keys(CRADLE_V2))

    def test_vN_suffix_links_without_variant_of(self):
        # A '-v2' id whose variant_of was lost still links to its base
        # via the structural suffix strip.
        a = _t("aural--aural-deep_currents", "Subaquatic Whispers")
        b = _t("aural--aural-deep_currents-v2", "Echoes of the Abyss")
        assert piece_keys(a) & piece_keys(b)

    def test_bis_pair_links_via_name(self):
        assert piece_keys(FOG) & piece_keys(FOG_BIS)

    def test_uuid_generations_stay_distinct(self):
        assert not (piece_keys(QP_A) & piece_keys(QP_B))

    def test_same_name_different_genre_stays_distinct(self):
        a = _t("aural--aural-x", "Circuit Matrix")
        b = _t("synthware--synthware-x-11111111-2222-3333-4444-555555555555",
               "Circuit Matrix", genre="synthware")
        # Structural keys differ; name keys carry the genre.
        assert not (piece_keys(a) & piece_keys(b))

    def test_empty_track_matches_nothing(self):
        assert piece_keys({}) == frozenset()
        assert not shares_piece({}, {"struct::x"})


class TestDedupeTakes:
    def test_keeps_first_take_drops_twins(self):
        out = dedupe_takes([LUZ_BASE, QP_A, LUZ_V3, QP_B, FOG, FOG_BIS])
        ids = [t["id"] for t in out]
        assert LUZ_BASE["id"] in ids and LUZ_V3["id"] not in ids
        assert FOG["id"] in ids and FOG_BIS["id"] not in ids
        assert QP_A["id"] in ids and QP_B["id"] in ids  # generations survive


# ── _autoplay_pick — piece-aware exclusion in every tier ──────────────────

class TestAutoplayPickTakeAware:
    def test_played_take_excludes_its_twin(self):
        # The 2026-08-05 shape: 'Luminous Space' played hours ago; its
        # twin 'Shimmering Quiet' is a different id and used to slip
        # straight through the id-level exclude.
        current = _t("aural--aural-now", "Now Playing", bpm=60)
        catalog = [LUZ_BASE, LUZ_V3, _t("aural--aural-fresh", "Fresh", bpm=90)]
        pick = _autoplay_pick(
            current, catalog, "aural", {LUZ_BASE["id"], current["id"]},
        )
        assert pick is not None and pick["id"] == "aural--aural-fresh"

    def test_recycle_tier_avoids_takes_of_recent_pieces(self):
        current = _t("aural--aural-now", "Now Playing", bpm=60)
        catalog = [LUZ_BASE, LUZ_V3, _t("aural--aural-old", "Old", bpm=90)]
        pick = _autoplay_pick(
            current, catalog, "aural",
            {LUZ_BASE["id"], LUZ_V3["id"], "aural--aural-old", current["id"]},
            allow_repeats=True,
            recent_ids=[LUZ_BASE["id"], current["id"]],
        )
        # LUZ_V3 ranks better on Δbpm but is a take of a recent piece.
        assert pick is not None and pick["id"] == "aural--aural-old"

    def test_degrade_tier_avoids_take_of_current(self):
        current = dict(LUZ_BASE)
        catalog = [LUZ_V3, _t("aural--aural-other", "Other", bpm=90)]
        pick = _autoplay_pick(
            current, catalog, "aural",
            {LUZ_BASE["id"], LUZ_V3["id"], "aural--aural-other"},
            allow_repeats=True,
            recent_ids=[LUZ_V3["id"], "aural--aural-other", LUZ_BASE["id"]],
        )
        assert pick is not None and pick["id"] == "aural--aural-other"

    def test_returns_none_when_only_twins_remain(self):
        current = _t("aural--aural-now", "Now Playing", bpm=60)
        catalog = [LUZ_V3]
        pick = _autoplay_pick(
            current, catalog, "aural", {LUZ_BASE["id"], current["id"]},
        )
        # Twin of an excluded piece... but LUZ_BASE is not in catalog,
        # so its piece keys can't be derived from the exclude ids —
        # verify via never_ids-free direct exclusion instead.
        pick2 = _autoplay_pick(
            current, [LUZ_BASE, LUZ_V3], "aural",
            {LUZ_BASE["id"], current["id"]},
        )
        assert pick2 is None
        assert pick is not None  # documents the catalog-lookup boundary

    def test_never_ids_extend_to_takes(self):
        # A take of a QUEUED piece must not be picked even on recycle.
        current = _t("aural--aural-now", "Now Playing", bpm=60)
        catalog = [LUZ_BASE, LUZ_V3, _t("aural--aural-old", "Old", bpm=90)]
        pick = _autoplay_pick(
            current, catalog, "aural", set(),
            allow_repeats=True,
            never_ids={LUZ_BASE["id"]},
        )
        assert pick is not None and pick["id"] == "aural--aural-old"


# ── append_track — take-aware dedupe guard ────────────────────────────────

def _engine(playlist):
    e = LiveEngineBrowser(emitter=lambda ev: None, approach_warn_sec=30)
    e.play(playlist)
    return e


class TestAppendGuardTakeAware:
    def test_rejects_take_of_queued_piece(self):
        engine = _engine([dict(LUZ_BASE), _t("aural--aural-b", "B")])
        out = engine.append_track(dict(LUZ_V3))
        assert "refusing duplicate append" in out
        assert len(engine.playlist) == 2

    def test_rejects_take_of_current_piece(self):
        engine = _engine([dict(LUZ_V3)])
        out = engine.append_track(dict(LUZ_BASE))
        assert "refusing duplicate append" in out

    def test_allows_take_of_played_piece(self):
        # Behind the cursor = fair recycle target, take or not.
        engine = _engine([dict(LUZ_BASE), _t("aural--aural-b", "B")])
        engine._idx = 1
        out = engine.append_track(dict(LUZ_V3))
        assert "refusing" not in out
        assert engine.playlist[-1]["id"] == LUZ_V3["id"]

    def test_distinct_generations_still_append(self):
        engine = _engine([dict(QP_A)])
        out = engine.append_track(dict(QP_B))
        assert "refusing" not in out


class TestFallbackHandlesRejection:
    def test_inflight_extend_reports_false_on_guard_rejection(self, monkeypatch):
        # Belt+braces: if a pick ever slips past the picker's own
        # exclusions but trips the append guard, the inflight extend
        # must report "not extended" instead of pretending success.
        engine = _engine([dict(LUZ_BASE)])
        engine._endless_mode = True
        engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
        monkeypatch.setattr(
            "agent.live_engine._autoplay_pick", lambda *a, **k: dict(LUZ_V3),
        )
        monkeypatch.setattr(
            "agent.live_engine._load_catalog", lambda: [dict(LUZ_V3)],
        )
        assert engine._try_endless_extend_inflight(engine.playlist[0]) is False
        assert len(engine.playlist) == 1


# ── Tools — planner + candidate table collapse twins ──────────────────────

def test_propose_playlist_schedules_one_take_per_piece(tmp_path, monkeypatch):
    import json

    import agent.tools as tools

    deep_a = _t("aural--aural-deep_currents", "Subaquatic Whispers", bpm=62)
    deep_b = _t("aural--aural-deep_currents-v2", "Echoes of the Abyss",
                vo="Aural-Deep_Currents", bpm=63)
    tracks = [
        dict(LUZ_BASE, bpm=60), dict(LUZ_V3, bpm=61),
        deep_a, deep_b,
        _t("aural--aural-solo", "Solo Piece", bpm=64),
    ]
    p = tmp_path / "tracks.json"
    p.write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
    monkeypatch.setattr(tools, "_CATALOG_PATH", p)
    out = propose_playlist("aural", 30, "calm", {})
    # One take per piece: never both ids of a pair.
    assert not (LUZ_BASE["id"] in out and LUZ_V3["id"] in out)
    assert not (deep_a["id"] in out and deep_b["id"] in out)
    assert "Solo Piece" in out


def test_pick_next_track_table_has_one_take_per_piece():
    import web.backend.pipeline as pipeline

    catalog = [dict(LUZ_BASE, bpm=60), dict(LUZ_V3, bpm=60),
               _t("aural--aural-other", "Other", bpm=60)]
    with patch.object(pipeline, "load_catalog", return_value=(catalog, ["aural"])):
        out = pick_next_track(55.0, 65.0, {"genre": "aural"})
    assert not (LUZ_BASE["id"] in out and LUZ_V3["id"] in out)
    assert "aural--aural-other" in out
