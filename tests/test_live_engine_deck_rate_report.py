"""v3.9.7 — the deck reports the rate it is actually running at.

Live on 2026-08-24, two transitions fired with ``pos_per_wall = 1.56``.
Back-solving each with the phase-lock anchors the engine had computed
gives the same answer to four figures::

    Moon Tide   (233.2 - 9.77) / 149.0 = 1.4995   plan said 0.9799
    Faint Bloom (231.0 - 8.33) / 148.5 = 1.4995   plan said 0.9884

Exactly 1.50 on two unrelated pairs, where every ``static_rate`` in that
session ran between 0.83 and 1.23. A deck at 1.5x eats its track in two
thirds of the time, which is the mid-track cut the operator hears.

The engine could not see this directly. ``position()`` in
audio_buffer_decks.ts is a model — ``offsetAtStart + elapsed *
rateAtStart`` — not a measurement of the audio, so a deck running at the
wrong rate reports a position derived from that same wrong rate. The two
agree with each other and the result looks self-consistent from outside.
``pos_per_wall`` only caught it because wall clock is independent, and
even then it cannot say WHY.

So the deck now ships the two terms its position is built from, and the
engine checks them against the rate the transition plan asked for.
"""
from __future__ import annotations

import pytest

from agent import live_engine
from agent.live_engine import LiveEngineBrowser


def _track(track_id: str, *, duration_sec: float = 240.0, bpm: float = 120.0) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "genre_folder": "lofi - ambient",
        "genre": "lofi - ambient",
        "hot_cues": [],
    }


class _FakeClock:
    def __init__(self, start: float = 10_000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    fake = _FakeClock()
    monkeypatch.setattr(live_engine.time, "monotonic", fake.monotonic)
    return fake


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [
        ln
        for ln in capsys.readouterr().out.splitlines()
        if ln.startswith("[engine crossfade]")
    ]


# ── the ping carries the deck's own terms ──────────────────────────────


def test_deck_rate_and_offset_are_recorded(clock):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a"), _track("b")])

    engine.report_playback_pos("a", 10.0, deck_rate=1.5, deck_offset=9.77)

    assert engine._deck_rate == pytest.approx(1.5)
    assert engine._deck_offset == pytest.approx(9.77)


def test_absent_fields_leave_the_previous_reading_alone(clock):
    """An older frontend omits them; that must not wipe a good reading."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a"), _track("b")])

    engine.report_playback_pos("a", 10.0, deck_rate=1.5, deck_offset=9.77)
    engine.report_playback_pos("a", 11.0)

    assert engine._deck_rate == pytest.approx(1.5)


def test_stale_ping_cannot_set_the_deck_terms(clock):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a"), _track("b")])

    engine.report_playback_pos("someone-else", 10.0, deck_rate=1.5)

    assert engine._deck_rate is None


# ── planned vs applied, in the crossfade line ──────────────────────────


def test_rate_mismatch_is_flagged(clock, capsys):
    """The live shape: plan asked ~0.98, deck ran at 1.50."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b"), _track("c")])
    # Advance onto 'b' so a planned incoming rate is on record.
    engine._planned_incoming_rate = 0.9799

    clock.advance(149.0)
    engine.report_playback_pos("a", 223.5, deck_rate=1.4995, deck_offset=9.77)

    (line,) = _lines(capsys)
    assert "deck rate=1.500" in line
    assert "planned 0.980" in line
    assert "offset=9.8s" in line
    assert "RATE MISMATCH" in line


def test_matching_rate_is_not_flagged(clock, capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])
    engine._planned_incoming_rate = 0.9799

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5, deck_rate=0.98, deck_offset=0.0)

    (line,) = _lines(capsys)
    assert "deck rate=0.980" in line
    assert "RATE MISMATCH" not in line


def test_small_drift_stays_under_the_threshold(clock, capsys):
    """5 % tolerance — ramps and rounding must not cry wolf."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])
    engine._planned_incoming_rate = 1.0

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5, deck_rate=1.04, deck_offset=0.0)

    (line,) = _lines(capsys)
    assert "RATE MISMATCH" not in line


def test_no_deck_report_says_so_rather_than_guessing(clock, capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5)

    (line,) = _lines(capsys)
    assert "deck rate=n/a (frontend not reporting)" in line
    assert "RATE MISMATCH" not in line


def test_no_planned_rate_reports_the_deck_without_a_verdict(clock, capsys):
    """The very first track never went through a crossfade."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5, deck_rate=1.5, deck_offset=0.0)

    (line,) = _lines(capsys)
    assert "planned n/a" in line
    assert "RATE MISMATCH" not in line


# ── per-track scoping ──────────────────────────────────────────────────


def test_deck_terms_reset_on_advance_so_they_never_cross_tracks(clock):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b", duration_sec=240.0)])

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5, deck_rate=1.5, deck_offset=9.0)

    # The crossfade advanced onto 'b'; its deck has not reported yet.
    assert engine._deck_rate is None
    assert engine._deck_offset is None


def test_advance_records_the_rate_we_asked_the_browser_for(clock):
    """The plan's incoming_rate becomes the next track's expectation."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0, bpm=120.0), _track("b", bpm=126.0)])

    clock.advance(223.5)
    engine.report_playback_pos("a", 223.5)

    assert engine._planned_incoming_rate is not None
    assert 0.5 < engine._planned_incoming_rate < 2.0
