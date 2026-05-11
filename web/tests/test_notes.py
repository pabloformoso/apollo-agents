"""Unit tests for v2.6.0 ``web.backend.notes``."""
from __future__ import annotations

from web.backend.notes import adapt, note_id, to_critic_notes


def _problem(**overrides) -> dict:
    base = {
        "pos_from": 2,
        "pos_to": 3,
        "key_pair": "Dm → Am",
        "bpm_diff": 8,
        "text": "Transition too steep. Consider a bridge track.",
    }
    base.update(overrides)
    return base


def test_note_id_is_deterministic():
    p = _problem()
    assert note_id(p) == note_id(p)
    assert note_id(p) != note_id(_problem(text="something else"))


def test_severity_fix_when_bpm_diff_exceeds_threshold():
    note = adapt(_problem(bpm_diff=8), {})
    assert note["severity"] == "fix"


def test_severity_tip_when_bpm_diff_small():
    note = adapt(_problem(bpm_diff=2), {})
    assert note["severity"] == "tip"


def test_target_collapses_same_position():
    note = adapt(_problem(pos_from=4, pos_to=4), {})
    assert note["target"] == "4"


def test_target_range_when_positions_differ():
    note = adapt(_problem(pos_from=2, pos_to=5), {})
    assert note["target"] == "2–5"


def test_headline_is_first_sentence_body_is_rest():
    note = adapt(
        _problem(text="Energy plateau at track 3. Insert a peak track to lift."),
        {},
    )
    assert note["headline"] == "Energy plateau at track 3."
    assert note["body"] == "Insert a peak track to lift."


def test_suggestion_extracted_from_consider_prefix():
    note = adapt(_problem(text="BPM gap. Consider: insert a bridge track."), {})
    assert note["suggestion"] == "insert a bridge track"


def test_suggestion_none_when_missing():
    note = adapt(_problem(text="Just a flat statement with no try-line."), {})
    assert note["suggestion"] is None


def test_status_reflects_handled_dict():
    p = _problem()
    nid = note_id(p)
    assert adapt(p, {nid: "applied"})["status"] == "applied"
    assert adapt(p, {nid: "ignored"})["status"] == "ignored"
    assert adapt(p, {})["status"] == "pending"


def test_to_critic_notes_handles_empty_and_none():
    assert to_critic_notes(None) == []
    assert to_critic_notes([]) == []


def test_to_critic_notes_maps_all_items():
    problems = [_problem(), _problem(pos_from=5, pos_to=5, text="Different issue.")]
    notes = to_critic_notes(problems, {})
    assert len(notes) == 2
    assert {n["id"] for n in notes} == {note_id(p) for p in problems}
