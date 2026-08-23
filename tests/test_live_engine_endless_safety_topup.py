"""v3.9.4 — a track must never play with an empty queue behind it.

Live fault, session 4be54b5d on 2026-08-23. The litellm gateway went
unreachable, so ``run_agent_streaming`` raised ``APITimeoutError`` on
every turn and the DJ returned ``response_len=0`` sixteen times out of
twenty-one. With the agent mute the deterministic fallback was the only
thing extending the set — and it only ran at end-of-track, appending a
single successor. The cursor then advanced onto that successor, leaving
``remaining_after=0`` for the whole of its playback.

Two decks died in that window:

    'Quiet Ember' — at 20.3s of 213.8s (9%); PREMATURE, 193.5s short
    'Calm Bloom'  — at  0.0s of 179.8s (0%); PREMATURE, 179.8s short

Both had to be force-advanced with a hard cut, because ``check_stall``
can only ramp into a deck the browser has already pre-loaded — and with
an empty queue there was none. That hard cut is what the listener hears
as a jump, and it cost 47 s and 57 s of dead air respectively.

The v3.6 in-flight extend was meant to prevent exactly this, but it only
ran once the last track was PAST its crossfade point — roughly 17 s
before the deck drains. Everything earlier in the track was unprotected,
which is precisely where both decks died.

Note that appending *two* tracks at end-of-track does not fix this: the
gate only runs when the queue reaches zero, and the cursor advance puts
it straight back to zero every other track. The queue has to be topped
up from the ping path, which is what these tests pin down.
"""
from __future__ import annotations

import pytest

from agent import live_engine
from agent.live_engine import (
    ENDLESS_GRACE_SEC,
    LIVE_STALL_MARGIN_SEC,
    TRACK_STARTED,
    LiveEngineBrowser,
)

PING_DT = 0.25  # PLAYBACK_POS_INTERVAL_MS in web/frontend/lib/live.ts


def _track(
    track_id: str,
    *,
    duration_sec: float = 600.0,
    bpm: float = 120.0,
    genre_folder: str = "lofi - ambient",
) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
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

    def commands(self) -> list[str]:
        return [
            e.get("command") for e in self.events if e.get("type") == "engine_command"
        ]


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


@pytest.fixture()
def catalog(monkeypatch):
    """Catalog with a rescue track, counting how often it is read."""
    reads = {"n": 0}

    def _load():
        reads["n"] += 1
        return [_track("rescue", bpm=121), _track("rescue2", bpm=122)]

    monkeypatch.setattr("agent.live_engine._load_catalog", _load)
    return reads


def _play(engine, clock, track_id: str, *, start: float, seconds: float) -> None:
    """Feed pings at the real 250 ms cadence, advancing the fake clock."""
    for i in range(1, int(seconds / PING_DT) + 1):
        clock.advance(PING_DT)
        engine.report_playback_pos(track_id=track_id, current_time=start + i * PING_DT)


def _endless(engine: LiveEngineBrowser) -> None:
    engine._endless_mode = True


# ── the payoff: a stall early in the track can now ramp ────────────────


def test_early_stall_ramps_instead_of_hard_cutting(clock, catalog):
    """The 'Quiet Ember' case: deck dies 20 s into a long track.

    Before v3.9.4 the queue was still empty at that point, so the
    watchdog had nothing pre-loaded and spliced. The top-up must have
    queued a successor by then so the normal ramp runs.
    """
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=20.0)
    rec.events.clear()
    clock.advance(LIVE_STALL_MARGIN_SEC + 5)

    assert engine.check_stall() == "a"

    cmds = rec.commands()
    assert "crossfade" in cmds, f"expected a ramp, got {cmds}"
    assert "stop_deck" not in cmds, "still hard-cutting — the audible jump"
    started = next(e for e in rec.events if e.get("type") == TRACK_STARTED)
    assert started["track"]["id"] == "rescue"


def test_deck_that_never_starts_still_gets_a_successor(clock, catalog):
    """The 'Calm Bloom' case: pings arrive but the position stays at 0."""
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    _endless(engine)

    for _ in range(int(10.0 / PING_DT)):
        clock.advance(PING_DT)
        engine.report_playback_pos(track_id="a", current_time=0.0)

    assert len(engine.playlist) == 2, "no successor queued for a dead-on-arrival deck"
    rec.events.clear()
    clock.advance(LIVE_STALL_MARGIN_SEC + 5)
    assert engine.check_stall() == "a"
    assert "crossfade" in rec.commands()


# ── the top-up itself ──────────────────────────────────────────────────


def test_empty_queue_is_topped_up_early_in_the_track(clock, catalog):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=ENDLESS_GRACE_SEC + 2)

    assert [t["id"] for t in engine.playlist] == ["a", "rescue"]


def test_grace_is_respected_before_topping_up(clock, catalog):
    """The LLM keeps priority — the fallback waits out its window."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=ENDLESS_GRACE_SEC - 1)

    assert len(engine.playlist) == 1, "jumped the gun on the agent's grace window"


def test_healthy_queue_is_never_touched(clock, catalog):
    """A DJ that keeps up holds remaining >= 1, so this must not engage.

    The catalog read is the tell: it must not happen at all, or an
    endless set would scan tracks.json at ping rate.
    """
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a"), _track("b")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=30.0)

    assert [t["id"] for t in engine.playlist] == ["a", "b"]
    assert catalog["n"] == 0, "scanned the catalog with a healthy queue"


def test_endless_off_is_left_to_end(clock, catalog):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a")])

    _play(engine, clock, "a", start=0.0, seconds=30.0)

    assert len(engine.playlist) == 1
    assert catalog["n"] == 0


def test_topup_is_one_shot_per_track(clock, monkeypatch):
    """A fruitless scan must not repeat at the 4 Hz ping rate."""
    reads = {"n": 0}

    def _empty():
        reads["n"] += 1
        return []

    monkeypatch.setattr("agent.live_engine._load_catalog", _empty)
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=30.0)

    assert reads["n"] <= 1, f"scanned the catalog {reads['n']}x for one track"
    assert len(engine.playlist) == 1


def test_topup_re_arms_on_the_next_track(clock, catalog):
    """One-shot is per track, not per session — the next one needs it too."""
    engine = LiveEngineBrowser(emitter=lambda _ev: None)
    engine.play([_track("a")])
    _endless(engine)

    _play(engine, clock, "a", start=0.0, seconds=ENDLESS_GRACE_SEC + 2)
    assert [t["id"] for t in engine.playlist] == ["a", "rescue"]

    # Advance onto 'rescue'; its own queue is empty again.
    engine.report_track_ended("a")
    _play(engine, clock, "rescue", start=0.0, seconds=ENDLESS_GRACE_SEC + 2)

    assert [t["id"] for t in engine.playlist] == ["a", "rescue", "rescue2"]
