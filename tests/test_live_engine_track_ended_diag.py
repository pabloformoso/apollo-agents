"""v3.9.3 — every ``track_ended`` leaves a line saying where the deck was.

The WS handler used to hand ``track_ended`` straight to the engine without
logging anything (``web/backend/app.py``). That mattered because the
frontend sends the *same* message from two very different situations:

  * the browser's ``<audio>`` fired ``ended`` — the track finished;
  * a decode failed and ``reportLoadFailure`` skipped the track
    (``web/frontend/lib/live.ts``) — an audible mid-set jump.

With no log line the two were indistinguishable, so "it jumped mid-song"
could not be confirmed or refuted from ``docker logs apollo-backend``
after the fact (2026-08-23). The derived signals don't help either:
``[beatmatch]`` is emitted at plan time, which lags whenever the endless
queue runs dry, and the ``[live_dj]`` turn lines are gated by LLM
latency — both drift by a minute or more.

``_log_track_ended_diag`` closes that gap: the reported position at the
moment the engine was told the track was over, plus a ``src=`` label
saying who said so. Only ``src=client`` can be a browser-side skip.
"""
from __future__ import annotations

import time

import pytest

from agent import live_engine
from agent.live_engine import (
    LIVE_TRACK_END_MARGIN_SEC,
    LiveEngineBrowser,
    LiveEngineLocal,
)

DURATION = 240.0


def _track(track_id: str, *, duration_sec: float = DURATION) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": 120.0,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "genre_folder": "lofi - ambient",
        "genre": "lofi - ambient",
        "hot_cues": [],
    }


def _engine(*tracks: dict, crossfade_sec: int = 12) -> LiveEngineBrowser:
    engine = LiveEngineBrowser(emitter=lambda _ev: None, crossfade_sec=crossfade_sec)
    engine.play(list(tracks))
    return engine


def _at(engine: LiveEngineBrowser, pos: float) -> None:
    """Park the reported position without walking the ping state machine.

    Same spirit as the stall suite poking ``_track_started_mono``: the
    thresholds under test are about the position the engine *holds*, not
    about how it got there.
    """
    engine._reported_pos_sec = pos


def _diag(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [
        ln
        for ln in capsys.readouterr().out.splitlines()
        if ln.startswith("[engine track_ended]")
    ]


# ── the margin itself ──────────────────────────────────────────────────


def test_default_margin_is_sane():
    # Wide enough to absorb the 250 ms ping cadence and a rounding-off
    # ``duration_sec``, far too narrow to swallow a real skip.
    assert 1 <= LIVE_TRACK_END_MARGIN_SEC <= 30


# ── the case this exists for: a browser-side skip ──────────────────────


def test_load_failure_skip_at_zero_is_flagged_premature(capsys):
    """``reportLoadFailure`` fires before the deck ever played."""
    engine = _engine(_track("a"), _track("b"))
    _at(engine, 0.0)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "src=client" in line
    assert "PREMATURE" in line
    assert "240.0s short" in line
    assert "at 0.0s of 240.0s (0%)" in line


def test_mid_track_end_is_flagged_premature(capsys):
    engine = _engine(_track("a"), _track("b"))
    _at(engine, 120.0)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "PREMATURE, 120.0s short" in line
    assert "(50%)" in line


def test_natural_end_is_not_flagged(capsys):
    engine = _engine(_track("a"), _track("b"))
    _at(engine, DURATION)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "natural end" in line
    assert "PREMATURE" not in line
    assert "at 240.0s of 240.0s (100%)" in line


# ── boundary ───────────────────────────────────────────────────────────


def test_exactly_at_the_margin_counts_as_natural(capsys):
    engine = _engine(_track("a"), _track("b"))
    _at(engine, DURATION - LIVE_TRACK_END_MARGIN_SEC)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "natural end" in line


def test_just_past_the_margin_is_premature(capsys):
    engine = _engine(_track("a"), _track("b"))
    _at(engine, DURATION - LIVE_TRACK_END_MARGIN_SEC - 0.1)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "PREMATURE" in line


def test_margin_is_read_off_the_module_so_it_can_be_tuned(monkeypatch, capsys):
    # Module attribute lookup (not a from-import) — same contract the WS
    # handler relies on for the stall cadence.
    monkeypatch.setattr(live_engine, "LIVE_TRACK_END_MARGIN_SEC", 200)
    engine = _engine(_track("a"), _track("b"))
    _at(engine, 100.0)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "natural end" in line


# ── edge cases that must not cry wolf ──────────────────────────────────


def test_zero_duration_reports_unknown_rather_than_premature(capsys):
    """A malformed catalog row must not manufacture a skip report."""
    engine = _engine(_track("a", duration_sec=0.0), _track("b"))
    _at(engine, 0.0)

    engine.report_track_ended("a")

    (line,) = _diag(capsys)
    assert "duration unknown" in line
    assert "PREMATURE" not in line


def test_stale_track_id_logs_nothing(capsys):
    """The ping is ignored, so there is no advance to explain."""
    engine = _engine(_track("a"), _track("b"))
    _at(engine, 0.0)

    engine.report_track_ended("someone-elses-track")

    assert _diag(capsys) == []


def test_idle_engine_logs_nothing(capsys):
    engine = LiveEngineBrowser(emitter=lambda _ev: None)

    engine.report_track_ended("a")

    assert _diag(capsys) == []


def test_missing_track_id_is_accepted_and_logged(capsys):
    """The browser fallback path may not know the id — still diagnose it."""
    engine = _engine(_track("a"), _track("b"))
    _at(engine, 12.0)

    engine.report_track_ended("")

    (line,) = _diag(capsys)
    assert "src=client" in line
    assert "PREMATURE" in line


# ── attribution: only a real browser message may read src=client ───────


def test_endgame_safeguard_labels_itself_not_the_client(capsys):
    """The last-2-seconds safeguard in ``report_playback_pos``.

    ``extend_track`` pushes the crossfade point past the end of the
    media, so no crossfade can fire and the browser's natural end wins
    the race — exactly the situation the safeguard exists for.
    """
    engine = _engine(_track("a"), _track("b"))
    engine.extend_track(60)

    engine.report_playback_pos("a", DURATION - 1.0)

    (line,) = _diag(capsys)
    assert "src=endgame" in line
    assert "src=client" not in line


def test_stall_watchdog_labels_itself_not_the_client(monkeypatch, capsys):
    """The watchdog's last-track path routes through report_track_ended."""
    monkeypatch.setattr(live_engine, "_load_catalog", lambda: [])
    engine = _engine(_track("a", duration_sec=60.0))
    engine.report_playback_pos("a", 5.0)
    # Freeze the deck well past the margin so check_stall arms.
    engine._last_pos_change_mono = time.monotonic() - (
        live_engine.LIVE_STALL_MARGIN_SEC + 5
    )

    assert engine.check_stall() == "a"

    (line,) = _diag(capsys)
    assert "src=stall" in line
    assert "src=client" not in line


# ── protocol compatibility ─────────────────────────────────────────────


def test_local_engine_still_satisfies_the_widened_protocol():
    """The WS handler calls this without an isinstance check."""
    engine = LiveEngineLocal(playlist=[], event_queue=None)

    assert engine.report_track_ended("a", source="client") is None
    assert engine.report_track_ended("a") is None
