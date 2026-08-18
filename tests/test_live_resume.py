"""Tests for resuming a live set across a websocket reconnect.

``LiveEngineBrowser`` is constructed PER WEBSOCKET, so a browser reload
builds a fresh engine and calls ``play()`` again. Until v3.7 that always
started at track 0: observed live 2026-08-17 on the healing stream, where
a tab drop at track 10 took the set back to 'Silent Bloom' (the backend
logged ``[beatmatch] 9->10`` and then, after the reconnect, ``0->1``).

Two halves are covered here:
  - ``resolve_resume_index`` — which position a reconnect should ask for.
  - ``LiveEngineBrowser.play(start_idx=...)`` — that it honours it.
"""
from __future__ import annotations

import pytest

from agent.live_engine import (
    SESSION_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
    resolve_resume_index,
)


def _track(track_id: str, *, duration_sec: float = 60.0, bpm: float = 120.0) -> dict:
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "hot_cues": [],
    }


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def first_started_id(self) -> str | None:
        for e in self.events:
            if e.get("type") == TRACK_STARTED:
                return (e.get("track") or {}).get("id")
        return None


class TestResolveResumeIndex:

    def test_resolves_a_known_track_to_its_position(self):
        assert resolve_resume_index(["a", "b", "c"], "c") == 2

    def test_no_resume_id_starts_at_the_top(self):
        assert resolve_resume_index(["a", "b"], None) == 0

    def test_unknown_id_starts_at_the_top(self):
        """A brand-new playlist must not inherit the old set's position."""
        assert resolve_resume_index(["x", "y"], "a") == 0

    def test_empty_playlist_is_zero(self):
        assert resolve_resume_index([], "a") == 0

    def test_follows_the_track_across_a_reorder(self):
        """The point of keying on id: an index would resume on the wrong track."""
        assert resolve_resume_index(["c", "a", "b"], "b") == 2

    def test_removed_track_falls_back_to_the_top(self):
        assert resolve_resume_index(["a", "c"], "b") == 0

    @pytest.mark.parametrize("resume_id", ["", None])
    def test_falsy_resume_ids_are_zero(self, resume_id):
        assert resolve_resume_index(["a", "b"], resume_id) == 0


class TestPlayStartIdx:

    def _engine(self, n: int = 4):
        rec = _Recorder()
        eng = LiveEngineBrowser(emitter=rec)
        playlist = [_track(chr(ord("a") + i)) for i in range(n)]
        return eng, rec, playlist

    def test_defaults_to_the_first_track(self):
        eng, rec, playlist = self._engine()
        eng.play(playlist)
        assert rec.first_started_id() == "a"
        assert eng._idx == 0

    def test_resumes_at_the_requested_track(self):
        """The live regression: reconnect at track 3 must not replay track 1."""
        eng, rec, playlist = self._engine()
        eng.play(playlist, start_idx=2)
        assert rec.first_started_id() == "c"
        assert eng._idx == 2

    def test_loads_the_resumed_track_in_the_browser(self):
        """The cmd_load must name the resumed track, or audio and engine diverge."""
        eng, rec, playlist = self._engine()
        eng.play(playlist, start_idx=3)
        loads = [
            e for e in rec.events
            if e.get("type", "").startswith("cmd") or e.get("command") == "load"
        ]
        assert loads, f"no load command emitted; got {[e.get('type') for e in rec.events]}"
        assert any(
            (e.get("track") or {}).get("id") == "d" for e in loads
        ), loads

    def test_index_past_the_end_is_clamped(self):
        """A stored position can outlive an edit that shortened the playlist."""
        eng, rec, playlist = self._engine(n=3)
        eng.play(playlist, start_idx=99)
        assert eng._idx == 2
        assert rec.first_started_id() == "c"

    def test_negative_index_is_clamped(self):
        eng, rec, playlist = self._engine()
        eng.play(playlist, start_idx=-5)
        assert eng._idx == 0
        assert rec.first_started_id() == "a"

    def test_none_index_is_treated_as_zero(self):
        eng, rec, playlist = self._engine()
        eng.play(playlist, start_idx=None)
        assert eng._idx == 0

    def test_empty_playlist_still_ends_the_session(self):
        rec = _Recorder()
        eng = LiveEngineBrowser(emitter=rec)
        eng.play([], start_idx=2)
        assert SESSION_ENDED in [e.get("type") for e in rec.events]

    def test_resumed_set_still_advances_from_there(self):
        """Resuming must not strand the engine: the next track is start_idx+1."""
        eng, rec, playlist = self._engine()
        eng.play(playlist, start_idx=1)
        assert eng._idx == 1
        assert eng.playlist[eng._idx + 1]["id"] == "c"
