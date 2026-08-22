"""Unit tests for the v3.6.3 server-side stall watchdog.

The browser engine is ping-driven: a frozen operator tab (Chrome Energy
Saver) or a deck that never decoded stops the ping stream and the whole
session wedges in silence — observed live 2026-07-11 (3.5 h endless set
died mid-'Slow Oxide' with a healthy backend and a valid MP3).
``check_stall`` is the backend's self-clock: called periodically by the
live WS, it force-advances once the wall clock is past the current
track's expected end + margin AND the reported position stopped moving.
"""
from __future__ import annotations

import time

import pytest

from agent import live_engine
from agent.live_engine import (
    ENDLESS_WARNING,
    LIVE_STALL_CHECK_SEC,
    LIVE_STALL_MARGIN_SEC,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
)


def _track(
    track_id: str,
    *,
    # v3.9.1 — default above MIN_TRACK_DURATION_SEC so catalog mocks
    # pass the session-eligibility screen; playlist tracks that drive
    # the stall math keep their explicit duration_sec=60.
    duration_sec: float = 240.0,
    bpm: float = 120.0,
    camelot_key: str = "8A",
    genre_folder: str = "lofi - ambient",
) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": camelot_key,
        "duration_sec": duration_sec,
        "genre_folder": genre_folder,
        "genre": genre_folder,
        "hot_cues": [],
    }


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


def _stall(engine: LiveEngineBrowser, seconds_past_start: float) -> None:
    """Rewind the track-start anchor so the engine looks stalled."""
    engine._track_started_mono = time.monotonic() - seconds_past_start


def test_defaults_are_sane():
    assert LIVE_STALL_CHECK_SEC > 0
    assert LIVE_STALL_MARGIN_SEC > 0
    # The margin must comfortably exceed decode latency on slow hardware
    # (~2 s) but stay well under a typical track length.
    assert 10 <= LIVE_STALL_MARGIN_SEC <= 120


def test_check_stall_none_while_track_still_running():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    # Just started — nowhere near expected end.
    assert engine.check_stall() is None
    assert TRACK_ENDED not in rec.types()


def test_check_stall_none_when_position_keeps_moving():
    """extend_track / manual cf-point moves can push playback past the
    catalog duration — a MOVING position must never trip the watchdog."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    # Fresh pings with a moving position — the deck is clearly alive.
    engine.report_playback_pos(track_id="a", current_time=10.0)
    engine.report_playback_pos(track_id="a", current_time=11.0)
    assert engine.check_stall() is None


def test_check_stall_forces_advance_when_position_frozen():
    """The live failure: pings stopped (frozen tab) — wall clock passes
    the expected end + margin and the watchdog synthesises the
    track_ended the browser never sent."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    forced = engine.check_stall()
    assert forced == "a"
    types = rec.types()
    assert TRACK_ENDED in types
    assert TRACK_STARTED in types
    started = next(e for e in rec.events if e.get("type") == TRACK_STARTED)
    assert started["track"]["id"] == "b"


def test_check_stall_frozen_ping_with_static_position_also_fires():
    """A deck that failed to decode keeps pinging position ~0 forever.
    Arrival of pings alone must not count as progress."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])
    engine.report_playback_pos(track_id="a", current_time=0.1)
    # Pings keep coming but the position never moves.
    engine.report_playback_pos(track_id="a", current_time=0.1)
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    engine._last_pos_change_mono = (
        time.monotonic() - (LIVE_STALL_MARGIN_SEC + 10)
    )
    assert engine.check_stall() == "a"


def test_check_stall_extends_endless_set_on_last_track(monkeypatch):
    """Stalled on the LAST track with endless ON: the forced track_ended
    flows through the endless gate, appends a continuation, and keeps
    the set alive — this is what keeps an OBS viewer audible while the
    operator tab is frozen."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    engine._endless_mode = True
    monkeypatch.setattr(
        "agent.live_engine._load_catalog",
        lambda: [_track("rescue", bpm=122)],
    )
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    assert engine.check_stall() == "a"
    assert SESSION_ENDED not in rec.types()
    assert engine.playlist[engine._idx]["id"] == "rescue"


def test_check_stall_ends_session_when_endless_off_and_no_next(monkeypatch):
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    monkeypatch.setattr("agent.live_engine._load_catalog", lambda: [])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    rec.events.clear()
    assert engine.check_stall() == "a"
    assert SESSION_ENDED in rec.types()


def test_check_stall_none_when_idle():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60)])
    engine.stop()
    _stall(engine, seconds_past_start=1000)
    assert engine.check_stall() is None


def test_check_stall_zero_duration_uses_fallback_ceiling():
    """A malformed catalog row (duration 0) must not wedge the watchdog
    open forever — a generous fixed ceiling still applies."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=0), _track("b")])
    # Well under the 600 s ceiling → quiet.
    _stall(engine, seconds_past_start=120)
    assert engine.check_stall() is None
    # Past ceiling + margin → fires.
    _stall(engine, seconds_past_start=600 + LIVE_STALL_MARGIN_SEC + 30)
    assert engine.check_stall() == "a"


def test_check_stall_one_advance_per_call_resets_the_clock():
    """After a forced advance the new track gets a fresh clock — the
    watchdog paces a fully-frozen client at roughly track-duration
    cadence instead of machine-gunning through the playlist."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b", duration_sec=60), _track("c")])
    _stall(engine, seconds_past_start=60 + LIVE_STALL_MARGIN_SEC + 30)
    assert engine.check_stall() == "a"
    # Immediately after: 'b' just (synthetically) started — quiet.
    assert engine.check_stall() is None
    assert engine.playlist[engine._idx]["id"] == "b"


# ---------------------------------------------------------------------------
# v3.9.2 — the liveness signal must survive a REALISTIC ping cadence.
#
# Regression for the live fault of 2026-08-22: 19/19 forced advances logged
# "no playback progress ... for Ns" where N == duration + past_end, i.e.
# exactly ``now - _track_started_mono``. That is the ``(last_change or
# started)`` fallback, so ``_last_pos_change_mono`` was stale on every
# single one — including tracks that had demonstrably been pinging (they
# had already emitted APPROACHING_CF).
#
# Cause: the freshness test compared each ping against the PREVIOUS ping.
# The frontend pings every PLAYBACK_POS_INTERVAL_MS = 250 ms, so a
# perfectly healthy deck advances ~0.25 s per ping and never clears a
# 0.5 s bar. The timestamp therefore froze at the FIRST ping of every
# track and the watchdog's "position stopped moving" guard was dead code.
# ``test_check_stall_none_when_position_keeps_moving`` missed it only
# because it pings 1.0 s apart, which no real client does.
# ---------------------------------------------------------------------------

PING_DT = 0.25  # PLAYBACK_POS_INTERVAL_MS in web/frontend/lib/live.ts


class _FakeClock:
    """Controllable ``time.monotonic`` substitute.

    Needed because the engine stamps liveness with ``time.monotonic()``:
    a loop of 80 pings completes inside a single monotonic tick on
    Windows (~15.6 ms resolution), so real time cannot distinguish
    "clock advanced" from "clock froze".
    """

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


def _play_realistically(engine, clock, track_id: str, *, start: float, seconds: float):
    """Feed pings at the real 250 ms frontend cadence, advancing the clock."""
    steps = int(seconds / PING_DT)
    for i in range(1, steps + 1):
        clock.advance(PING_DT)
        engine.report_playback_pos(track_id=track_id, current_time=start + i * PING_DT)


def test_liveness_timestamp_advances_under_real_ping_cadence(clock):
    """A healthy deck pinging every 250 ms must keep the liveness clock fresh."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=240), _track("b")])

    engine.report_playback_pos(track_id="a", current_time=0.0)
    first = engine._last_pos_change_mono
    assert first is not None

    _play_realistically(engine, clock, "a", start=0.0, seconds=20.0)

    assert engine._last_pos_change_mono > first, (
        "liveness clock froze at the first ping despite 20 s of real playback — "
        "the freshness test compares consecutive pings (0.25 s apart) against a "
        "0.5 s bar, which a healthy deck can never clear"
    )
    # Fresh to within a couple of ping intervals, not stale by 20 s.
    assert clock.monotonic() - engine._last_pos_change_mono <= 2 * PING_DT


def test_healthy_deck_past_expected_end_is_not_force_advanced(clock):
    """A deck that is demonstrably playing must never be force-advanced.

    Long track, so the ping burst stays far below both the crossfade point
    and the endgame safeguard; only ``_track_started_mono`` is rewound, so
    the wall clock is past expected end + margin while the deck is live.
    A force-advance here is the audible mid-set jump, and it is exactly
    what the broken freshness test allowed: with the liveness clock frozen
    at the first ping, any burst longer than the margin looked stale.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=600), _track("b")])

    # 60 s of real pings — longer than the margin, so a first-ping-frozen
    # clock reads as stale while a correctly-refreshed one reads as fresh.
    _play_realistically(engine, clock, "a", start=0.0, seconds=60.0)
    assert engine._reported_pos_sec < engine._cf_point_seconds(engine.playlist[0])

    # Wall clock is now past expected end + margin, but the deck is alive.
    engine._track_started_mono = clock.monotonic() - (600 + LIVE_STALL_MARGIN_SEC + 30)

    assert engine.check_stall() is None, (
        "force-advanced a deck that is actively reporting movement"
    )


def test_frozen_deck_still_trips_watchdog_under_real_cadence(clock):
    """The genuine failure must still be caught: pings keep arriving at
    the real cadence but the position is stuck (decode failed), so the
    liveness clock goes stale and the watchdog fires."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])

    _play_realistically(engine, clock, "a", start=0.0, seconds=10.0)
    # Deck wedges: pings continue, position does not move.
    stuck_at = engine._reported_pos_sec
    for _ in range(int((60 + LIVE_STALL_MARGIN_SEC + 30) / PING_DT)):
        clock.advance(PING_DT)
        engine.report_playback_pos(track_id="a", current_time=stuck_at)

    rec.events.clear()
    assert engine.check_stall() == "a"
    assert TRACK_ENDED in rec.types()


def test_no_progress_figure_reflects_real_ping_activity(clock):
    """The diagnostic must measure liveness, not time-since-track-start.

    Live on 2026-08-22 all 19 forced advances printed a no-progress figure
    exactly equal to ``duration + past_end`` (= ``now - _track_started_mono``),
    the ``(last_change or started)`` fallback — proof the timestamp was
    never being refreshed.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=60), _track("b")])

    _play_realistically(engine, clock, "a", start=0.0, seconds=40.0)
    engine._track_started_mono = clock.monotonic() - 400.0  # long-running track

    since_start = clock.monotonic() - engine._track_started_mono
    since_change = clock.monotonic() - engine._last_pos_change_mono
    # The deck pinged 250 ms ago, so the figure the watchdog would print
    # must be ~0 — not the 400 s that time-since-start would report.
    assert since_change <= 2 * PING_DT, (
        f"no-progress figure ({since_change:.1f}s) tracks time-since-start "
        f"({since_start:.0f}s) instead of real ping activity"
    )


# ---------------------------------------------------------------------------
# v3.9.2 — forced-advance behaviour: fire on the freeze, ramp not splice.
# ---------------------------------------------------------------------------


def _commands(rec: _Recorder) -> list[str]:
    return [
        e.get("command") for e in rec.events if e.get("type") == "engine_command"
    ]


def _die_mid_track(engine, clock, track_id: str, *, played: float, frozen_for: float):
    """Play for a while at the real cadence, then wedge (no more pings)."""
    _play_realistically(engine, clock, track_id, start=0.0, seconds=played)
    clock.advance(frozen_for)


def test_stall_fires_on_the_freeze_not_at_the_nominal_end(clock):
    """The live fault: decks died 21–52 % in. Waiting for expected_end +
    margin burned the whole remainder as dead air (2m40s–3m30s measured).
    A deck frozen for the margin must be advanced right away."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    # 600 s track; die 60 s in. The old gate would have waited ~9 more
    # minutes; the new one fires one margin after the freeze.
    engine.play([_track("a", duration_sec=600), _track("b")])

    _die_mid_track(engine, clock, "a", played=60.0, frozen_for=LIVE_STALL_MARGIN_SEC - 5)
    assert engine.check_stall() is None, "fired before the margin elapsed"

    clock.advance(10)  # now past the margin, still far from expected_end
    assert clock.monotonic() - engine._track_started_mono < 600, (
        "test no longer exercises the early path"
    )
    assert engine.check_stall() == "a"


def test_forced_advance_ramps_instead_of_hard_cutting(clock):
    """v3.6.3 forced a ``stop_deck`` + ``load`` splice — the audible jump.
    With a next track queued the watchdog must run the normal crossfade."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=600), _track("b")])

    _die_mid_track(engine, clock, "a", played=60.0, frozen_for=LIVE_STALL_MARGIN_SEC + 5)
    rec.events.clear()
    assert engine.check_stall() == "a"

    cmds = _commands(rec)
    assert "crossfade" in cmds, f"expected a ramp, got {cmds}"
    assert "stop_deck" not in cmds, "still hard-cutting the deck"
    types = rec.types()
    assert live_engine.CROSSFADE_TRIGGERED in types
    assert TRACK_ENDED in types
    started = next(e for e in rec.events if e.get("type") == TRACK_STARTED)
    assert started["track"]["id"] == "b"


def test_forced_advance_on_last_track_still_runs_the_endless_gate(clock, monkeypatch):
    """No next deck to ramp into — must fall back to report_track_ended so
    endless mode can append a successor rather than dying silently."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=600)])
    engine._endless_mode = True
    monkeypatch.setattr(
        "agent.live_engine._load_catalog", lambda: [_track("rescue", bpm=122)]
    )

    _die_mid_track(engine, clock, "a", played=60.0, frozen_for=LIVE_STALL_MARGIN_SEC + 5)
    rec.events.clear()
    assert engine.check_stall() == "a"
    assert SESSION_ENDED not in rec.types()
    assert engine.playlist[engine._idx]["id"] == "rescue"


def test_never_pinged_track_keeps_duration_paced_gate(clock):
    """A fully frozen tab never pings at all. That branch re-arms on every
    forced advance, so firing it on the short margin would machine-gun the
    whole playlist at one track per margin. It must stay duration-paced."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a", duration_sec=600), _track("b")])

    assert engine._last_pos_change_mono is None
    clock.advance(LIVE_STALL_MARGIN_SEC * 3)  # long past the short margin
    assert engine.check_stall() is None, "machine-gunning a never-pinged client"

    clock.advance(600)  # now past expected end + margin
    assert engine.check_stall() == "a"
