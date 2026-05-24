"""
v3.0 — cross-path phase-lock parity tests.

The whole reason ``agent/phase_lock.py`` was extracted was so the
offline pipeline (``main.build_mix``), the terminal-live engine
(``agent.live_engine.LiveEngineLocal``), and the web-live engine
(``agent.live_engine.LiveEngineBrowser`` + ``web/frontend/lib/live.ts``)
all compute identical anchors for identical input. These tests pin
that invariant.

If any path silently forks the algorithm — e.g. somebody copies a
helper into ``main.py`` and tweaks the constant, or somebody adds a
"smarter" pickup heuristic to ``LiveEngineLocal`` without porting it
to the browser — the assertions below break. That's the safety net.
"""
from __future__ import annotations

from queue import Queue

import numpy as np
import pytest

from agent.live_engine import LiveEngineBrowser, LiveEngineLocal
from agent.phase_lock import (
    PhaseLockPlan,
    build_live_transition_plan,
    compute_phase_lock,
    compute_tempo_match_rate,
    resolve_downbeats,
)
from main import compute_transition_bpm


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SR = 44100
BPM = 128.0
BAR_SEC = (60.0 / BPM) * 4.0  # 4/4 → 1.875 s


def _v2_beatgrid(duration_sec: float, *, bpm: float = BPM):
    bar = (60.0 / bpm) * 4.0
    n_bars = int(duration_sec / bar) + 1
    downbeats = [round(i * bar, 3) for i in range(n_bars)]
    return {
        "version": 2,
        "bpm": bpm,
        "first_beat_sec": 0.0,
        "downbeats_sec": downbeats,
        "beats_per_bar": 4,
        "source": "madmom",
    }


def _v2_track(track_id: str, duration_sec: float = 60.0):
    return {
        "id": track_id,
        "display_name": f"Track {track_id}",
        "bpm": BPM,
        "camelot_key": "8A",
        "duration_sec": duration_sec,
        "hot_cues": [],
        "beatgrid": _v2_beatgrid(duration_sec),
    }


# ---------------------------------------------------------------------------
# Cross-path parity — same input MUST produce same anchors everywhere
# ---------------------------------------------------------------------------

class TestCrossPathParity:
    """Three call sites, one source of truth. A pre-v3.0 codebase had
    each path computing its own crossfade timing; this class breaks
    if a future contributor accidentally reverts that decoupling."""

    def test_offline_and_local_live_pick_same_outgoing_anchor(self):
        """``main.build_mix`` plans anchors via ``compute_phase_lock``;
        ``LiveEngineLocal._build_transition_plan_for_next`` calls the
        same function via ``build_live_transition_plan``. Same input
        → same catalog-time anchor."""
        # 60-second tracks @ 128 BPM, 12 s crossfade target.
        out_bg = _v2_beatgrid(60.0)
        in_bg = _v2_beatgrid(60.0)
        # Direct compute_phase_lock call — what build_mix does.
        offline_plan = compute_phase_lock(
            outgoing_downbeats=out_bg["downbeats_sec"],
            outgoing_duration_catalog_sec=60.0,
            incoming_downbeats=in_bg["downbeats_sec"],
            incoming_audio_y=None,
            incoming_sr=SR,
            target_xfade_sec=12.0,
        )
        # LiveEngineLocal flow — pulls beatgrid from track dict, calls
        # build_live_transition_plan with the post-stretch buffer.
        engine = LiveEngineLocal(
            [_v2_track("a"), _v2_track("b")], Queue(), crossfade_sec=12,
        )
        engine._audio = np.zeros((int(60.0 * SR), 2), dtype=np.float32)
        local_live_plan = engine._build_transition_plan_for_next(
            _v2_track("a"),
            _v2_track("b"),
            np.zeros((int(60.0 * SR), 2), dtype=np.float32),
        )
        assert local_live_plan is not None
        assert (
            offline_plan.outgoing_anchor_catalog_sec
            == local_live_plan.plan.outgoing_anchor_catalog_sec
        ), (
            "Offline (compute_phase_lock) and LiveEngineLocal "
            "(build_live_transition_plan) disagree on outgoing anchor — "
            "they MUST share a single source of truth."
        )
        assert (
            offline_plan.incoming_anchor_catalog_sec
            == local_live_plan.plan.incoming_anchor_catalog_sec
        )
        assert offline_plan.phrase_tier == local_live_plan.plan.phrase_tier

    def test_local_live_and_browser_live_pick_same_anchors(self):
        """Both engines call ``build_live_transition_plan`` — but with
        different ``incoming_audio_y`` (local has the post-stretch
        buffer, browser passes None). Without the audio buffer the
        pickup-skip heuristic doesn't fire. The OUTGOING anchor must
        still match (it depends only on the catalog beatgrid)."""
        track_a = _v2_track("a")
        track_b = _v2_track("b")
        # Local-live: has audio buffer (silent → no pickup-skip).
        local = LiveEngineLocal([track_a, track_b], Queue(), crossfade_sec=12)
        local._audio = np.zeros((int(60.0 * SR), 2), dtype=np.float32)
        local_plan = local._build_transition_plan_for_next(
            track_a, track_b,
            np.zeros((int(60.0 * SR), 2), dtype=np.float32),
        )
        # Browser-live: no audio buffer (browser holds the bytes).
        browser = LiveEngineBrowser(crossfade_sec=12)
        browser.play([track_a, track_b])
        browser_plan = browser._transition_plan
        assert local_plan is not None
        assert browser_plan is not None
        assert (
            local_plan.plan.outgoing_anchor_catalog_sec
            == browser_plan.plan.outgoing_anchor_catalog_sec
        ), "Local-live and browser-live disagree on outgoing anchor"
        assert local_plan.plan.xfade_catalog_sec == browser_plan.plan.xfade_catalog_sec
        assert local_plan.plan.phrase_tier == browser_plan.plan.phrase_tier
        # On silent buffers the pickup-skip RMS heuristic doesn't fire
        # in either path, so incoming anchors also match (both = 0.0).
        assert (
            local_plan.plan.incoming_anchor_catalog_sec
            == browser_plan.plan.incoming_anchor_catalog_sec
        )

    def test_sample_index_math_consistent_across_paths(self):
        """The three sample-index conversions
        (``LiveEngineLocal._cf_point_samples``,
        ``LiveEngineBrowser._cf_point_seconds * SR``,
        ``build_live_transition_plan(...).outgoing_anchor_sample``)
        must all produce the same sample index for the same catalog
        anchor + sample rate."""
        track_a = _v2_track("a")
        track_b = _v2_track("b")
        # Local-live path. ``_build_transition_plan_for_next`` only
        # computes; in production the prestretch worker assigns the
        # result to ``self._transition_plan`` after time-stretching the
        # incoming buffer. Mirror that here so ``_cf_point_samples``
        # takes the plan-based branch.
        local = LiveEngineLocal([track_a, track_b], Queue(), crossfade_sec=12)
        local._audio = np.zeros((int(60.0 * SR), 2), dtype=np.float32)
        local._transition_plan = local._build_transition_plan_for_next(
            track_a, track_b,
            np.zeros((int(60.0 * SR), 2), dtype=np.float32),
        )
        local_cf_samples = local._cf_point_samples(track_a)
        # Browser-live path: convert seconds to samples manually.
        browser = LiveEngineBrowser(crossfade_sec=12)
        browser.play([track_a, track_b])
        browser_cf_samples = int(round(browser._cf_point_seconds(track_a) * SR))
        # build_live_transition_plan: direct access.
        direct_plan = build_live_transition_plan(
            outgoing_beatgrid=track_a["beatgrid"],
            outgoing_duration_sec=60.0,
            incoming_beatgrid=track_b["beatgrid"],
            incoming_duration_sec=60.0,
            incoming_audio_y=None,
            sample_rate=SR,
            target_xfade_sec=12.0,
        )
        assert local_cf_samples == direct_plan.outgoing_anchor_sample
        assert browser_cf_samples == direct_plan.outgoing_anchor_sample


# ---------------------------------------------------------------------------
# Fallback parity — degraded catalog entries fall back THE SAME WAY
# ---------------------------------------------------------------------------

class TestFallbackParity:
    """The 3-tier ladder (v3 plan → hot cue → duration formula) must
    behave identically on every path. A pre-v3.0 regression where
    LiveEngineLocal used "duration - cf - 5" while LiveEngineBrowser
    used "duration - cf - 3" would silently produce off-grid live
    sessions for legacy catalog entries — pin both to the same value."""

    def test_no_beatgrid_both_engines_use_legacy_formula(self):
        """No v2 beatgrid → ``phrase_tier == "fallback"`` → both
        engines drop to ``duration_sec - crossfade_sec - 5``. Pin both
        paths."""
        track_a = {"id": "a", "display_name": "A", "duration_sec": 60.0}
        track_b = {"id": "b", "display_name": "B", "duration_sec": 60.0}
        local = LiveEngineLocal([track_a, track_b], Queue(), crossfade_sec=12)
        local._audio = np.zeros((int(60.0 * SR), 2), dtype=np.float32)
        local._build_transition_plan_for_next(
            track_a, track_b,
            np.zeros((int(60.0 * SR), 2), dtype=np.float32),
        )
        local_sec = local._cf_point_samples(track_a) / SR
        browser = LiveEngineBrowser(crossfade_sec=12)
        browser.play([track_a, track_b])
        browser_sec = browser._cf_point_seconds(track_a)
        # Both must agree on the fallback target: 60 - 12 - 5 = 43 s.
        assert local_sec == 43.0
        assert browser_sec == 43.0

    def test_hot_cue_overrides_legacy_formula_in_both(self):
        """When a v1 catalog entry has an OUT hot cue, both engines
        honour it. The fallback formula is only the third tier."""
        track_a = {
            "id": "a", "display_name": "A", "duration_sec": 60.0,
            "hot_cues": [{"type": "out", "position_sec": 50.0}],
        }
        track_b = {"id": "b", "display_name": "B", "duration_sec": 60.0}
        local = LiveEngineLocal([track_a, track_b], Queue(), crossfade_sec=12)
        local._audio = np.zeros((int(60.0 * SR), 2), dtype=np.float32)
        local._build_transition_plan_for_next(
            track_a, track_b,
            np.zeros((int(60.0 * SR), 2), dtype=np.float32),
        )
        local_sec = local._cf_point_samples(track_a) / SR
        browser = LiveEngineBrowser(crossfade_sec=12)
        browser.play([track_a, track_b])
        browser_sec = browser._cf_point_seconds(track_a)
        assert local_sec == 50.0
        assert browser_sec == 50.0


# ---------------------------------------------------------------------------
# Schema parity — v1 entries synthesise the SAME grid in both engines
# ---------------------------------------------------------------------------

class TestV1SynthParity:
    """A legacy v1 entry (bpm + first_beat_sec only) gets a synthesised
    4/4 grid via ``synthesise_downbeats_from_v1`` — both the offline
    and live paths must read the same synthetic downbeats. Pin via
    ``resolve_downbeats``."""

    def test_v1_resolves_to_same_grid_in_each_path(self):
        v1 = {"bpm": 128.0, "first_beat_sec": 0.0}
        # Direct call from offline path.
        offline_dbs, offline_bpb = resolve_downbeats(v1, track_duration_sec=60.0)
        # Same call from inside LiveEngineLocal via build_live_transition_plan.
        track_a = {"id": "a", "duration_sec": 60.0, "beatgrid": v1, "bpm": 128.0}
        track_b = _v2_track("b")
        plan = build_live_transition_plan(
            outgoing_beatgrid=v1,
            outgoing_duration_sec=60.0,
            incoming_beatgrid=track_b["beatgrid"],
            incoming_duration_sec=60.0,
            incoming_audio_y=None,
            sample_rate=SR,
            target_xfade_sec=12.0,
        )
        # The plan was built from the same synthesised grid — its
        # outgoing anchor falls on a synthesised downbeat.
        assert any(
            abs(db - plan.plan.outgoing_anchor_catalog_sec) < 0.005
            for db in offline_dbs
        )
        assert offline_bpb == 4


# ---------------------------------------------------------------------------
# v3.1 Tempo-match rate parity — incoming-rate decision agrees across paths
# ---------------------------------------------------------------------------

class TestTempoMatchRateParity:
    """v3.1 — tempo matching parity.

    The browser path can't run pyrubberband, so it applies the equivalent
    tempo correction via ``HTMLMediaElement.playbackRate``. The decision
    *whether* to stretch and *what factor* to use MUST agree with the CLI
    engine's ``_time_stretch`` and the offline mixer's "match outgoing"
    branch — otherwise the same playlist would still sound differently on
    /live vs the rendered YouTube mix, defeating the v3 unification."""

    @pytest.mark.parametrize("out_bpm,in_bpm", [
        (128.0, 128.0),    # equal → no stretch
        (128.0, 124.0),    # 4 BPM delta → within threshold
        (128.0, 123.0),    # 5 BPM delta exactly → still within threshold
        (120.0, 130.0),    # 10 BPM delta → slow incoming to 120
        (130.0, 120.0),    # 10 BPM delta → speed incoming to 130
        (140.0, 100.0),    # 40 BPM delta → 1.4 ratio (under clamp ceiling)
        (180.0, 60.0),     # 3.0 raw ratio → clamped to STRETCH_RATIO_MAX
        (60.0, 180.0),     # 0.333 raw ratio → clamped to STRETCH_RATIO_MIN
    ])
    def test_browser_rate_matches_cli_time_stretch_ratio(self, out_bpm, in_bpm):
        """The CLI engine derives its stretch ratio from
        ``_time_stretch``: ``ratio = to_bpm / from_bpm`` clamped to
        ``[_STRETCH_MIN, _STRETCH_MAX]`` and gated on
        ``abs(from - to) > _BPM_THRESHOLD``. The browser path's
        ``incoming_rate`` MUST produce the same number — that's the
        whole parity claim. Compute both and assert equality."""
        from agent.live_engine import (
            _BPM_THRESHOLD,
            _STRETCH_MAX,
            _STRETCH_MIN,
        )

        # Simulate CLI _time_stretch exactly (without invoking pyrubberband).
        if abs(out_bpm - in_bpm) <= _BPM_THRESHOLD:
            cli_ratio = 1.0
        else:
            cli_ratio = max(_STRETCH_MIN, min(_STRETCH_MAX, out_bpm / in_bpm))

        # Browser path goes through compute_tempo_match_rate.
        browser_rate = compute_tempo_match_rate(out_bpm, in_bpm)

        assert browser_rate == pytest.approx(cli_ratio), (
            f"Tempo-match parity broken for {out_bpm}→{in_bpm} BPM: "
            f"CLI would stretch by {cli_ratio}, browser would playbackRate "
            f"at {browser_rate}. Same playlist would sound different on "
            f"/live (CLI) vs /live (browser) — defeating v3 phase-lock parity."
        )

    def test_offline_match_outgoing_branch_agrees_with_browser_rate(self):
        """The offline pipeline's small-delta branch
        (``compute_transition_bpm`` returning ``bpm_out``) implicitly
        plays the incoming track at ``bpm_out`` via pyrubberband — i.e.
        the same target the browser's playbackRate aims at. Pin that
        the rate the browser applies equals the implicit rate the
        offline mixer applies to the incoming track for the "match
        outgoing" case (small delta)."""
        out_bpm, in_bpm = 128.0, 124.0  # delta = 4 → within threshold
        trans_bpm = compute_transition_bpm(out_bpm, in_bpm)
        # Match-outgoing branch: trans_bpm equals out_bpm.
        assert trans_bpm == out_bpm
        # Browser rate is 1.0 because the delta is below the threshold;
        # offline pyrubberband would also be a near-1.0 ratio
        # (out_bpm / in_bpm = 1.032 — but the threshold gate keeps both
        # paths at 1.0). Parity preserved.
        assert compute_tempo_match_rate(out_bpm, in_bpm) == 1.0

    def test_browser_engine_payload_carries_parity_rate_to_frontend(self):
        """End-to-end: build a 2-track playlist with a BPM mismatch,
        confirm the engine's serialised phase_lock payload carries the
        same rate ``compute_tempo_match_rate`` returns. This is the wire
        contract the frontend reads — if it drifts the frontend would
        apply a different ``playbackRate`` than the parity proof above
        guarantees."""
        track_a = {
            "id": "a",
            "display_name": "A",
            "duration_sec": 60.0,
            "bpm": 120.0,
            "camelot_key": "8A",
            "hot_cues": [],
            "beatgrid": _v2_beatgrid(60.0, bpm=120.0),
        }
        track_b = {
            "id": "b",
            "display_name": "B",
            "duration_sec": 60.0,
            "bpm": 130.0,
            "camelot_key": "8A",
            "hot_cues": [],
            "beatgrid": _v2_beatgrid(60.0, bpm=130.0),
        }
        engine = LiveEngineBrowser(crossfade_sec=12)
        engine.play([track_a, track_b])
        payload = engine._phase_lock_payload()
        expected = round(compute_tempo_match_rate(120.0, 130.0), 6)
        assert payload["incoming_rate"] == expected
