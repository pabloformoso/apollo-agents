"""v3.9.6 — record where each crossfade fired, in both clocks.

The operator reports songs cut mid-track in endless mode (2026-08-24),
intermittently. The backend log rules out every advance path that logs:
no ``check_stall``, no ``[engine track_ended]`` (so no browser
``track_ended`` and no watchdog), no ``skip_track``, no
``set_crossfade_point``, no ``critic_warning``. Reproducing the planner
offline against the live catalog puts every crossfade point at 82-92 %
of its track, so the threshold is not moving.

That leaves the position. The crossfade fires on
``reported_pos >= cf_point``, so a mid-track cut requires the reported
position to have jumped ahead — the threshold cannot come to it.

On-air time cannot be derived from the existing log: ``[beatmatch]`` is
emitted when the transition plan is BUILT, which lags whenever the queue
is momentarily empty, so the same 'Moon Tide' -> 'Silent Bloom' pair
measured 86 % on one pass and 55 % on another. Only one of those can be
true and the log cannot say which.

Wall clock is the independent witness. The browser deck runs between
1.0x and roughly 1.25x, so a position advancing far faster than the
clock is physically impossible and convicts the ping; a ratio near 1.0
exonerates it and points at the frontend instead.
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


def _drive_to_crossfade(engine, clock, track_id, *, pos, wall):
    """Park the deck at ``pos`` after ``wall`` seconds of clock."""
    clock.advance(wall)
    engine.report_playback_pos(track_id=track_id, current_time=pos)


# ── the honest case ────────────────────────────────────────────────────


def test_healthy_transition_reports_pos_tracking_wall_clock(clock, capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])

    # cf_point = 240 - 12 - 5 = 223. Deck played honestly to get there.
    _drive_to_crossfade(engine, clock, "a", pos=223.5, wall=223.5)

    (line,) = _lines(capsys)
    assert "'Track a' -> 'Track b'" in line
    assert "fired at pos=223.5s of 240.0s (93%)" in line
    assert "cf_point=223.0s" in line
    assert "pos_per_wall=1.00" in line


def test_a_sped_up_deck_still_reads_as_plausible(clock, capsys):
    """Beatmatching runs the incoming deck fast; ~1.23x is the observed top."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b")])

    _drive_to_crossfade(engine, clock, "a", pos=223.5, wall=223.5 / 1.23)

    (line,) = _lines(capsys)
    assert "pos_per_wall=1.23" in line


# ── the case under investigation ───────────────────────────────────────


def test_mid_track_cut_is_convicted_by_the_wall_clock(clock, capsys):
    """A position that outran the clock: the cut the operator hears.

    Same numbers as the live 'Moon Tide' reading — a 272.7 s track whose
    crossfade fired at its legitimate 250.7 s point after only 149 s of
    wall clock, i.e. the deck was really less than 55 % through.
    """
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=272.7), _track("b")])

    _drive_to_crossfade(engine, clock, "a", pos=256.0, wall=149.0)

    (line,) = _lines(capsys)
    assert "fired at pos=256.0s of 272.7s (94%)" in line
    # 256 / 149 = 1.72 — no playback rate reaches that.
    assert "pos_per_wall=1.72" in line


def test_every_crossfade_is_logged_across_a_chain(clock, capsys):
    """One line per transition — the series is what makes a pattern visible."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=240.0), _track("b", duration_sec=240.0), _track("c")])

    _drive_to_crossfade(engine, clock, "a", pos=223.5, wall=223.5)
    _drive_to_crossfade(engine, clock, "b", pos=223.5, wall=223.5)

    lines = _lines(capsys)
    assert len(lines) == 2
    assert "'Track a' -> 'Track b'" in lines[0]
    assert "'Track b' -> 'Track c'" in lines[1]


# ── edge cases ─────────────────────────────────────────────────────────


def test_zero_duration_does_not_break_the_line(clock, capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=0.0), _track("b")])

    _drive_to_crossfade(engine, clock, "a", pos=5.0, wall=5.0)

    (line,) = _lines(capsys)
    assert "of 0.0s (?)" in line


def test_unanchored_track_says_so_instead_of_guessing(capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.playlist = [_track("a"), _track("b")]
    engine._state = "playing"
    engine._track_started_mono = None

    engine._begin_crossfade(engine.playlist[0], engine.playlist[1])

    (line,) = _lines(capsys)
    assert "wall unknown (track never anchored)" in line


def test_watchdog_forced_ramp_is_logged_too(clock, capsys):
    """check_stall ramps through the same method — it must leave a line."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a", duration_sec=600.0), _track("b")])
    engine.report_playback_pos(track_id="a", current_time=30.0)
    engine._last_pos_change_mono = (
        live_engine.time.monotonic() - (live_engine.LIVE_STALL_MARGIN_SEC + 5)
    )

    assert engine.check_stall() == "a"

    (line,) = _lines(capsys)
    assert "fired at pos=30.0s of 600.0s (5%)" in line
