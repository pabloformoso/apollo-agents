"""Shared phase-lock primitives used by every transition path in the project.

v3.0 introduced downbeat-accurate, phrase-aligned crossfades on the offline
render path (``main.build_mix``). Until v3.0 the live engines used their own
time-based linear-fade crossfade, which silently disagreed with the offline
behaviour: the same playlist on /live and on the YouTube render produced
different beat alignment, and the live path could not stay phase-locked at
all when pyrubberband time-stretch was applied.

This module is the single source of truth that the offline mixer, the
terminal-side ``LiveEngineLocal``, and the web ``LiveEngineBrowser`` all
import. Anything more than a thin AudioSegment wrapper lives here so the
three paths can never drift again.

Naming convention: public names are unprefixed (e.g. ``GridTracker``,
``pick_incoming_anchor``). ``main.py`` re-exports them under the historical
underscore-prefixed names (``_GridTracker``, ``_pick_incoming_anchor``)
purely so the pre-existing ``tests/test_phase_lock.py`` import surface
keeps working without a rename pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from agent.transition_styles import (
    TransitionStyle,
    TransitionStyleChoice,
    pick_transition_style,
)


def _default_smooth_blend() -> TransitionStyleChoice:
    """Default factory for the LiveTransitionPlan.transition_style field.

    Lives at module scope (not a lambda) so the dataclass default_factory
    pickles cleanly across processes — the live engines are not pickled
    today but keeping the door open avoids a debugging trap later.
    """
    return TransitionStyleChoice(style=TransitionStyle.SMOOTH_BLEND)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Pickup heuristic: if the first bar's RMS is below this fraction of the
# track-mean RMS, treat downbeats[0] as an intro pickup and start at downbeats[1].
INCOMING_PICKUP_RMS_RATIO: float = 0.4

# Sample count for the raised-cosine guard at each end of the overlap window.
# Masks any one-sample discontinuity from rounding while staying inaudible.
XFADE_EDGE_GUARD_SAMPLES: int = 64

# v2 beatgrid schema version. Catalog entries with version < 2 are legacy
# (librosa-only) and the mixer must synthesise downbeats via
# ``synthesise_downbeats_from_v1``.
BEATGRID_SCHEMA_VERSION: int = 2

# Default crossfade + tempo-ramp lengths, mirroring ``main.CROSSFADE_SEC`` and
# ``main.TEMPO_RAMP_SEC``. Kept duplicated rather than imported to avoid a
# circular dependency (main.py imports from this module). If you change one,
# change both.
DEFAULT_CROSSFADE_SEC: float = 12.0
DEFAULT_TEMPO_RAMP_SEC: float = 16.0

# BPM delta below which tempo matching is a no-op (no audible benefit from
# stretching, and ~5 BPM falls within typical madmom/librosa detection noise).
# Mirrors ``main.BPM_MATCH_THRESHOLD`` and ``live_engine._BPM_THRESHOLD``.
DEFAULT_BPM_MATCH_THRESHOLD: float = 5.0

# Safety bounds on the time-stretch ratio. Past 1.5× (or its inverse) the
# stretched audio sounds wrong regardless of algorithm, and a malformed
# catalog entry could otherwise produce a 10× rate that just stops playing.
# Mirrors ``live_engine._STRETCH_MAX`` / ``_STRETCH_MIN``.
STRETCH_RATIO_MAX: float = 1.5
STRETCH_RATIO_MIN: float = 1.0 / STRETCH_RATIO_MAX

# v3.5 — beat-lock grid-warp tunables.
#
# Coefficient-of-variation ceiling on a track's bar intervals below which
# per-bar grid-warp is safe. A tight 4/4 electronic grid sits near 0.005;
# live / swung material (jazz, soul, lofi) runs much higher and would
# audibly wobble if we warped its playback rate bar-by-bar. Above this
# ceiling on EITHER side the schedule falls back to a single static
# tempo-match rate (the pre-v3.5 behaviour that already sounds smooth on
# those genres). The gate is data-driven — no hardcoded genre list to keep
# in sync.
GRIDWARP_MAX_CV: float = 0.04

# A single bar whose length deviates from the track's median bar by more
# than this fraction is treated as a madmom grid glitch (a dropped or
# doubled downbeat) and warped using the median bar instead of its own —
# so one bad downbeat can't throw a whole transition out of lock.
GRIDWARP_BAR_OUTLIER_FRAC: float = 0.4


# ---------------------------------------------------------------------------
# Plan + grid tracking
# ---------------------------------------------------------------------------

@dataclass
class PhaseLockPlan:
    """Output of :func:`compute_phase_lock`. All times in seconds of catalog audio.

    Both anchors are downbeat times; cutting each track at its anchor and
    overlaying with equal-power fades produces sample-accurate phase lock.

    ``phrase_tier`` is a diagnostic label ("16-bar" / "8-bar" / "4-bar" /
    "downbeat" / "fallback") describing which level of the phrase-boundary
    ladder produced the outgoing anchor — printed per transition so a bad
    ear-test result can be reconstructed from logs.
    """
    outgoing_anchor_catalog_sec: float
    incoming_anchor_catalog_sec: float
    xfade_catalog_sec: float
    ramp_catalog_sec: float
    phrase_tier: str
    incoming_pickup_skipped: bool = False


@dataclass
class GridState:
    """Mapping catalog→mix time for the BODY portion of the current outgoing track.

    Body has no time-stretch (it plays at native_bpm in the mix), so the
    mapping is a constant offset. We only need correctness for the body —
    the next transition's outgoing anchor will live there.
    """
    track_id: str
    duration_catalog_sec: float
    downbeats_sec: list[float]
    beats_per_bar: int
    body_catalog_start_sec: float
    body_mix_start_sec: float

    def catalog_to_mix(self, catalog_t: float) -> float:
        return self.body_mix_start_sec + (catalog_t - self.body_catalog_start_sec)


class GridTracker:
    """Tracks the current outgoing track's catalog↔mix grid mapping.

    Single source of truth across transitions — the body portion of every
    transitioned-in track lands at native_bpm, so a simple offset suffices.
    Without this, cumulative time-stretches accumulate and the chosen
    anchor at transition N+1 would drift away from a real downbeat in
    mix-time.
    """

    def __init__(self) -> None:
        self.state: Optional[GridState] = None

    def set_first(
        self,
        *,
        track_id: str,
        duration_catalog_sec: float,
        downbeats_sec: Sequence[float],
        beats_per_bar: int,
        body_mix_start_sec: float = 0.0,
    ) -> None:
        self.state = GridState(
            track_id=track_id,
            duration_catalog_sec=duration_catalog_sec,
            downbeats_sec=list(downbeats_sec),
            beats_per_bar=beats_per_bar,
            body_catalog_start_sec=0.0,
            body_mix_start_sec=body_mix_start_sec,
        )

    def set_after_transition(
        self,
        *,
        track_id: str,
        duration_catalog_sec: float,
        downbeats_sec: Sequence[float],
        beats_per_bar: int,
        incoming_anchor_catalog_sec: float,
        xfade_catalog_sec: float,
        ramp_catalog_sec: float,
        body_mix_start_sec: float,
    ) -> None:
        body_catalog_start = (
            incoming_anchor_catalog_sec
            + xfade_catalog_sec
            + ramp_catalog_sec
        )
        self.state = GridState(
            track_id=track_id,
            duration_catalog_sec=duration_catalog_sec,
            downbeats_sec=list(downbeats_sec),
            beats_per_bar=beats_per_bar,
            body_catalog_start_sec=body_catalog_start,
            body_mix_start_sec=body_mix_start_sec,
        )


# ---------------------------------------------------------------------------
# Anchor selection
# ---------------------------------------------------------------------------

def find_phrase_anchor(
    downbeats: Sequence[float],
    target_sec: float,
    track_duration_sec: float,
    min_tail_sec: float = DEFAULT_CROSSFADE_SEC + 1.0,
    max_offset_sec: float = 4.0,
) -> tuple[float, str]:
    """Pick the downbeat closest to ``target_sec`` sitting on a 16/8/4-bar boundary.

    Phrase boundary candidates are ``downbeats[::N]`` for N=16, 8, 4 (counting
    bars from ``downbeats[0]``, which madmom locks to the song's true bar 1).
    Falls back through the ladder when no candidate fits the constraints,
    finally returning the nearest plain downbeat. The string return is a
    diagnostic tier label printed alongside per-transition logging.
    """
    if not downbeats:
        return target_sec, "fallback"

    def _candidates(stride: int) -> list[float]:
        out: list[float] = []
        for i in range(0, len(downbeats), stride):
            t = downbeats[i]
            if (track_duration_sec - t) < min_tail_sec:
                continue
            if abs(t - target_sec) > max_offset_sec:
                continue
            out.append(t)
        return out

    for stride, label in (
        (16, "16-bar"),
        (8, "8-bar"),
        (4, "4-bar"),
        (1, "downbeat"),
    ):
        cands = _candidates(stride)
        if cands:
            return min(cands, key=lambda t: abs(t - target_sec)), label

    # Last resort: closest beat we know about, even past the tail constraint.
    return min(downbeats, key=lambda t: abs(t - target_sec)), "fallback"


def pick_incoming_anchor(
    downbeats: Sequence[float],
    audio_y: Optional[np.ndarray],
    sr: int,
) -> tuple[float, bool]:
    """Choose the incoming track's anchor downbeat, optionally skipping a pickup bar.

    Returns ``(anchor_sec, pickup_skipped)``. When the first bar's energy is
    well below the track average we advance to ``downbeats[1]`` — a cheap way
    to skip atmospheric pickups / sweeps that would otherwise crossfade in
    inaudibly. If ``audio_y`` is ``None`` (e.g. live engine doing this from
    the catalog without having loaded the next track's samples yet) the
    heuristic is skipped and we keep ``downbeats[0]``.
    """
    if not downbeats:
        return 0.0, False
    default = float(downbeats[0])
    if len(downbeats) < 2 or audio_y is None or len(audio_y) == 0:
        return default, False

    bar0_start = int(round(default * sr))
    bar0_end = int(round(downbeats[1] * sr))
    if bar0_end <= bar0_start or bar0_start >= len(audio_y):
        return default, False
    bar0 = audio_y[bar0_start:min(bar0_end, len(audio_y))]
    sample_window = audio_y[: min(len(audio_y), sr * 60)]
    bar_rms = float(np.sqrt(np.mean(np.square(bar0)))) if len(bar0) else 0.0
    track_rms = (
        float(np.sqrt(np.mean(np.square(sample_window)))) if len(sample_window) else 0.0
    )
    if track_rms > 0.0 and bar_rms < INCOMING_PICKUP_RMS_RATIO * track_rms:
        return float(downbeats[1]), True
    return default, False


def compute_phase_lock(
    *,
    outgoing_downbeats: Sequence[float],
    outgoing_duration_catalog_sec: float,
    incoming_downbeats: Sequence[float],
    incoming_audio_y: Optional[np.ndarray],
    incoming_sr: int,
    target_xfade_sec: float = DEFAULT_CROSSFADE_SEC,
    target_ramp_sec: float = DEFAULT_TEMPO_RAMP_SEC,
) -> PhaseLockPlan:
    """Plan a downbeat-locked transition between two tracks.

    Both tracks are sliced at a downbeat. Cutting at a downbeat means the
    first sample of each track's xfade slice IS a downbeat; overlay-adding
    the two slices puts them in phase by construction. The outgoing anchor
    is chosen near ``(duration - xfade)`` on a phrase boundary; the incoming
    anchor is its first downbeat (or [1] if the first bar is a quiet pickup).
    """
    target_pos = outgoing_duration_catalog_sec - target_xfade_sec
    outgoing_anchor, tier = find_phrase_anchor(
        outgoing_downbeats,
        target_pos,
        outgoing_duration_catalog_sec,
        min_tail_sec=target_xfade_sec + 0.5,
    )
    incoming_anchor, pickup_skipped = pick_incoming_anchor(
        incoming_downbeats, incoming_audio_y, incoming_sr,
    )
    return PhaseLockPlan(
        outgoing_anchor_catalog_sec=float(outgoing_anchor),
        incoming_anchor_catalog_sec=float(incoming_anchor),
        xfade_catalog_sec=float(target_xfade_sec),
        ramp_catalog_sec=float(target_ramp_sec),
        phrase_tier=tier,
        incoming_pickup_skipped=pickup_skipped,
    )


# ---------------------------------------------------------------------------
# Numpy equal-power crossfade
# ---------------------------------------------------------------------------

def phase_locked_crossfade_np(
    mix_y: np.ndarray,
    incoming_y: np.ndarray,
    xfade_samples: int,
) -> np.ndarray:
    """Sample-accurate equal-power overlay-add at the tail of ``mix_y``.

    Caller is responsible for slicing both buffers so that the LAST
    ``xfade_samples`` of ``mix_y`` and the FIRST ``xfade_samples`` of
    ``incoming_y`` represent the SAME musical bar at the SAME downbeat —
    this function does not align anything itself, it only sums them with
    cos/sin curves that preserve power.

    Works for mono (1-D float arrays) and stereo (2-D float arrays
    shaped ``[n_samples, n_channels]``). A 64-sample raised-cosine guard
    at the entry of the outgoing tail masks any 1-sample rounding click
    that may show up at the cut point.

    Returns a concatenated float32 array containing
    ``mix_y[:-n] + overlap + incoming_y[n:]``. When ``xfade_samples`` is
    non-positive or either buffer is shorter than the requested overlap,
    falls back to a plain concatenation.
    """
    n = min(int(xfade_samples), len(mix_y), len(incoming_y))
    if n <= 0:
        return np.concatenate([mix_y, incoming_y], axis=0).astype(np.float32)

    t = np.linspace(0.0, 1.0, n, endpoint=False, dtype=np.float32)
    fade_out = np.cos(t * (np.pi / 2.0)).astype(np.float32)
    fade_in = np.sin(t * (np.pi / 2.0)).astype(np.float32)

    is_stereo = mix_y.ndim == 2
    if is_stereo:
        fade_out = fade_out[:, None]
        fade_in = fade_in[:, None]

    mix_tail = mix_y[-n:].astype(np.float32) * fade_out
    in_head = incoming_y[:n].astype(np.float32) * fade_in

    guard_n = min(XFADE_EDGE_GUARD_SAMPLES, n // 2)
    if guard_n > 0:
        ramp = (
            0.5
            - 0.5
            * np.cos(np.linspace(0.0, np.pi, guard_n, dtype=np.float32))
        ).astype(np.float32)
        if is_stereo:
            ramp = ramp[:, None]
        mix_tail[:guard_n] *= ramp

    overlap = mix_tail + in_head
    return np.concatenate(
        [mix_y[:-n].astype(np.float32), overlap, incoming_y[n:].astype(np.float32)],
        axis=0,
    )


# ---------------------------------------------------------------------------
# Beatgrid v1 → v2 helpers
# ---------------------------------------------------------------------------

def is_v2_beatgrid(beatgrid: Optional[dict]) -> bool:
    """True iff ``beatgrid`` carries the v2 schema (downbeats array + version)."""
    if not beatgrid:
        return False
    return (
        beatgrid.get("version", 1) >= BEATGRID_SCHEMA_VERSION
        and isinstance(beatgrid.get("downbeats_sec"), list)
        and len(beatgrid["downbeats_sec"]) >= 1
    )


def synthesise_downbeats_from_v1(
    beatgrid: dict, track_duration_sec: float
) -> list[float]:
    """Build a v2-style downbeat list from a v1 beatgrid (bpm + first_beat_sec).

    Assumes 4/4. Used to keep mixing functional for un-migrated catalog
    entries — accurate to within the precision of the original BPM detection.
    """
    bpm = float(beatgrid.get("bpm") or 120.0)
    first_beat = float(beatgrid.get("first_beat_sec") or 0.0)
    if bpm <= 0 or track_duration_sec <= 0:
        return [first_beat]
    bar_sec = (60.0 / bpm) * 4.0
    n_bars = max(1, int((track_duration_sec - first_beat) / bar_sec) + 1)
    return [round(first_beat + i * bar_sec, 3) for i in range(n_bars)]


# ---------------------------------------------------------------------------
# Live-engine helpers
# ---------------------------------------------------------------------------

def compute_tempo_match_rate(
    outgoing_bpm: Optional[float],
    incoming_bpm: Optional[float],
    threshold: float = DEFAULT_BPM_MATCH_THRESHOLD,
) -> float:
    """Playback rate that aligns the incoming track's tempo to the outgoing's.

    Mirrors the ratio computed by ``LiveEngineLocal._time_stretch`` and the
    "match outgoing" branch of the offline mixer's ``compute_transition_bpm``
    + pyrubberband stretch. The browser path applies this as the incoming
    deck's ``HTMLMediaElement.playbackRate`` (with ``preservesPitch=true``)
    during the crossfade window so the two decks stay in beat-lock without
    pyrubberband running in WASM.

    Returns ``1.0`` (no stretch) when either BPM is missing or non-positive,
    or when the BPM delta is within ``threshold`` — same early-return shape
    as the CLI engine so the three paths' tempo decisions agree by
    construction. The result is clamped to
    ``[STRETCH_RATIO_MIN, STRETCH_RATIO_MAX]`` so a malformed catalog entry
    can't produce a runaway rate.
    """
    if outgoing_bpm is None or incoming_bpm is None:
        return 1.0
    if outgoing_bpm <= 0 or incoming_bpm <= 0:
        return 1.0
    if abs(outgoing_bpm - incoming_bpm) <= threshold:
        return 1.0
    rate = outgoing_bpm / incoming_bpm
    return max(STRETCH_RATIO_MIN, min(STRETCH_RATIO_MAX, rate))


# ---------------------------------------------------------------------------
# v3.5 — feed-forward beat-lock grid-warp
# ---------------------------------------------------------------------------

@dataclass
class RateSegment:
    """One playback-rate automation point for the incoming deck.

    ``at_sec`` is seconds after the crossfade's shared ``when`` clock
    (i.e. measured from the outgoing anchor / first audible incoming
    sample). ``ramp`` selects the AudioParam method the browser deck
    applies: ``False`` → ``setValueAtTime`` (a stepped per-bar correction
    that holds until the next segment), ``True`` →
    ``linearRampToValueAtTime`` (the smooth release glide back to native
    rate after the overlap).
    """
    at_sec: float
    rate: float
    ramp: bool = False


@dataclass
class BeatRateSchedule:
    """Feed-forward playback-rate plan that keeps every incoming downbeat
    locked onto an outgoing downbeat across the whole overlap.

    This is the software equivalent of a DJ riding the pitch fader / jog
    wheel for the entire blend, except it is computed up front from both
    madmom beatgrids rather than chased by ear — so it absorbs the average
    BPM delta, the per-bar micro-tempo, AND madmom's own estimation error
    in one shot, and it is deterministic (hence testable).

    ``mode`` is a diagnostic label:
      - ``"grid_warp"`` — per-bar lock schedule produced; ``segments`` is
        non-empty.
      - ``"static"`` — one or both grids were too loose (cv >
        :data:`GRIDWARP_MAX_CV`) or too short to lock per bar; ``segments``
        is empty and the caller should fall back to the single static
        ``incoming_rate``.
    """
    mode: str
    segments: list[RateSegment] = field(default_factory=list)


def _nearest_index(downbeats: Sequence[float], t: float) -> int:
    """Index of the downbeat closest to ``t`` (assumes non-empty)."""
    return min(range(len(downbeats)), key=lambda i: abs(downbeats[i] - t))


def _is_grid_warpable(
    lengths: Sequence[float],
    max_cv: float = GRIDWARP_MAX_CV,
    outlier_frac: float = GRIDWARP_BAR_OUTLIER_FRAC,
) -> bool:
    """True iff ``lengths`` (bar durations) form a grid tight enough to warp.

    Two-stage test, designed to tell apart the two reasons a bar can be
    "wrong":

    1. **Glitches** — a handful of bars deviate hugely (a dropped/doubled
       madmom downbeat). A few of these are fine: the per-bar outlier guard
       in :func:`compute_beat_rate_schedule` repairs them. But if MANY bars
       deviate by more than ``outlier_frac`` it isn't a glitch, it's a
       genuinely loose / swung grid → reject.
    2. **Consistent swing** — bars that wobble moderately (say ±20%) trip no
       single >``outlier_frac`` outlier yet would still warble audibly if
       warped per bar. After repairing the few real glitches we measure the
       classic std/mean coefficient of variation on the cleaned lengths and
       reject anything above ``max_cv``.

    Tight 4/4 electronic grids (cv ≈ 0.005) sail through both stages; jazz /
    soul / lofi fail one or the other and fall back to the static rate.
    """
    n = len(lengths)
    if n < 2:
        return False
    median = sorted(lengths)[n // 2]
    if median <= 0:
        return False
    deviating = sum(1 for x in lengths if abs(x - median) / median > outlier_frac)
    # >~20% of bars deviating (always tolerating a single glitch) means the
    # grid is loose by nature, not glitched.
    if deviating > max(1, n // 5):
        return False
    repaired = [
        median if abs(x - median) / median > outlier_frac else x for x in lengths
    ]
    mean = sum(repaired) / n
    if mean <= 0:
        return False
    var = sum((x - mean) ** 2 for x in repaired) / n
    return (var ** 0.5) / mean <= max_cv


def compute_beat_rate_schedule(
    *,
    outgoing_downbeats: Sequence[float],
    incoming_downbeats: Sequence[float],
    outgoing_anchor_sec: float,
    incoming_anchor_sec: float,
    xfade_sec: float,
    ramp_sec: float = 0.0,
    max_cv: float = GRIDWARP_MAX_CV,
    rate_min: float = STRETCH_RATIO_MIN,
    rate_max: float = STRETCH_RATIO_MAX,
) -> BeatRateSchedule:
    """Plan a per-bar playback-rate curve that bar-locks incoming to outgoing.

    The outgoing track is the reference (plays at rate 1.0, like the deck
    already on the speakers). For each bar ``k`` of the overlap we set the
    incoming deck's rate to ``incoming_bar_len / outgoing_bar_len`` so the
    incoming track consumes exactly one outgoing bar of wall-clock per bar
    — putting every incoming downbeat on an outgoing downbeat by
    construction, not just the first one.

    Two phases of segments are emitted:
      1. **Lock** — one stepped ``setValueAtTime`` segment per overlap bar.
      2. **Release** — when ``ramp_sec > 0``, hold the matched rate to the
         end of the crossfade then ``linearRamp`` back to 1.0 over the
         tempo-ramp window, so the incoming track ends at native rate as
         the next transition's reference with no audible tempo step.

    Returns a ``"static"`` :class:`BeatRateSchedule` (empty segments) when
    either grid is too loose (cv > ``max_cv``) or too short to form at
    least two overlap bars — the caller then falls back to the single
    static ``incoming_rate`` that already sounds smooth on those genres.
    Per-bar rates are clamped to ``[rate_min, rate_max]`` and a single
    outlier bar (a dropped/doubled madmom downbeat) is warped using the
    median bar instead of its own length.
    """
    if len(outgoing_downbeats) < 2 or len(incoming_downbeats) < 2 or xfade_sec <= 0:
        return BeatRateSchedule(mode="static")

    oa = _nearest_index(outgoing_downbeats, outgoing_anchor_sec)
    ia = _nearest_index(incoming_downbeats, incoming_anchor_sec)

    # Walk paired bars from each anchor until we've covered the crossfade
    # window (in outgoing wall-clock) or run out of downbeats on either
    # side. Each entry: (offset_from_anchor, outgoing_bar_len, incoming_bar_len).
    bars: list[tuple[float, float, float]] = []
    k = 0
    while (oa + k + 1) < len(outgoing_downbeats) and (ia + k + 1) < len(incoming_downbeats):
        offset = outgoing_downbeats[oa + k] - outgoing_downbeats[oa]
        if offset > xfade_sec:
            break
        out_bar = outgoing_downbeats[oa + k + 1] - outgoing_downbeats[oa + k]
        in_bar = incoming_downbeats[ia + k + 1] - incoming_downbeats[ia + k]
        bars.append((offset, out_bar, in_bar))
        k += 1

    if len(bars) < 2:
        return BeatRateSchedule(mode="static")

    out_lengths = [b[1] for b in bars]
    in_lengths = [b[2] for b in bars]

    # Gate on BOTH grids: a loose grid on either side makes the per-bar
    # rate sequence wobble, which is audible. Tight 4/4 sails through; a
    # single glitch bar is tolerated and repaired below.
    if not _is_grid_warpable(out_lengths, max_cv) or not _is_grid_warpable(in_lengths, max_cv):
        return BeatRateSchedule(mode="static")

    median_out = sorted(out_lengths)[len(out_lengths) // 2]
    median_in = sorted(in_lengths)[len(in_lengths) // 2]

    segments: list[RateSegment] = []
    last_rate = 1.0
    for offset, out_bar, in_bar in bars:
        ob, ib = out_bar, in_bar
        # Single dropped/doubled downbeat → fall back to the median bar so
        # one glitch can't yank the whole transition out of lock.
        if median_out > 0 and abs(out_bar - median_out) / median_out > GRIDWARP_BAR_OUTLIER_FRAC:
            ob = median_out
        if median_in > 0 and abs(in_bar - median_in) / median_in > GRIDWARP_BAR_OUTLIER_FRAC:
            ib = median_in
        rate = ib / ob if ob > 0 else 1.0
        rate = max(rate_min, min(rate_max, rate))
        segments.append(RateSegment(at_sec=round(offset, 6), rate=round(rate, 6), ramp=False))
        last_rate = rate

    # Release glide: hold the matched rate through the end of the
    # crossfade, then ramp back to native over the tempo-ramp window.
    if ramp_sec > 0:
        segments.append(
            RateSegment(at_sec=round(xfade_sec, 6), rate=round(last_rate, 6), ramp=False)
        )
        segments.append(
            RateSegment(at_sec=round(xfade_sec + ramp_sec, 6), rate=1.0, ramp=True)
        )

    return BeatRateSchedule(mode="grid_warp", segments=segments)


@dataclass
class LiveTransitionPlan:
    """Live-engine-facing summary of a phase-lock plan.

    Whereas :class:`PhaseLockPlan` carries catalog times only, this struct
    pre-computes the sample offsets the engines actually consume:

    - ``outgoing_anchor_sample`` — index into the OUTGOING track's PCM buffer
      where the crossfade should begin (i.e. the chosen outgoing downbeat).
    - ``incoming_start_sample`` — index into the INCOMING track's PCM buffer
      where playback should start (i.e. the chosen incoming downbeat).
    - ``xfade_samples`` — length of the equal-power overlap in samples.

    Sample rates are carried explicitly so the live engines don't have to
    cross-check. Both tracks resample to a common rate before this struct
    is built (44.1 kHz in ``LiveEngineLocal``, the browser's
    ``AudioContext`` rate in ``LiveEngineBrowser``).

    Tempo-match rates (v3.1):

    - ``incoming_rate`` — multiplier to apply to the incoming deck's playback
      speed so its tempo matches the outgoing's during the crossfade. Equals
      ``outgoing_bpm / incoming_bpm`` (clamped) when the delta exceeds
      ``DEFAULT_BPM_MATCH_THRESHOLD``, else ``1.0``. The CLI engine's
      pyrubberband pre-stretch consumes this implicitly via
      ``_time_stretch``; the browser path applies it directly as
      ``HTMLMediaElement.playbackRate``.
    - ``outgoing_rate`` — placeholder for a future meet-in-middle strategy.
      Always ``1.0`` today (matches CLI behaviour, where only the incoming
      deck is stretched).
    """
    outgoing_anchor_sample: int
    incoming_start_sample: int
    xfade_samples: int
    sample_rate: int
    phrase_tier: str
    incoming_pickup_skipped: bool
    # Raw catalog plan kept for diagnostics + tests; the engines only consume
    # the sample fields above.
    plan: PhaseLockPlan = field(repr=False)
    incoming_rate: float = 1.0
    outgoing_rate: float = 1.0
    # v3.3 — which crossfade move the engine should execute. SMOOTH_BLEND
    # is the legacy equal-power overlay; BASS_SWAP adds a HPF automation
    # the browser deck applies on the incoming track. The choice is
    # deterministic (see agent.transition_styles.pick_transition_style)
    # so tests can assert exact-match wire payloads.
    transition_style: "TransitionStyleChoice" = field(
        default_factory=lambda: _default_smooth_blend()
    )
    # v3.5 — feed-forward per-bar playback-rate curve that keeps every
    # incoming downbeat locked onto an outgoing downbeat across the whole
    # overlap (the software pitch-fader/jog ride). Defaults to a "static"
    # schedule with no segments, signalling the engine to use the single
    # ``incoming_rate`` above (the pre-v3.5 behaviour) — which is what
    # loose-grid genres (jazz/soul/lofi) fall back to.
    beat_rate_schedule: "BeatRateSchedule" = field(
        default_factory=lambda: BeatRateSchedule(mode="static")
    )


def resolve_downbeats(
    beatgrid: Optional[dict],
    track_duration_sec: float,
) -> tuple[list[float], int]:
    """Return ``(downbeats_sec, beats_per_bar)`` for any beatgrid the catalog hands us.

    Encapsulates the legacy fallback ladder so callers (offline + both live
    engines) don't have to repeat the v2/v1/none branching:

    - v2 schema → use ``downbeats_sec`` + ``beats_per_bar`` verbatim.
    - v1 schema (only ``bpm`` + ``first_beat_sec``) → synthesise a 4/4 grid.
    - ``None`` / missing → empty list + 4/4 default (caller decides whether
      to abort the transition or fall back to a linear fade).
    """
    if is_v2_beatgrid(beatgrid):
        downbeats = list(beatgrid.get("downbeats_sec") or [])
        bpb = int(beatgrid.get("beats_per_bar") or 4)
        return downbeats, bpb
    if beatgrid:
        return synthesise_downbeats_from_v1(beatgrid, track_duration_sec), 4
    return [], 4


def build_live_transition_plan(
    *,
    outgoing_beatgrid: Optional[dict],
    outgoing_duration_sec: float,
    incoming_beatgrid: Optional[dict],
    incoming_duration_sec: float,
    incoming_audio_y: Optional[np.ndarray],
    sample_rate: int,
    target_xfade_sec: float,
    target_ramp_sec: float = 0.0,
    outgoing_bpm: Optional[float] = None,
    incoming_bpm: Optional[float] = None,
    bpm_match_threshold: float = DEFAULT_BPM_MATCH_THRESHOLD,
) -> LiveTransitionPlan:
    """Top-level convenience for the live engines.

    Resolves both tracks' beatgrids (v2 / v1 / none) and computes the
    catalog-time phase-lock plan, then converts the chosen anchors to
    sample indices at the engine's sample rate. The live engines use the
    returned sample fields directly when positioning their decks.

    ``target_ramp_sec`` is carried through for parity with the offline
    pipeline (live engines that don't run a tempo ramp can leave it at 0).

    When ``outgoing_bpm`` and ``incoming_bpm`` are supplied, the returned
    plan also carries ``incoming_rate`` — a tempo-match playback rate the
    browser path applies via ``HTMLMediaElement.playbackRate``. The CLI
    engine already pre-stretches with pyrubberband so it ignores this
    field; passing the BPMs is still useful for diagnostics. Defaults to
    ``1.0`` (no rate change) when either BPM is missing.
    """
    outgoing_downbeats, _ = resolve_downbeats(outgoing_beatgrid, outgoing_duration_sec)
    incoming_downbeats, _ = resolve_downbeats(incoming_beatgrid, incoming_duration_sec)

    plan = compute_phase_lock(
        outgoing_downbeats=outgoing_downbeats,
        outgoing_duration_catalog_sec=outgoing_duration_sec,
        incoming_downbeats=incoming_downbeats,
        incoming_audio_y=incoming_audio_y,
        incoming_sr=sample_rate,
        target_xfade_sec=target_xfade_sec,
        target_ramp_sec=target_ramp_sec,
    )
    incoming_rate = compute_tempo_match_rate(
        outgoing_bpm, incoming_bpm, threshold=bpm_match_threshold,
    )
    # v3.3 — pick the named crossfade move. Deterministic, runs after
    # phase-lock so it can use the chosen incoming anchor as the
    # reference point for the bass-swap drop downbeat search.
    transition_choice = pick_transition_style(
        outgoing_bpm=outgoing_bpm,
        incoming_bpm=incoming_bpm,
        phrase_tier=plan.phrase_tier,
        incoming_anchor_catalog_sec=plan.incoming_anchor_catalog_sec,
        incoming_downbeats=incoming_downbeats,
        xfade_sec=plan.xfade_catalog_sec,
    )
    # v3.5 — feed-forward beat-lock grid-warp. Computed from the actual
    # downbeat times (not the average BPM), so it corrects micro-tempo and
    # madmom estimation error that the single static ``incoming_rate``
    # cannot. Falls back to a "static" schedule for loose grids; the engine
    # then uses ``incoming_rate`` as before.
    rate_schedule = compute_beat_rate_schedule(
        outgoing_downbeats=outgoing_downbeats,
        incoming_downbeats=incoming_downbeats,
        outgoing_anchor_sec=plan.outgoing_anchor_catalog_sec,
        incoming_anchor_sec=plan.incoming_anchor_catalog_sec,
        xfade_sec=plan.xfade_catalog_sec,
        ramp_sec=plan.ramp_catalog_sec,
    )
    return LiveTransitionPlan(
        outgoing_anchor_sample=int(round(plan.outgoing_anchor_catalog_sec * sample_rate)),
        incoming_start_sample=int(round(plan.incoming_anchor_catalog_sec * sample_rate)),
        xfade_samples=int(round(plan.xfade_catalog_sec * sample_rate)),
        sample_rate=sample_rate,
        phrase_tier=plan.phrase_tier,
        incoming_pickup_skipped=plan.incoming_pickup_skipped,
        plan=plan,
        incoming_rate=incoming_rate,
        outgoing_rate=1.0,
        transition_style=transition_choice,
        beat_rate_schedule=rate_schedule,
    )
