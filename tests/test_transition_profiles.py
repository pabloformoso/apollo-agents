"""Unit tests for v3.7.0 genre transition profiles ("drift" mode).

Two layers under test:

1. ``agent.transition_styles`` — the pure ``TransitionProfile`` metadata,
   the ``profile_for_genre`` lookup, and ``serialise_choice`` support for
   the new ``TransitionStyle.DRIFT``.
2. ``LiveEngineBrowser`` — per-transition profile resolution. A transition
   runs in DRIFT mode when EITHER endpoint's ``genre_folder`` (falling back
   to ``genre``) maps to a ``dj_mix=False`` profile. Drift suppresses the
   whole phase-lock surface (anchors / rates / grid-warp / bass_swap) and
   emits a single ``transition_style: "drift"`` marker with an effective
   crossfade_sec of 24s. Non-drift transitions must stay byte-identical.

The engine tests deliberately give the aural fixtures a (hallucinated) v2
beatgrid so they prove the profile gates the DJ machinery OFF *before* the
planner's phrase-tier decision — not merely because the grid was missing.
"""
from __future__ import annotations

from agent.live_engine import (
    APPROACHING_CF,
    ENDLESS_APPEND_CAP,
    TRACK_STARTED,
    LiveEngineBrowser,
)
from agent.transition_styles import (
    GENRE_TRANSITION_PROFILES,
    TransitionStyle,
    TransitionStyleChoice,
    profile_for_genre,
    serialise_choice,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _v2_track(
    track_id: str,
    *,
    genre_folder: str,
    duration_sec: float = 60.0,
    bpm: float = 128.0,
    genre: str | None = None,
) -> dict:
    """Catalog track with a v2 beatgrid spanning the whole duration.

    Mirrors the browser-suite ``_v2_track`` but carries a genre so the
    profile layer has something to resolve. ``genre`` defaults to
    ``genre_folder`` (matches the real catalog, where the folder name is
    the coarse genre).
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
        "genre_folder": genre_folder,
        "genre": genre if genre is not None else genre_folder,
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


def _aural(track_id: str, **kwargs) -> dict:
    return _v2_track(track_id, genre_folder="aural", **kwargs)


def _lofi(track_id: str, **kwargs) -> dict:
    return _v2_track(track_id, genre_folder="lofi - ambient", **kwargs)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


def _crossfade_cmd(rec: _Recorder) -> dict | None:
    cmds = [
        e for e in rec.events
        if e.get("type") == "engine_command" and e.get("command") == "crossfade"
    ]
    return cmds[0] if cmds else None


# ===========================================================================
# 1. profile_for_genre lookup matrix
# ===========================================================================

class TestProfileLookup:
    def test_aural_is_not_dj_mixed(self):
        assert profile_for_genre("aural").dj_mix is False

    def test_aural_carries_24s_crossfade_override(self):
        assert profile_for_genre("aural").crossfade_sec == 24.0

    def test_lookup_is_case_insensitive(self):
        for spelling in ("AURAL", "Aural", "aUrAl"):
            prof = profile_for_genre(spelling)
            assert prof.dj_mix is False
            assert prof.crossfade_sec == 24.0

    def test_lookup_strips_surrounding_whitespace(self):
        assert profile_for_genre("  aural  ").dj_mix is False

    def test_unknown_genre_defaults_to_dj_mix(self):
        prof = profile_for_genre("techno")
        assert prof.dj_mix is True
        assert prof.crossfade_sec is None

    def test_none_genre_defaults_to_dj_mix(self):
        prof = profile_for_genre(None)
        assert prof.dj_mix is True
        assert prof.crossfade_sec is None

    def test_empty_string_defaults_to_dj_mix(self):
        assert profile_for_genre("").dj_mix is True

    def test_unknown_genres_share_the_default_singleton(self):
        # Identity, not just equality — the default is a module singleton
        # so repeated lookups don't allocate a fresh profile each time.
        assert profile_for_genre("techno") is profile_for_genre("deep house")
        assert profile_for_genre(None) is profile_for_genre("unknown")

    def test_registry_contains_aural(self):
        # Guards against a rename/typo in the frozen key.
        assert "aural" in GENRE_TRANSITION_PROFILES
        assert GENRE_TRANSITION_PROFILES["aural"].dj_mix is False


# ===========================================================================
# 2. serialise_choice — DRIFT support
# ===========================================================================

class TestSerialiseDrift:
    def test_drift_serialises_to_style_only(self):
        choice = TransitionStyleChoice(style=TransitionStyle.DRIFT)
        assert serialise_choice(choice) == {"transition_style": "drift"}

    def test_drift_never_carries_bass_swap(self):
        choice = TransitionStyleChoice(style=TransitionStyle.DRIFT)
        assert "bass_swap" not in serialise_choice(choice)

    def test_drift_enum_value_is_the_wire_string(self):
        assert TransitionStyle.DRIFT.value == "drift"


# ===========================================================================
# 3. LiveEngineBrowser — per-transition drift resolution
# ===========================================================================

class TestEngineDriftResolution:
    """The _drift_transition_profile helper is the gate everything hinges
    on: (is_drift, effective_crossfade_sec) for a (current, next) pair."""

    def test_both_aural_is_drift_at_24s(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        drift, cf = engine._drift_transition_profile(_aural("a"), _aural("b"))
        assert drift is True and cf == 24.0

    def test_aural_to_lofi_is_drift(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        drift, cf = engine._drift_transition_profile(_aural("a"), _lofi("b"))
        assert drift is True and cf == 24.0

    def test_lofi_to_aural_is_drift(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        drift, cf = engine._drift_transition_profile(_lofi("a"), _aural("b"))
        assert drift is True and cf == 24.0

    def test_lofi_to_lofi_is_not_drift(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        drift, cf = engine._drift_transition_profile(_lofi("a"), _lofi("b"))
        assert drift is False and cf == 12.0

    def test_falls_back_to_genre_when_no_genre_folder(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        cur = {"id": "a", "duration_sec": 60.0, "genre": "aural"}
        nxt = {"id": "b", "duration_sec": 60.0, "genre": "lofi - ambient"}
        drift, cf = engine._drift_transition_profile(cur, nxt)
        assert drift is True and cf == 24.0

    def test_missing_next_track_uses_current_only(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        drift, cf = engine._drift_transition_profile(_aural("a"), None)
        assert drift is True and cf == 24.0
        drift2, cf2 = engine._drift_transition_profile(_lofi("a"), None)
        assert drift2 is False and cf2 == 12.0


class TestEngineDriftPayload:
    """AC2 / AC3 — the wire payload for a drift transition."""

    def test_aural_to_aural_phase_lock_is_drift_marker_only(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        payload = engine._phase_lock_payload()
        # Drift suppresses ALL phase-lock detail — anchors must not drive
        # the transition — so the payload is the bare style marker.
        assert payload == {"transition_style": "drift"}

    def test_aural_to_aural_payload_has_no_bass_swap(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        assert "bass_swap" not in engine._phase_lock_payload()

    def test_aural_to_aural_payload_has_no_anchors_or_rates(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        payload = engine._phase_lock_payload()
        for suppressed in (
            "outgoing_anchor_sec",
            "incoming_anchor_sec",
            "xfade_sec",
            "incoming_rate",
            "outgoing_rate",
            "beat_rate_schedule",
        ):
            assert suppressed not in payload

    def test_mixed_aural_lofi_is_drift(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _lofi("b")])
        assert engine._phase_lock_payload() == {"transition_style": "drift"}

    def test_mixed_lofi_aural_is_drift(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_lofi("a"), _aural("b")])
        assert engine._phase_lock_payload() == {"transition_style": "drift"}

    def test_crossfade_command_carries_24s_for_drift(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        # cf_point for aural drift = 60 - 24 - 5 = 31s; report well past it.
        engine.report_playback_pos("a", current_time=50.0)
        cmd = _crossfade_cmd(rec)
        assert cmd is not None
        assert cmd["crossfade_sec"] == 24.0
        # And the outgoing-side phase_lock rides the drift marker.
        assert cmd["phase_lock"] == {"transition_style": "drift"}

    def test_cf_point_is_earlier_for_drift_than_default(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        drift_cf = engine._cf_point_seconds(engine.playlist[0])
        # Drift uses the legacy duration formula with 24s: 60 - 24 - 5 = 31.
        assert drift_cf == 31.0
        # A non-drift lofi pair on an identical 60s track cuts later
        # (either its phrase anchor near 48s or the 12s legacy point 43s).
        lofi_engine = LiveEngineBrowser(crossfade_sec=12)
        lofi_engine.play([_lofi("a"), _lofi("b")])
        lofi_cf = lofi_engine._cf_point_seconds(lofi_engine.playlist[0])
        assert drift_cf < lofi_cf

    def test_cf_point_drift_respects_extend_sec(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        base = engine._cf_point_seconds(engine.playlist[0])
        engine._extend_sec = 7.0
        assert engine._cf_point_seconds(engine.playlist[0]) == base + 7.0


class TestEngineNonDriftUnchanged:
    """AC3 — lofi→lofi is byte-identical to the pre-v3.7 behaviour."""

    def test_lofi_pair_keeps_full_phase_lock_payload(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_lofi("a"), _lofi("b")])
        payload = engine._phase_lock_payload()
        # Non-drift path still ships the rich anchor contract.
        assert payload["transition_style"] in {"smooth_blend", "bass_swap"}
        assert payload["xfade_sec"] == 12.0
        assert "incoming_rate" in payload
        assert "outgoing_rate" in payload

    def test_lofi_crossfade_command_keeps_int_default(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_lofi("a"), _lofi("b")])
        engine.report_playback_pos("a", current_time=59.0)
        cmd = _crossfade_cmd(rec)
        assert cmd is not None
        # Byte-identical: the int default, not a float override.
        assert cmd["crossfade_sec"] == 12
        assert isinstance(cmd["crossfade_sec"], int)

    def test_lofi_cf_point_uses_plan_or_legacy_not_24s(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_lofi("a"), _lofi("b")])
        cf = engine._cf_point_seconds(engine.playlist[0])
        # Must NOT be the drift 31.0 point — either the phrase anchor
        # (~48s) or the 12s legacy fallback (43s).
        assert cf != 31.0
        assert cf >= 43.0


class TestEngineEndlessWithAural:
    """AC-adjacent — endless append/extend paths are profile-agnostic."""

    def test_append_aural_track_still_works(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec)
        engine.play([_aural("a")])
        rec.events.clear()
        msg = engine.append_track(_aural("b"))
        assert "Appended" in msg
        assert [t["id"] for t in engine.playlist] == ["a", "b"]

    def test_append_aural_still_enforces_cap(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec)
        engine.play([_aural("a")])
        engine._endless_appended = ENDLESS_APPEND_CAP
        msg = engine.append_track(_aural("b"))
        assert "cap reached" in msg.lower()
        assert [t["id"] for t in engine.playlist] == ["a"]

    def test_extend_pushes_drift_crossfade_point_back(self):
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([_aural("a", duration_sec=120.0), _aural("b")])
        before = engine.get_state()["seconds_to_crossfade"]
        engine.extend_track(20)
        after = engine.get_state()["seconds_to_crossfade"]
        assert after >= before + 19

    def test_aural_transition_still_fires_approaching_crossfade(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12, approach_warn_sec=30)
        engine.play([_aural("a"), _aural("b")])
        # cf_point = 31s; warn window 30s → 1s in we are inside it.
        engine.report_playback_pos("a", current_time=2.0)
        assert APPROACHING_CF in rec.types()
        # The APPROACHING_CF event carries the drift marker too.
        approached = [e for e in rec.events if e["type"] == APPROACHING_CF][0]
        assert approached.get("phase_lock") == {"transition_style": "drift"}

    def test_track_started_for_aural_carries_drift_marker(self):
        rec = _Recorder()
        engine = LiveEngineBrowser(emitter=rec, crossfade_sec=12)
        engine.play([_aural("a"), _aural("b")])
        ts = [e for e in rec.events if e["type"] == TRACK_STARTED][0]
        assert ts.get("phase_lock") == {"transition_style": "drift"}
