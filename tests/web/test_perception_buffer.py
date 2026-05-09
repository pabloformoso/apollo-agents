"""Unit tests for the v2.5.2 perception buffer + audience-request batcher.

The relay coroutine sits between the WS-side queue (which receives raw
``perception_sample`` / ``user_msg`` items) and the agent loop's inner
queue (which consumes synthetic ``environment_changed`` /
``audience_request_batch`` events). These tests poke the relay directly
so we can assert delta-detection and rate-limiting behaviour without
spinning up the full WS handler.
"""
from __future__ import annotations

import asyncio

import pytest

from web.backend.pipeline import (
    PERCEPTION_BUFFER_LEN,
    _detect_environment_change,
    _live_relay,
    _perception_window_means,
)


def test_perception_window_means_empty():
    rms_mean, voice_mean = _perception_window_means([])
    assert rms_mean == 0.0
    assert voice_mean is None


def test_perception_window_means_aggregates():
    buf = [
        {"rms_db": -60.0, "voice_likelihood": 0.1},
        {"rms_db": -50.0, "voice_likelihood": 0.2},
        {"rms_db": -40.0, "voice_likelihood": None},
    ]
    rms_mean, voice_mean = _perception_window_means(buf)
    assert rms_mean == pytest.approx(-50.0)
    # Only the non-None entries contribute to voice_mean.
    assert voice_mean == pytest.approx(0.15)


def test_perception_window_means_voice_none_when_all_missing():
    buf = [{"rms_db": -55.0, "voice_likelihood": None}] * 4
    _, voice_mean = _perception_window_means(buf)
    assert voice_mean is None


def test_detect_environment_change_no_shift():
    out = _detect_environment_change(
        (-55.0, 0.1), (-54.5, 0.1)
    )
    assert out is None


def test_detect_environment_change_db_jump_up():
    out = _detect_environment_change((-60.0, 0.0), (-50.0, 0.0))
    assert out is not None
    assert out["type"] == "environment_changed"
    assert out["rms_db_delta"] == pytest.approx(10.0)
    assert out["rms_db_mean"] == pytest.approx(-50.0)


def test_detect_environment_change_db_drop():
    out = _detect_environment_change((-40.0, 0.0), (-50.0, 0.0))
    assert out is not None
    assert out["rms_db_delta"] == pytest.approx(-10.0)


def test_detect_environment_change_voice_drop():
    out = _detect_environment_change((-55.0, 0.9), (-55.0, 0.2))
    assert out is not None
    assert "voice_likelihood_delta" in out


@pytest.mark.asyncio
async def test_relay_passthrough_engine_events():
    """Engine events (track_started etc) pass through verbatim."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}
    await src.put({"type": "track_started", "track": {"id": "t1"}})
    task = asyncio.create_task(_live_relay(src, inner, ctx))
    out = await asyncio.wait_for(inner.get(), timeout=1.0)
    assert out["type"] == "track_started"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_relay_perception_emits_environment_changed_on_delta():
    """A 6 dB shift between consecutive windows triggers environment_changed."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    fake_now = [0.0]

    def fake_clock() -> float:
        return fake_now[0]

    task = asyncio.create_task(_live_relay(src, inner, ctx, now=fake_clock))
    try:
        # First window: settle a baseline at -60 dB.
        for _ in range(3):
            await src.put(
                {
                    "type": "perception_sample",
                    "rms_db": -60.0,
                    "onset_density_hz": 0.0,
                    "voice_likelihood": None,
                }
            )
        # Second window: enough -50 samples that the rolling mean shifts
        # past the 6 dB threshold. The buffer caps at 10 — after 10 new
        # -50 samples the mean is exactly -50 (delta = +10 dB from the
        # -60 dB baseline).
        for _ in range(12):
            await src.put(
                {
                    "type": "perception_sample",
                    "rms_db": -50.0,
                    "onset_density_hz": 0.0,
                    "voice_likelihood": None,
                }
            )
        # Drain inner queue; we expect at least one environment_changed event.
        synthetic: list[dict] = []
        for _ in range(20):
            try:
                ev = await asyncio.wait_for(inner.get(), timeout=0.2)
            except asyncio.TimeoutError:
                break
            synthetic.append(ev)
        kinds = [e["type"] for e in synthetic]
        assert "environment_changed" in kinds
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_relay_perception_rate_limits_environment_changed():
    """Two delta crossings within 30 s → only one environment_changed event."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    fake_now = [0.0]

    def fake_clock() -> float:
        return fake_now[0]

    task = asyncio.create_task(_live_relay(src, inner, ctx, now=fake_clock))
    try:
        # Window A: baseline at -70 dB
        for _ in range(3):
            await src.put({"type": "perception_sample", "rms_db": -70.0, "voice_likelihood": None})
        # Window B: +15 dB shift (need enough samples to overflow the buffer)
        for _ in range(12):
            await src.put({"type": "perception_sample", "rms_db": -55.0, "voice_likelihood": None})
        await asyncio.sleep(0.05)
        # Now another swing — still within the 30 s rate-limit window.
        fake_now[0] = 5.0
        for _ in range(12):
            await src.put({"type": "perception_sample", "rms_db": -75.0, "voice_likelihood": None})
        await asyncio.sleep(0.1)

        synthetic: list[dict] = []
        for _ in range(30):
            try:
                ev = await asyncio.wait_for(inner.get(), timeout=0.05)
            except asyncio.TimeoutError:
                break
            synthetic.append(ev)
        env_events = [e for e in synthetic if e["type"] == "environment_changed"]
        assert len(env_events) == 1
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_relay_user_msg_control_passthrough():
    """Control words ("skip", "stay") pass through immediately as user_msg."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    task = asyncio.create_task(_live_relay(src, inner, ctx))
    try:
        await src.put({"type": "user_msg", "text": "skip"})
        out = await asyncio.wait_for(inner.get(), timeout=1.0)
        assert out["type"] == "user_msg"
        assert out["text"] == "skip"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_relay_audience_requests_batch_within_5s():
    """Three audience requests within the 5 s window collapse into one
    audience_request_batch event."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    fake_now = [0.0]

    def fake_clock() -> float:
        return fake_now[0]

    task = asyncio.create_task(_live_relay(src, inner, ctx, now=fake_clock))
    try:
        for txt in ("play more techno", "drop the bass", "more groove"):
            await src.put({"type": "user_msg", "text": txt})
        # Advance past the 5 s batch window → relay should flush.
        await asyncio.sleep(0.1)
        fake_now[0] = 6.0
        # Wake the relay by putting a no-op item it will pass through.
        await src.put({"type": "track_started", "track": {"id": "x"}})

        events: list[dict] = []
        for _ in range(20):
            try:
                ev = await asyncio.wait_for(inner.get(), timeout=0.5)
            except asyncio.TimeoutError:
                break
            events.append(ev)

        batches = [e for e in events if e["type"] == "audience_request_batch"]
        assert len(batches) == 1
        assert len(batches[0]["requests"]) == 3
        texts = [r["text"] for r in batches[0]["requests"]]
        assert "play more techno" in texts
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_relay_audience_rate_limit_drops_second_batch():
    """A second batch within 30 s of the first is dropped (logged on ctx)."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    fake_now = [0.0]

    def fake_clock() -> float:
        return fake_now[0]

    task = asyncio.create_task(_live_relay(src, inner, ctx, now=fake_clock))
    try:
        # First batch.
        await src.put({"type": "user_msg", "text": "first ask"})
        await asyncio.sleep(0.05)
        fake_now[0] = 6.0
        # Wake the relay after the batch window has elapsed.
        await src.put({"type": "track_started", "track": {"id": "a"}})
        await asyncio.sleep(0.2)

        # Second batch starts at t=10 (still within 30 s of last_audience_emit).
        fake_now[0] = 10.0
        await src.put({"type": "user_msg", "text": "second ask"})
        await asyncio.sleep(0.05)
        fake_now[0] = 16.0
        await src.put({"type": "track_started", "track": {"id": "b"}})
        await asyncio.sleep(0.2)

        events: list[dict] = []
        for _ in range(20):
            try:
                ev = await asyncio.wait_for(inner.get(), timeout=0.2)
            except asyncio.TimeoutError:
                break
            events.append(ev)
        batches = [e for e in events if e["type"] == "audience_request_batch"]
        assert len(batches) == 1
        # Dropped requests are recorded on the ctx for telemetry / inspection.
        assert any(
            r["text"] == "second ask" for r in ctx.get("audience_dropped", [])
        )
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_relay_perception_buffer_capped():
    """The buffer never grows beyond ``PERCEPTION_BUFFER_LEN``."""
    src: asyncio.Queue = asyncio.Queue()
    inner: asyncio.Queue = asyncio.Queue()
    ctx: dict = {}

    task = asyncio.create_task(_live_relay(src, inner, ctx))
    try:
        for i in range(PERCEPTION_BUFFER_LEN * 3):
            await src.put(
                {
                    "type": "perception_sample",
                    "rms_db": -60.0 + (i % 3),
                    "voice_likelihood": None,
                }
            )
        # Let the relay drain the queue before we assert the buffer length.
        for _ in range(5):
            if src.qsize() == 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)
        assert len(ctx["perception_buffer"]) == PERCEPTION_BUFFER_LEN
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
