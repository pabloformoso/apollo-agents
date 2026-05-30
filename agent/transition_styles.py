"""Transition style decision layer for the Apollo live engine.

The engine's phase-lock plumbing decides *when* and *where* to cut and
overlap two tracks (downbeat-accurate, equal-power, tempo-matched). This
module decides *how* the crossfade SOUNDS — picking from a small set of
named "moves" with concrete DSP automation curves the browser can execute
on Web Audio nodes.

v3.3 — first cut, only two styles:

- ``SMOOTH_BLEND``: the legacy equal-power overlay-add. No EQ touch on
  either deck. Returned by default and whenever bass_swap's preconditions
  don't hold.
- ``BASS_SWAP``: classic DJ move — high-pass the incoming track from the
  start of the crossfade so its sub-bass / bassline doesn't clash with
  the outgoing's groove, then snap the filter open on a phrase boundary
  inside the crossfade window ("the drop"). Tension → release pattern
  that feels musical on 4/4 dance material.

The picker is deterministic and conservative on purpose: BASS_SWAP only
fires when BPMs are close (no tempo-warp artefacts piling on top of EQ
automation) AND a 16-bar phrase boundary is present (so the drop lands
on a structurally significant downbeat, not a stray one). Future
revisions can layer softmax + temperature on top of this floor.

The choice is serialised onto the existing phase-lock WS payload — the
browser deck reads ``transition_style`` and, when ``bass_swap``, applies
the HPF cutoff schedule with ``BiquadFilterNode.frequency.setValueAtTime``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence


class TransitionStyle(str, Enum):
    """Named crossfade moves. String-valued so JSON serialisation is trivial."""

    SMOOTH_BLEND = "smooth_blend"
    BASS_SWAP = "bass_swap"


# --- Bass-swap defaults ----------------------------------------------------
# Cutoff during the bass-cut portion of the xfade. 120 Hz keeps the kick's
# body audible (the "thump" sits around 60-90 Hz but the body extends up
# to ~150 Hz) while killing the bassline groove that would clash with the
# outgoing's sub-bass. Higher cutoffs (200+ Hz) sound musically "filtered"
# but in 4/4 dance kill the kick — wrong feel for a clean bass-swap.
BASS_SWAP_HPF_DURING_HZ: float = 120.0

# Cutoff after the drop. 20 Hz is below the audible spectrum / below
# typical playback systems' rolloff, so it's effectively "filter off".
BASS_SWAP_HPF_AFTER_HZ: float = 20.0

# How deep into the crossfade the drop should land, as a fraction of
# xfade_sec. 0.5 = halfway — listener gets ~half the crossfade with the
# tension of a filtered incoming, then the drop releases on a phrase
# boundary roughly at the midpoint. Tunable, not magic.
BASS_SWAP_DROP_AT_FRACTION: float = 0.5


@dataclass(frozen=True)
class BassSwapParams:
    """Automation envelope the frontend applies to the incoming deck's HPF.

    All times are in the INCOMING track's CATALOG seconds (the same
    reference frame as ``incoming_anchor_catalog_sec`` in
    :class:`PhaseLockPlan`). The frontend converts them to AudioContext
    time using the deck's current playhead.
    """

    hpf_cutoff_during_hz: float
    hpf_cutoff_after_hz: float
    drop_at_incoming_sec: float


@dataclass(frozen=True)
class TransitionStyleChoice:
    """What the picker returned + the parameters the executor will need.

    ``bass_swap`` is populated iff ``style is TransitionStyle.BASS_SWAP``;
    SMOOTH_BLEND carries no parameters because the engine's default
    crossfade path doesn't need any.
    """

    style: TransitionStyle
    bass_swap: Optional[BassSwapParams] = None


def _find_drop_downbeat(
    incoming_downbeats: Sequence[float],
    incoming_anchor_sec: float,
    target_offset_sec: float,
) -> Optional[float]:
    """Return the first incoming downbeat at least ``target_offset_sec``
    past ``incoming_anchor_sec``. None if no such downbeat exists in the
    remaining grid (e.g. the incoming track is too short, or the catalog
    grid was somehow truncated)."""

    target_time = incoming_anchor_sec + target_offset_sec
    for db in incoming_downbeats:
        if db >= target_time:
            return float(db)
    return None


def pick_transition_style(
    *,
    outgoing_bpm: Optional[float],
    incoming_bpm: Optional[float],
    phrase_tier: str,
    incoming_anchor_catalog_sec: float,
    incoming_downbeats: Sequence[float],
    xfade_sec: float,
    bpm_delta_threshold: float = 2.0,
) -> TransitionStyleChoice:
    """Decide which crossfade move fits the current transition.

    Returns ``BASS_SWAP`` iff ALL of the following hold:

    - Both BPMs known and ``|Δbpm| < bpm_delta_threshold`` (keeps the
      already-stretching incoming deck from also having to fight EQ
      automation artefacts — small Δ means rate ≈ 1.0).
    - ``phrase_tier == "16-bar"`` — the anchor is on a structurally
      significant downbeat, so a "drop" 4-8 bars later feels intentional,
      not random.
    - We can find an incoming downbeat at least
      ``xfade_sec * BASS_SWAP_DROP_AT_FRACTION`` past the anchor. Without
      a real downbeat to snap on, the drop has no musical target.

    Otherwise returns ``SMOOTH_BLEND`` (the legacy behaviour).

    The function is pure / deterministic — the LLM and future
    softmax+temperature scoring layer call into the same primitive.
    """
    if outgoing_bpm is None or incoming_bpm is None:
        return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)

    if abs(outgoing_bpm - incoming_bpm) >= bpm_delta_threshold:
        return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)

    if phrase_tier != "16-bar":
        return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)

    if xfade_sec <= 0:
        return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)

    drop_target_offset = xfade_sec * BASS_SWAP_DROP_AT_FRACTION
    drop_at = _find_drop_downbeat(
        incoming_downbeats=incoming_downbeats,
        incoming_anchor_sec=incoming_anchor_catalog_sec,
        target_offset_sec=drop_target_offset,
    )
    if drop_at is None:
        return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)

    return TransitionStyleChoice(
        style=TransitionStyle.BASS_SWAP,
        bass_swap=BassSwapParams(
            hpf_cutoff_during_hz=BASS_SWAP_HPF_DURING_HZ,
            hpf_cutoff_after_hz=BASS_SWAP_HPF_AFTER_HZ,
            drop_at_incoming_sec=drop_at,
        ),
    )


def serialise_choice(choice: TransitionStyleChoice) -> dict:
    """Flatten a TransitionStyleChoice into the WS payload shape.

    Frontend contract:

    - ``transition_style``: ``"smooth_blend"`` | ``"bass_swap"`` — the
      switch the deck looks at.
    - ``bass_swap``: present iff ``transition_style == "bass_swap"``. The
      keys mirror ``BassSwapParams`` but with explicit time units in the
      names so the JS side doesn't have to guess.
    """
    payload: dict = {"transition_style": choice.style.value}
    if choice.style is TransitionStyle.BASS_SWAP and choice.bass_swap is not None:
        payload["bass_swap"] = {
            "hpf_cutoff_during_hz": round(choice.bass_swap.hpf_cutoff_during_hz, 2),
            "hpf_cutoff_after_hz": round(choice.bass_swap.hpf_cutoff_after_hz, 2),
            "drop_at_incoming_sec": round(choice.bass_swap.drop_at_incoming_sec, 4),
        }
    return payload
