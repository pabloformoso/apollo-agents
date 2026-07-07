"""A-3: monotonic tick scheduler. Deterministic via injected time/sleep."""

import threading

import pytest

from agent.generative.clock import Clock


class FakeTime:
    """Deterministic clock: sleep() advances time exactly (plus optional lag)."""

    def __init__(self, lag: float = 0.0):
        self.now = 0.0
        self.lag = lag  # simulated oversleep per sleep() call

    def time(self) -> float:
        # advance a hair on every read so busy-wait loops terminate
        self.now += 1e-6
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds + self.lag


def make_clock(bpm=120, lag=0.0, spin=0.002):
    ft = FakeTime(lag)
    return Clock(bpm, time_fn=ft.time, sleep_fn=ft.sleep, spin_threshold=spin), ft


# --- construction ------------------------------------------------------------

def test_tick_seconds():
    clock, _ = make_clock(bpm=120)  # 120bpm, 24 tpb -> 48 ticks/s
    assert clock.tick_seconds == pytest.approx(60.0 / (120 * 24))


@pytest.mark.parametrize("bad", [0, -10])
def test_rejects_nonpositive_bpm(bad):
    with pytest.raises(ValueError):
        Clock(bad)


# --- scheduling ---------------------------------------------------------------

def test_calls_on_tick_for_every_tick():
    clock, _ = make_clock()
    seen = []
    clock.run(10, seen.append)
    assert seen == list(range(10))


def test_deadlines_do_not_drift():
    """Absolute scheduling: with a well-behaved sleep, lateness stays ~0."""
    clock, _ = make_clock()
    clock.run(100, lambda t: None)
    stats = clock.jitter_stats()
    assert stats["ticks"] == 100
    assert stats["max_ms"] < 1.0


def test_oversleep_recorded_as_jitter_but_no_accumulation():
    clock, ft = make_clock(lag=0.003)  # every sleep runs 3ms long
    clock.run(50, lambda t: None)
    stats = clock.jitter_stats()
    # each tick is late, but lateness is bounded (no drift compounding)
    assert 0.0 < stats["p99_ms"] < 10.0
    # total elapsed stays near the grid: 50 ticks of a 120bpm/24tpb clock
    assert ft.now == pytest.approx(49 * clock.tick_seconds, abs=0.05)


def test_stop_event_exits_early():
    clock, _ = make_clock()
    stop = threading.Event()
    seen = []

    def on_tick(t):
        seen.append(t)
        if t == 4:
            stop.set()

    clock.run(100, on_tick, stop_event=stop)
    assert seen == list(range(5))


def test_jitter_stats_empty():
    clock, _ = make_clock()
    assert clock.jitter_stats() == {"ticks": 0, "p50_ms": 0.0, "p99_ms": 0.0,
                                    "max_ms": 0.0, "mean_ms": 0.0}


def test_reset_stats():
    clock, _ = make_clock()
    clock.run(5, lambda t: None)
    clock.reset_stats()
    assert clock.jitter_stats()["ticks"] == 0


# --- real time (loose bound; the spike prints the honest numbers) --------------

def test_real_clock_short_run_keeps_reasonable_jitter():
    clock = Clock(bpm=200)  # fastest supported -> shortest run (~0.6s for 50 ticks)
    clock.run(50, lambda t: None)
    stats = clock.jitter_stats()
    assert stats["ticks"] == 50
    # generous CI bound — A3's real verdict comes from the spike's printout
    assert stats["p50_ms"] < 20.0
