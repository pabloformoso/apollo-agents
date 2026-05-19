"""Unit tests for the v2.5.1 ``LiveEngineBrowser`` implementation.

The browser engine doesn't touch sounddevice, librosa, or pyrubberband — it
only manages playlist state and emits engine events that the WS handler
forwards to the browser. These tests collect emitted events into a Python
list and inspect transitions explicitly.
"""
from __future__ import annotations

from agent.live_engine import (
    APPROACHING_CF,
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineBrowser,
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

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


# ---------------------------------------------------------------------------
# play()
# ---------------------------------------------------------------------------

def test_play_emits_track_started_for_first_track():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    started = [e for e in rec.events if e["type"] == TRACK_STARTED]
    assert len(started) == 1
    assert started[0]["track"]["id"] == "a"


def test_play_with_empty_playlist_emits_session_ended_only():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([])
    assert rec.types() == [SESSION_ENDED]


def test_play_emits_load_command_so_browser_starts_audio():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "load"
    ]
    assert cmds and cmds[0]["track"]["id"] == "a"


# ---------------------------------------------------------------------------
# report_playback_pos()
# ---------------------------------------------------------------------------

def test_report_playback_pos_triggers_approaching_crossfade_at_threshold():
    rec = _Recorder()
    # 30s warn window, 20s track. Crossfade point defaults to
    # duration - crossfade_sec - 5 = 20 - 12 - 5 = 3s. So at currentTime
    # 0.0 we're already inside the warn window for the first track.
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=20.0), _track("b", duration_sec=20.0)])
    rec.events.clear()
    engine.report_playback_pos("a", 0.0)
    assert APPROACHING_CF in rec.types()


def test_report_playback_pos_only_fires_warn_once_per_track():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
    engine.play(
        [_track("a", duration_sec=120.0), _track("b", duration_sec=120.0)]
    )
    rec.events.clear()
    # Crossfade point ~ 120 - 12 - 5 = 103s. Warn at <=30s remaining => 73s.
    engine.report_playback_pos("a", 80.0)
    engine.report_playback_pos("a", 81.0)
    engine.report_playback_pos("a", 82.0)
    warns = [e for e in rec.events if e["type"] == APPROACHING_CF]
    assert len(warns) == 1


def test_report_playback_pos_triggers_crossfade_past_threshold():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=5)
    engine.play(
        [_track("a", duration_sec=20.0), _track("b", duration_sec=20.0)]
    )
    rec.events.clear()
    engine.report_playback_pos("a", 19.0)  # well past cf point (3s)
    types = rec.types()
    assert CROSSFADE_TRIGGERED in types
    assert TRACK_STARTED in types  # next track started


def test_report_playback_pos_for_last_track_emits_track_ended_and_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec, crossfade_sec=2, approach_warn_sec=2)
    engine.play([_track("a", duration_sec=10.0)])
    rec.events.clear()
    engine.report_playback_pos("a", 11.0)  # past duration
    types = rec.types()
    assert TRACK_ENDED in types
    assert SESSION_ENDED in types


def test_report_playback_pos_ignores_stale_track_pings():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    engine.report_playback_pos("not-the-current-track", 1.0)
    assert rec.events == []


# ---------------------------------------------------------------------------
# skip_track()
# ---------------------------------------------------------------------------

def test_skip_track_advances_cursor_and_emits_events():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b")])
    rec.events.clear()
    msg = engine.skip_track()
    assert "Track b" in msg
    assert engine._idx == 1
    types = rec.types()
    assert TRACK_STARTED in types
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "skip"
    ]
    assert cmds


def test_skip_track_on_last_track_returns_message():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    msg = engine.skip_track()
    assert "No next track" in msg


# ---------------------------------------------------------------------------
# queue_swap()
# ---------------------------------------------------------------------------

def test_queue_swap_replaces_track_at_position():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a"), _track("b"), _track("c")])
    new_track = _track("z")
    msg = engine.queue_swap_with_track(3, new_track)
    assert "Queued" in msg
    assert engine.playlist[2]["id"] == "z"
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "queue_swap"
    ]
    assert cmds and cmds[-1]["track"]["id"] == "z"


def test_queue_swap_rejects_past_position():
    engine = LiveEngineBrowser()
    engine.play([_track("a"), _track("b")])
    msg = engine.queue_swap_with_track(1, _track("z"))
    assert "not a future slot" in msg


# ---------------------------------------------------------------------------
# extend_track()
# ---------------------------------------------------------------------------

def test_extend_track_pushes_crossfade_point_back():
    engine = LiveEngineBrowser(crossfade_sec=12, approach_warn_sec=30)
    engine.play([_track("a", duration_sec=60.0), _track("b")])
    state_before = engine.get_state()
    engine.extend_track(20)
    state_after = engine.get_state()
    assert state_after["seconds_to_crossfade"] >= state_before["seconds_to_crossfade"] + 19


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_emits_session_ended_when_playing():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([_track("a")])
    rec.events.clear()
    engine.stop()
    types = rec.types()
    assert SESSION_ENDED in types
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "stop"
    ]
    assert cmds


def test_stop_when_idle_does_not_re_emit_session_ended():
    rec = _Recorder()
    engine = LiveEngineBrowser(emitter=rec)
    engine.play([])
    rec.events.clear()  # discard the SESSION_ENDED that ``play([])`` emitted
    engine.stop()
    assert SESSION_ENDED not in rec.types()


# ---------------------------------------------------------------------------
# get_state()
# ---------------------------------------------------------------------------

def test_get_state_after_play():
    engine = LiveEngineBrowser()
    engine.play([_track("a"), _track("b")])
    s = engine.get_state()
    assert s["state"] == "playing"
    assert s["current_track"]["display_name"] == "Track a"
    assert s["next_track"]["display_name"] == "Track b"
    assert s["playlist_remaining"] == 1


# ===========================================================================
# v3.0 — phase-lock wiring on LiveEngineBrowser
# ===========================================================================
#
# These tests pin that the browser engine emits the phase-lock payload
# the frontend's WebAudio scheduler needs. Without this surface the
# /live tab would keep running its pre-v3.0 linear-fade crossfade while
# the offline render uses downbeat-locked equal-power curves — exactly
# the live-vs-offline drift that motivated this whole refactor.

from agent.phase_lock import LiveTransitionPlan  # noqa: E402


def _v2_track(
    track_id: str,
    *,
    duration_sec: float = 60.0,
    bpm: float = 128.0,
) -> dict:
    """Catalog track with a v2 beatgrid spanning the whole duration.

    128 BPM 4/4 → bar = 1.875 s. Use ``round`` consistently so the
    integer sample-index math in the engine matches the float
    seconds we compare against in tests.
    """
    bar_sec = (60.0 / bpm) * 4.0
    n_bars = int(duration_sec / bar_sec) + 1
    downbeats = [round(i * bar_sec, 3) for i in range(n_bars)]
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": bpm,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "hot_cues": [],
        "beatgrid": {
            "version": 2,
            "bpm": bpm,
            "first_beat_sec": 0.0,
            "downbeats_sec": downbeats,
            "beats_per_bar": 4,
            "source": "madmom",
        },
    }


class TestBrowserPhaseLockPayload:
    """The frontend reads the ``phase_lock`` field from three event types
    (TRACK_STARTED, APPROACHING_CF, engine_command:crossfade). Pin that
    each carries the right anchors at the right time."""

    def test_track_started_carries_phase_lock_when_v2_beatgrids_present(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        ts = [e for e in rec.events if e["type"] == TRACK_STARTED][0]
        pl = ts.get("phase_lock")
        assert pl, "phase_lock payload must be present on TRACK_STARTED"
        # 60-second track @ 128 BPM, 12 s xfade. Outgoing anchor target =
        # 60 - 12 = 48 s; the chosen anchor must be on a phrase boundary
        # near 48 and leave room for the xfade tail.
        assert pl["incoming_anchor_sec"] == 0.0
        assert pl["xfade_sec"] == 12.0
        assert pl["phrase_tier"] != "fallback"
        # The frontend reads ``edge_guard_samples`` to size its raised-cosine
        # guard — must match the offline/local-live constant.
        assert pl["edge_guard_samples"] == 64

    def test_track_started_phase_lock_empty_when_no_beatgrid(self):
        """A v1-only catalog should produce a payload that signals
        "fall back to legacy fade" — the frontend reads this as an
        empty truthiness check."""
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_track("a"), _track("b")])
        ts = [e for e in rec.events if e["type"] == TRACK_STARTED][0]
        # ``phase_lock`` field is present but its content is empty so
        # the frontend's ``if (payload?.xfade_sec) {...}`` branch fails
        # cleanly.
        assert ts.get("phase_lock") == {}

    def test_approaching_crossfade_carries_phase_lock(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(
            emitter=rec, crossfade_sec=12, approach_warn_sec=30,
        )
        engine.play([_v2_track("a"), _v2_track("b")])
        # Drive the playback position into the approaching window.
        engine.report_playback_pos("a", current_time=30.0)
        approached = [e for e in rec.events if e["type"] == APPROACHING_CF]
        assert approached, "approaching_crossfade should fire at 30 s in"
        assert approached[0].get("phase_lock"), (
            "APPROACHING_CF must carry phase_lock so the frontend can pre-position "
            "the incoming deck before the actual crossfade trigger."
        )

    def test_crossfade_engine_command_carries_outgoing_side_payload(self):
        """The 'crossfade' engine_command fires AT the trigger moment.
        Its phase_lock payload describes the OUTGOING side's anchors —
        captured BEFORE the cursor advances. After advance the cached
        plan will be for (to_track → next-after), so capturing before
        is the only way to ship correct anchors to the frontend."""
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b"), _v2_track("c")])
        # Fast-forward to the crossfade trigger.
        engine.report_playback_pos("a", current_time=49.0)
        cf_cmds = [
            e for e in rec.events
            if e.get("type") == "engine_command" and e.get("command") == "crossfade"
        ]
        assert cf_cmds, "engine_command crossfade must fire"
        pl = cf_cmds[0].get("phase_lock")
        assert pl, "crossfade command must carry the outgoing-side phase_lock"
        # Outgoing anchor came from the (a → b) plan, NOT the (b → c) one
        # that was rebuilt after the cursor advanced. We can't easily
        # distinguish the two by value (both use the same beatgrid in this
        # test), but the field must be present and non-empty.
        assert "xfade_sec" in pl

    def test_phase_lock_rebuilt_after_crossfade_for_new_pair(self):
        """After the (a → b) crossfade, the cached plan should be for
        (b → c). The TRACK_STARTED emitted for ``b`` is where the
        frontend would read this — its phase_lock must describe the
        new outgoing side."""
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b"), _v2_track("c")])
        engine.report_playback_pos("a", current_time=49.0)
        # TRACK_STARTED for ``b`` is the second one (the first was for ``a``).
        ts_events = [e for e in rec.events if e["type"] == TRACK_STARTED]
        assert len(ts_events) >= 2
        assert ts_events[1].get("phase_lock"), (
            "TRACK_STARTED for the new current track must carry the "
            "phase_lock for the NEXT transition, otherwise the frontend "
            "has no anchors for (b → c) when its approaching_crossfade fires."
        )

    def test_phase_lock_empty_when_last_track(self):
        """On the final track there is no next transition — the rebuild
        produces no plan and the payload is empty. The frontend uses
        this to suppress any pre-positioning."""
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        engine.report_playback_pos("a", current_time=49.0)
        ts_events = [e for e in rec.events if e["type"] == TRACK_STARTED]
        # Last track started — its phase_lock should be empty.
        assert ts_events[-1].get("phase_lock") == {}


class TestBrowserCfPointSecondsLadder:
    """Pin the priority ladder in ``_cf_point_seconds`` so a future
    change to the hot-cue logic can't silently shadow the phase-lock
    anchor."""

    def test_plan_wins_over_hot_cue_for_current_track(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        track_a = _v2_track("a")
        track_a["hot_cues"] = [{"type": "out", "position_sec": 55.0}]
        engine.play([track_a, _v2_track("b")])
        # The cached plan was built for (a → b). Its outgoing anchor
        # was selected near (60 - 12) = 48 s, NOT 55 (the hot cue).
        sec = engine._cf_point_seconds(track_a)
        assert sec != 55.0, "phase-lock plan must win over hot cue"
        assert 44.0 <= sec <= 52.0, (
            f"outgoing anchor {sec} must land near the 48 s target "
            f"and on a phrase boundary"
        )

    def test_legacy_path_used_for_track_not_matching_cached_plan(self):
        """``_cf_point_seconds`` is sometimes called speculatively for a
        track that's not the current one. The cached plan describes the
        CURRENT track's outgoing side, so any other input must take the
        legacy fallback ladder rather than reading stale anchor data."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        speculative = {
            "id": "speculative",
            "duration_sec": 100.0,
            "hot_cues": [{"type": "out", "position_sec": 90.0}],
        }
        # Should fall through the legacy hot-cue path (90.0), NOT use
        # the (a → b) plan's outgoing anchor.
        assert engine._cf_point_seconds(speculative) == 90.0

    def test_extend_sec_adds_on_top_of_plan_anchor(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        base = engine._cf_point_seconds(engine.playlist[0])
        engine._extend_sec = 4.0
        bumped = engine._cf_point_seconds(engine.playlist[0])
        assert bumped == base + 4.0


class TestBrowserPhaseLockPayloadShape:
    """Snapshot the payload shape so a serialiser change can't quietly
    rename a key the frontend depends on."""

    def test_payload_keys_match_frontend_contract(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        payload = engine._phase_lock_payload()
        assert set(payload.keys()) == {
            "outgoing_anchor_sec",
            "incoming_anchor_sec",
            "xfade_sec",
            "phrase_tier",
            "incoming_pickup_skipped",
            "edge_guard_samples",
            "sample_rate",
            # v3.1 — tempo-match rates for the browser playbackRate path.
            "incoming_rate",
            "outgoing_rate",
        }

    def test_payload_empty_dict_when_no_plan(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        # No play() yet → no plan → empty payload.
        assert engine._phase_lock_payload() == {}

    def test_payload_empty_dict_on_fallback_tier(self):
        """Fallback tier means the heuristics couldn't lock onto a
        phrase boundary. The frontend reads the empty dict as the signal
        to use its legacy linear-fade scheduling — same semantics as
        having no beatgrid at all."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_track("a"), _track("b")])  # no beatgrid → fallback
        assert engine._phase_lock_payload() == {}


class TestBrowserPhaseLockTempoMatching:
    """v3.1 — tempo-match playback rate.

    The browser path can't run pyrubberband, so it mimics CLI behaviour by
    setting ``HTMLMediaElement.playbackRate`` on the incoming deck before
    play. The backend pre-computes the rate so all three paths (offline /
    CLI / browser) make the same stretch decision."""

    def test_incoming_rate_is_one_when_bpms_match(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play(
            [_v2_track("a", bpm=128.0), _v2_track("b", bpm=128.0)]
        )
        payload = engine._phase_lock_payload()
        assert payload["incoming_rate"] == 1.0

    def test_incoming_rate_is_one_when_delta_within_threshold(self):
        """5-BPM delta is the threshold — exactly equal still counts as
        "no audible benefit from stretching" (mirrors CLI behaviour)."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play(
            [_v2_track("a", bpm=128.0), _v2_track("b", bpm=124.0)]
        )
        payload = engine._phase_lock_payload()
        assert payload["incoming_rate"] == 1.0

    def test_incoming_rate_scales_when_delta_exceeds_threshold(self):
        """120 BPM outgoing → 130 BPM incoming: incoming must be slowed
        to 120/130 ≈ 0.923 so the two tracks crossfade at the same BPM.
        Sign convention matches the CLI ``_time_stretch`` (and main's
        compute_transition_bpm "match outgoing" branch): ratio
        = outgoing / incoming."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play(
            [_v2_track("a", bpm=120.0), _v2_track("b", bpm=130.0)]
        )
        payload = engine._phase_lock_payload()
        assert payload["incoming_rate"] == round(120.0 / 130.0, 6)

    def test_incoming_rate_clamped_to_stretch_max(self):
        """A huge BPM jump (60 → 180) would otherwise produce a 0.333
        rate that's both unmusical and crashes browsers. Clamp keeps it
        at 1/1.5 ≈ 0.667 — same safety bound as CLI's _STRETCH_MIN."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play(
            [_v2_track("a", bpm=60.0), _v2_track("b", bpm=180.0)]
        )
        payload = engine._phase_lock_payload()
        from agent.phase_lock import STRETCH_RATIO_MIN
        assert payload["incoming_rate"] == round(STRETCH_RATIO_MIN, 6)

    def test_outgoing_rate_is_always_one_today(self):
        """Phase 1 ships with ``outgoing_rate == 1.0`` for both small and
        large BPM deltas. Meet-in-middle stretching on the outgoing deck
        is reserved for Phase 2 (alongside backend pre-stretching for
        large ratios where playbackRate quality degrades)."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play(
            [_v2_track("a", bpm=120.0), _v2_track("b", bpm=130.0)]
        )
        payload = engine._phase_lock_payload()
        assert payload["outgoing_rate"] == 1.0

    def test_incoming_rate_is_one_when_outgoing_bpm_missing(self):
        """Legacy catalog entries with no BPM must not crash or produce a
        runaway rate. The backend treats missing BPM as "skip the stretch"
        — frontend keeps playbackRate at 1.0."""
        engine = LiveEngineBrowser(crossfade_sec=12)
        track_a = _v2_track("a", bpm=120.0)
        track_a["bpm"] = 0  # simulate missing/invalid BPM in catalog
        engine.play([track_a, _v2_track("b", bpm=130.0)])
        payload = engine._phase_lock_payload()
        assert payload["incoming_rate"] == 1.0


class TestBrowserNoDeadlockOnReportPlaybackPos:
    """v3.0 regression: ``_cf_point_seconds`` is called from inside the
    ``with self._lock`` block at the head of ``report_playback_pos``.
    The first cut of ``_current_track_for_plan`` re-acquired
    ``self._lock`` (non-reentrant) and deadlocked every browser session
    that had a v2 beatgrid. The fix is documented in
    ``_current_track_for_plan`` — this test pins it so a future
    "rewrap with the lock for safety" PR cannot reintroduce the hang."""

    def test_report_playback_pos_returns_under_two_seconds(self):
        import time as _time

        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_v2_track("a"), _v2_track("b")])
        t0 = _time.monotonic()
        engine.report_playback_pos("a", current_time=30.0)
        elapsed = _time.monotonic() - t0
        assert elapsed < 2.0, (
            f"report_playback_pos took {elapsed:.2f}s — should be sub-ms. "
            f"A regression here likely means _current_track_for_plan is "
            f"re-acquiring self._lock from inside a with self._lock block."
        )
