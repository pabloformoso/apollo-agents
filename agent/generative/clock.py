"""Monotonic tick scheduler (A-3). Measures its own jitter (kills/confirms A3).

Absolute-deadline scheduling: deadline(tick) = start + tick * tick_seconds,
so sleep error never accumulates as drift. Near each deadline we stop
sleeping and busy-wait the last `spin_threshold` seconds — Windows
time.sleep granularity (~1-15 ms) is too coarse to trust on its own.

time_fn / sleep_fn are injectable for deterministic unit tests.
"""

from __future__ import annotations

import statistics
import time

from .interpreter import TICKS_PER_BEAT


class Clock:
    def __init__(
        self,
        bpm: float,
        ticks_per_beat: int = TICKS_PER_BEAT,
        *,
        time_fn=time.perf_counter,
        sleep_fn=time.sleep,
        spin_threshold: float = 0.002,
    ):
        if bpm <= 0:
            raise ValueError(f"bpm must be positive, got {bpm}")
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.tick_seconds = 60.0 / (bpm * ticks_per_beat)
        self._time = time_fn
        self._sleep = sleep_fn
        self._spin = spin_threshold
        self._lateness: list[float] = []  # seconds late per tick (>= 0 in practice)

    def run(self, total_ticks: int, on_tick, stop_event=None) -> None:
        """Call on_tick(tick) for tick in [0, total_ticks) at the grid deadlines.

        stop_event: optional threading.Event — checked every tick for early exit.
        """
        start = self._time()
        for tick in range(total_ticks):
            if stop_event is not None and stop_event.is_set():
                return
            deadline = start + tick * self.tick_seconds
            while True:
                now = self._time()
                remaining = deadline - now
                if remaining <= 0:
                    break
                if remaining > self._spin:
                    self._sleep(remaining - self._spin)
                # inside spin window: busy-wait
            self._lateness.append(self._time() - deadline)
            on_tick(tick)

    def jitter_stats(self) -> dict:
        """p50/p99/max/mean lateness in milliseconds over all ticks run."""
        if not self._lateness:
            return {"ticks": 0, "p50_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}
        ms = sorted(x * 1000.0 for x in self._lateness)
        n = len(ms)
        return {
            "ticks": n,
            "p50_ms": round(ms[n // 2], 3),
            "p99_ms": round(ms[min(n - 1, int(n * 0.99))], 3),
            "max_ms": round(ms[-1], 3),
            "mean_ms": round(statistics.fmean(ms), 3),
        }

    def reset_stats(self) -> None:
        self._lateness.clear()
