"""Verify both LiveEngine implementations satisfy LiveEngineProtocol.

The protocol is ``@runtime_checkable`` so a plain ``isinstance`` is enough
to confirm every method on the protocol exists on each implementation.
"""
from __future__ import annotations

from queue import Queue

import pytest

from agent.live_engine import (
    LiveEngine,
    LiveEngineBrowser,
    LiveEngineLocal,
    LiveEngineProtocol,
)


def test_live_engine_local_satisfies_protocol():
    engine = LiveEngineLocal([], Queue())
    assert isinstance(engine, LiveEngineProtocol)


def test_live_engine_browser_satisfies_protocol():
    engine = LiveEngineBrowser()
    assert isinstance(engine, LiveEngineProtocol)


def test_live_engine_alias_points_at_local():
    """``LiveEngine`` is a backwards-compat alias for ``LiveEngineLocal`` so
    pre-v2.5.1 callers (and ``tests/test_live_engine.py``) keep working."""
    assert LiveEngine is LiveEngineLocal


@pytest.mark.parametrize(
    "method",
    [
        "play",
        "crossfade_now",
        "extend_track",
        "skip_track",
        "queue_swap",
        "set_crossfade_point",
        "get_state",
        "stop",
    ],
)
def test_browser_implements_every_protocol_method(method):
    """Catch any forgotten method even if Python's structural typing missed it."""
    assert callable(getattr(LiveEngineBrowser, method, None)), (
        f"LiveEngineBrowser is missing method '{method}'"
    )


@pytest.mark.parametrize(
    "method",
    [
        "play",
        "crossfade_now",
        "extend_track",
        "skip_track",
        "queue_swap",
        "set_crossfade_point",
        "get_state",
        "stop",
    ],
)
def test_local_implements_every_protocol_method(method):
    assert callable(getattr(LiveEngineLocal, method, None)), (
        f"LiveEngineLocal is missing method '{method}'"
    )
