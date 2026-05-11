"""Verify ``Session.to_dict`` exposes v2.6.0 fields (notes, handled, arc,
set_health) and that the serialize/rehydrate round-trip preserves them.
"""
from __future__ import annotations

from web.backend.session_store import Session


def _seed_session() -> Session:
    s = Session("sess-1", user_id=1)
    s.context_variables["playlist"] = [
        {"id": "a", "display_name": "A", "bpm": 60, "camelot_key": "8A"},
        {"id": "b", "display_name": "B", "bpm": 100, "camelot_key": "9A"},
        {"id": "c", "display_name": "C", "bpm": 130, "camelot_key": "10A"},
    ]
    s.structured_problems = [
        {
            "pos_from": 1,
            "pos_to": 2,
            "key_pair": "Am → Em",
            "bpm_diff": 8,
            "text": "Steep jump. Try a bridge.",
        }
    ]
    s.set_health = 88
    return s


def test_to_dict_emits_v260_fields():
    s = _seed_session()
    d = s.to_dict()
    assert "notes" in d
    assert "handled" in d
    assert "arc" in d
    assert "set_health" in d
    assert d["set_health"] == 88
    assert len(d["notes"]) == 1
    note = d["notes"][0]
    assert note["severity"] == "fix"
    assert note["target"] == "1–2"
    assert note["status"] == "pending"
    assert d["arc"] is not None
    assert d["arc"]["points"] == [1.0, 50/12, 80/12]
    assert d["arc"]["peak_pos"] == 2


def test_handled_notes_round_trip():
    s = _seed_session()
    # Pick the canonical id for the seeded problem.
    nid = s.to_dict()["notes"][0]["id"]
    s.handled_notes[nid] = "ignored"

    blob = s._serialize()
    rehydrated = Session._from_row({
        "id": s.id,
        "user_id": str(s.user_id),
        "created_at": s.created_at,
        "data": blob,
    })
    assert rehydrated.handled_notes == {nid: "ignored"}
    assert rehydrated.set_health == 88

    out = rehydrated.to_dict()
    assert out["handled"] == [nid]
    assert out["notes"][0]["status"] == "ignored"


def test_arc_is_none_for_empty_playlist():
    s = Session("sess-2", user_id=1)
    d = s.to_dict()
    assert d["arc"] is None
    assert d["notes"] == []
    assert d["handled"] == []
    assert d["set_health"] is None
