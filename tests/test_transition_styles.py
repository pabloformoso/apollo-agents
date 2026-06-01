"""Tests for the v3.3 transition style decision layer.

Covers the deterministic ``pick_transition_style`` rules + the WS payload
serialisation contract the frontend deck depends on.
"""
from __future__ import annotations

import pytest

from agent.transition_styles import (
    BASS_SWAP_DROP_AT_FRACTION,
    BASS_SWAP_HPF_AFTER_HZ,
    BASS_SWAP_HPF_DURING_HZ,
    BassSwapParams,
    TransitionStyle,
    TransitionStyleChoice,
    pick_transition_style,
    serialise_choice,
)


# ---------------------------------------------------------------------------
# Fixture helpers — a "good" baseline that satisfies every BASS_SWAP gate.
# ---------------------------------------------------------------------------

def _good_inputs() -> dict:
    """Inputs that should produce BASS_SWAP. Tests mutate one field
    at a time to verify each gate independently."""
    # 122 BPM, 4/4 → 1 bar ≈ 1.967s. 16 bars from anchor = ~31.5s of
    # downbeats. Plenty of room for the drop at xfade/2 = 6s.
    bar = 60.0 / 122.0 * 4.0
    downbeats = [round(0.5 + i * bar, 3) for i in range(40)]
    return dict(
        outgoing_bpm=122.0,
        incoming_bpm=122.5,
        phrase_tier="16-bar",
        incoming_anchor_catalog_sec=downbeats[2],  # 3rd downbeat as anchor
        incoming_downbeats=downbeats,
        xfade_sec=12.0,
    )


# ---------------------------------------------------------------------------
# Picker — BASS_SWAP happy path
# ---------------------------------------------------------------------------

def test_picks_bass_swap_when_all_gates_pass():
    choice = pick_transition_style(**_good_inputs())
    assert choice.style is TransitionStyle.BASS_SWAP
    assert choice.bass_swap is not None
    assert choice.bass_swap.hpf_cutoff_during_hz == BASS_SWAP_HPF_DURING_HZ
    assert choice.bass_swap.hpf_cutoff_after_hz == BASS_SWAP_HPF_AFTER_HZ


def test_bass_swap_drop_lands_on_a_real_downbeat():
    """The drop time must equal one of the incoming downbeats, not a
    midpoint between them — otherwise the snap won't feel musical."""
    inputs = _good_inputs()
    choice = pick_transition_style(**inputs)
    assert choice.bass_swap is not None
    assert choice.bass_swap.drop_at_incoming_sec in inputs["incoming_downbeats"]


def test_bass_swap_drop_is_at_least_half_xfade_after_anchor():
    """The drop should land near xfade_sec * BASS_SWAP_DROP_AT_FRACTION
    past the anchor so the listener gets a real tension window before
    release."""
    inputs = _good_inputs()
    choice = pick_transition_style(**inputs)
    assert choice.bass_swap is not None
    offset = choice.bass_swap.drop_at_incoming_sec - inputs["incoming_anchor_catalog_sec"]
    expected_min = inputs["xfade_sec"] * BASS_SWAP_DROP_AT_FRACTION
    assert offset >= expected_min


# ---------------------------------------------------------------------------
# Picker — each gate that should force SMOOTH_BLEND
# ---------------------------------------------------------------------------

def test_falls_back_to_smooth_blend_when_outgoing_bpm_missing():
    inputs = _good_inputs() | {"outgoing_bpm": None}
    choice = pick_transition_style(**inputs)
    assert choice.style is TransitionStyle.SMOOTH_BLEND
    assert choice.bass_swap is None


def test_falls_back_to_smooth_blend_when_incoming_bpm_missing():
    inputs = _good_inputs() | {"incoming_bpm": None}
    choice = pick_transition_style(**inputs)
    assert choice.style is TransitionStyle.SMOOTH_BLEND


def test_falls_back_to_smooth_blend_when_bpm_delta_at_or_above_threshold():
    """Δbpm ≥ 2 means the incoming rate is doing meaningful work; piling
    HPF automation on top risks compounding artefacts."""
    inputs = _good_inputs() | {"incoming_bpm": 124.5}  # Δ = 2.5
    choice = pick_transition_style(**inputs)
    assert choice.style is TransitionStyle.SMOOTH_BLEND


def test_picks_bass_swap_when_bpm_delta_just_below_threshold():
    """Boundary: Δ = 1.9 should still pass, Δ = 2.0 should not."""
    just_under = _good_inputs() | {"incoming_bpm": 123.9}  # Δ = 1.9
    just_at = _good_inputs() | {"incoming_bpm": 124.0}  # Δ = 2.0
    assert pick_transition_style(**just_under).style is TransitionStyle.BASS_SWAP
    assert pick_transition_style(**just_at).style is TransitionStyle.SMOOTH_BLEND


@pytest.mark.parametrize("tier", ["8-bar", "4-bar", "fallback", "anywhere"])
def test_falls_back_to_smooth_blend_for_non_16_bar_phrase_tiers(tier: str):
    inputs = _good_inputs() | {"phrase_tier": tier}
    assert pick_transition_style(**inputs).style is TransitionStyle.SMOOTH_BLEND


def test_falls_back_to_smooth_blend_when_xfade_sec_is_zero():
    inputs = _good_inputs() | {"xfade_sec": 0.0}
    assert pick_transition_style(**inputs).style is TransitionStyle.SMOOTH_BLEND


def test_falls_back_to_smooth_blend_when_no_downbeat_far_enough():
    """If the incoming track's grid runs out before xfade/2 past the
    anchor, there's no musical target for the drop — degrade gracefully."""
    inputs = _good_inputs()
    # Truncate downbeats so the last one is just past the anchor —
    # nothing xfade/2 = 6s away.
    anchor = inputs["incoming_anchor_catalog_sec"]
    inputs["incoming_downbeats"] = [d for d in inputs["incoming_downbeats"] if d <= anchor + 1.0]
    assert pick_transition_style(**inputs).style is TransitionStyle.SMOOTH_BLEND


def test_falls_back_to_smooth_blend_when_incoming_downbeats_empty():
    inputs = _good_inputs() | {"incoming_downbeats": []}
    assert pick_transition_style(**inputs).style is TransitionStyle.SMOOTH_BLEND


# ---------------------------------------------------------------------------
# WS payload serialisation contract
# ---------------------------------------------------------------------------

def test_serialise_smooth_blend_omits_bass_swap_block():
    payload = serialise_choice(TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND))
    assert payload == {"transition_style": "smooth_blend"}
    assert "bass_swap" not in payload


def test_serialise_bass_swap_includes_all_three_keys():
    choice = TransitionStyleChoice(
        style=TransitionStyle.BASS_SWAP,
        bass_swap=BassSwapParams(
            hpf_cutoff_during_hz=120.0,
            hpf_cutoff_after_hz=20.0,
            drop_at_incoming_sec=12.345,
        ),
    )
    payload = serialise_choice(choice)
    assert payload["transition_style"] == "bass_swap"
    assert payload["bass_swap"] == {
        "hpf_cutoff_during_hz": 120.0,
        "hpf_cutoff_after_hz": 20.0,
        "drop_at_incoming_sec": 12.345,
    }


def test_serialise_bass_swap_rounds_drop_time_to_4_decimals():
    """Frontend uses this as an AudioContext target time — sub-millisecond
    precision is overkill and gives noisy WS payloads."""
    choice = TransitionStyleChoice(
        style=TransitionStyle.BASS_SWAP,
        bass_swap=BassSwapParams(
            hpf_cutoff_during_hz=120.0,
            hpf_cutoff_after_hz=20.0,
            drop_at_incoming_sec=12.345678901234,
        ),
    )
    payload = serialise_choice(choice)
    assert payload["bass_swap"]["drop_at_incoming_sec"] == 12.3457


def test_smooth_blend_with_stray_bass_swap_params_is_ignored():
    """Defensive: if a future caller builds a TransitionStyleChoice with
    style=SMOOTH_BLEND but accidentally also fills bass_swap, the wire
    format must NOT leak that — the frontend would misread the style."""
    choice = TransitionStyleChoice(
        style=TransitionStyle.SMOOTH_BLEND,
        bass_swap=BassSwapParams(
            hpf_cutoff_during_hz=120.0,
            hpf_cutoff_after_hz=20.0,
            drop_at_incoming_sec=5.0,
        ),
    )
    payload = serialise_choice(choice)
    assert "bass_swap" not in payload
