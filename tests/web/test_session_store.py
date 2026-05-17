"""Unit tests for web/backend/session_store.py in-memory state."""
from __future__ import annotations

from web.backend.session_store import Session, SessionStore


def test_create_returns_unique_ids():
    store = SessionStore()
    s1 = store.create(user_id=1)
    s2 = store.create(user_id=1)
    assert s1.id != s2.id
    assert s1.user_id == s2.user_id == 1


def test_get_returns_session_or_none():
    store = SessionStore()
    s = store.create(user_id=7)
    assert store.get(s.id) is s
    assert store.get("nope") is None


def test_get_user_sessions_filters_by_user():
    store = SessionStore()
    a1 = store.create(user_id=1)
    a2 = store.create(user_id=1)
    b1 = store.create(user_id=2)

    user_1 = store.get_user_sessions(1)
    user_2 = store.get_user_sessions(2)
    assert {s.id for s in user_1} == {a1.id, a2.id}
    assert {s.id for s in user_2} == {b1.id}
    assert store.get_user_sessions(999) == []


def test_delete_removes_from_both_maps():
    store = SessionStore()
    s = store.create(user_id=1)
    store.delete(s.id)
    assert store.get(s.id) is None
    assert store.get_user_sessions(1) == []


def test_delete_of_unknown_id_is_noop():
    store = SessionStore()
    store.delete("nonexistent")  # must not raise


def test_to_dict_on_empty_context():
    s = Session("abc", user_id=1)
    d = s.to_dict()
    assert d["id"] == "abc"
    assert d["user_id"] == 1
    assert d["phase"] == "init"
    assert d["playlist"] == []
    assert d["genre"] is None


def test_to_dict_sanitizes_playlist_fields():
    """Projection allow-lists the fields the frontend needs and drops
    everything else. v2.7.3 added ``beatgrid`` + ``waveform_peaks`` to
    the allow-list so /live can render real waveforms / beat-aligned
    visuals instead of falling back to the synthetic sin pattern; this
    test guards both that they ARE surfaced AND that arbitrary extra
    fields ARE still dropped (no information leak)."""
    s = Session("abc", user_id=1)
    s.context_variables["genre"] = "techno"
    s.context_variables["playlist"] = [
        {
            "id": "t1",
            "display_name": "Track",
            "bpm": 128,
            "camelot_key": "9A",
            "duration_sec": 300,
            "genre": "techno",
            "beatgrid": {"bpm": 128.0, "first_beat_sec": 0.012},
            "waveform_peaks": [0.1, 0.2, 0.3],
            "secret_field": "should-be-dropped",
            "file": "/absolute/path/should-not-leak.wav",
        }
    ]
    d = s.to_dict()
    track = d["playlist"][0]
    assert set(track.keys()) == {
        "id",
        "display_name",
        "bpm",
        "camelot_key",
        "duration_sec",
        "genre",
        "beatgrid",
        "waveform_peaks",
    }
    # Sanity check that the new fields preserve their structure end-to-end.
    assert track["beatgrid"] == {"bpm": 128.0, "first_beat_sec": 0.012}
    assert track["waveform_peaks"] == [0.1, 0.2, 0.3]
    # Negative assertions: arbitrary fields must still be stripped — the
    # projection is an allow-list, not a deny-list, and a regression that
    # accidentally widened it could leak file paths or secrets.
    assert "secret_field" not in track
    assert "file" not in track
    assert d["genre"] == "techno"


def test_to_dict_playlist_missing_beatgrid_or_peaks_is_none():
    """Legacy entries (catalogged before v2 beatgrid + before the waveform
    analyser ran) don't have these keys. The projection must surface
    ``None`` rather than KeyError-ing or omitting the field, so the
    frontend's ``track.beatgrid ?? null`` fallback fires."""
    s = Session("abc", user_id=1)
    s.context_variables["playlist"] = [
        {
            "id": "t1",
            "display_name": "Legacy",
            "bpm": 100,
            "camelot_key": "5A",
            "duration_sec": 200,
            "genre": "lofi - ambient",
        }
    ]
    track = s.to_dict()["playlist"][0]
    assert track["beatgrid"] is None
    assert track["waveform_peaks"] is None
