"""The engine says on the wire when ITS safety net queued a track.

Until the ``decision`` event, a track the endless fallback appended and a
track the DJ chose looked identical from the browser: both just appeared.
The tier ``_endless_pick`` returns only ever reached the backend log.
"""
from __future__ import annotations

import time

from agent.live_engine import DECISION, ENDLESS_GRACE_SEC, LiveEngineBrowser


def _t(track_id, name, *, genre="aural", bpm=60.0):
    return {
        "id": track_id,
        "display_name": name,
        "variant_of": None,
        "genre_folder": genre,
        "genre": genre,
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": 240.0,
        "hot_cues": [],
    }


A = _t("aural--a", "Luminous Space")
B = _t("aural--b", "Soft Focus")


def _armed_engine(events: list[dict]) -> LiveEngineBrowser:
    engine = LiveEngineBrowser(emitter=events.append, approach_warn_sec=30)
    engine.play([dict(A)])
    engine._endless_mode = True
    engine._low_water_at = time.monotonic() - (ENDLESS_GRACE_SEC + 1)
    return engine


def _decisions(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == DECISION]


def test_inflight_fallback_announces_the_pick_and_its_tier(monkeypatch):
    events: list[dict] = []
    engine = _armed_engine(events)
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [dict(A), dict(B)])
    monkeypatch.setattr("agent.live_engine._endless_pick", lambda *a, **k: (dict(B), "widened"))

    assert engine._try_endless_extend_inflight(engine.playlist[0]) is True

    assert _decisions(events) == [{
        "type": DECISION,
        "kind": "endless_pick",
        "tier": "widened",
        "picked_by": "engine",
        "track": {"id": "aural--b", "display_name": "Soft Focus"},
    }]


def test_end_of_track_fallback_announces_too(monkeypatch):
    events: list[dict] = []
    engine = _armed_engine(events)
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [dict(A), dict(B)])
    monkeypatch.setattr("agent.live_engine._endless_pick", lambda *a, **k: (dict(B), "in_genre"))

    ended = engine._maybe_end_or_extend(engine.playlist[0], track_over=True)

    assert ended is False, "a successful append keeps the set going"
    assert [d["tier"] for d in _decisions(events)] == ["in_genre"]
    assert engine.playlist[-1]["id"] == "aural--b"


def test_a_rejected_pick_is_not_announced(monkeypatch):
    """The guard refused it, so nothing was queued — and nothing is claimed."""
    events: list[dict] = []
    engine = _armed_engine(events)
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [dict(A)])
    # The playing track again: the append guard refuses the duplicate.
    monkeypatch.setattr("agent.live_engine._endless_pick", lambda *a, **k: (dict(A), "recycled"))

    assert engine._try_endless_extend_inflight(engine.playlist[0]) is False
    assert _decisions(events) == []


def test_no_candidates_is_a_warning_not_a_decision(monkeypatch):
    events: list[dict] = []
    engine = _armed_engine(events)
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [dict(A)])
    monkeypatch.setattr("agent.live_engine._endless_pick", lambda *a, **k: (None, "none"))

    assert engine._maybe_end_or_extend(engine.playlist[0], track_over=True) is True
    assert _decisions(events) == []
    assert any(e.get("type") == "endless_warning" for e in events)
