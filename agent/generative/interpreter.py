"""spec -> MIDI event stream. Pure, deterministic with seed (FS1).

No I/O, no LLM, no clock — just math. Same spec + same seed must produce a
byte-identical event list; the humanization (velocity jitter) draws from a
seeded RNG so determinism survives.

Grid: TICKS_PER_BEAT ticks per quarter note, 4 beats per bar, 16th-note
steps (TICKS_PER_STEP ticks each). Swing delays every odd 16th step by
`swing` fraction of a step — the classic hat shuffle.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .spec import (
    BassRole,
    ControlsRole,
    DrumRole,
    PadRole,
    PatternSpec,
    STEPS_PER_BAR,
    chord_to_midi,
)

TICKS_PER_BEAT = 24
BEATS_PER_BAR = 4
TICKS_PER_BAR = TICKS_PER_BEAT * BEATS_PER_BAR
TICKS_PER_STEP = TICKS_PER_BAR // STEPS_PER_BAR  # 6

DRUM_CHANNEL = 9  # GM drums (0-indexed)
BASS_CHANNEL = 0
PAD_CHANNEL = 1

DRUM_NOTES = {"kick": 36, "snare": 38, "hats": 42}
DRUM_HIT_TICKS = TICKS_PER_STEP // 2  # short percussive gate
ACCENT_BOOST = 15
VEL_JITTER = 5  # humanization bound: |rendered - spec vel| <= this (+accent)

# M-5 feel bounds. Slop shifts snare/hat hits by at most one tick either way
# (the kick never drifts — it anchors the groove); ghosts are sparse, quiet
# insertions on empty 16th steps.
SLOP_MAX_TICKS = 1
GHOST_DENSITY = 0.15   # per-empty-step probability at ghost_notes=1.0
GHOST_VEL_RATIO = 0.35


@dataclass(frozen=True, order=True)
class MidiEvent:
    tick: int
    kind: str  # "on" | "off" | "cc" (for cc: note = controller number, velocity = value)
    channel: int
    note: int
    velocity: int


def _clamp_vel(v: int) -> int:
    return max(1, min(127, v))


def _drum_events(name: str, role: DrumRole, bar: int, rng: random.Random,
                 feel=None) -> list[MidiEvent]:
    # feel=0/0 (or None) draws NOTHING extra from the RNG, so a spec without
    # feel renders byte-identical to pre-M-5 output (determinism, FS1).
    slop = feel.timing_slop if feel is not None and name != "kick" else 0.0
    ghosts = feel.ghost_notes if feel is not None and name != "kick" else 0.0
    events = []
    note = DRUM_NOTES[name]
    bar_tick = bar * TICKS_PER_BAR
    swing_ticks = int(round(role.swing * TICKS_PER_STEP))
    for step, ch in enumerate(role.pattern):
        tick = bar_tick + step * TICKS_PER_STEP + (swing_ticks if step % 2 == 1 else 0)
        if ch == ".":
            if ghosts > 0 and rng.random() < ghosts * GHOST_DENSITY:
                vel = _clamp_vel(int(role.vel * GHOST_VEL_RATIO) + rng.randint(-VEL_JITTER, VEL_JITTER))
                events.append(MidiEvent(tick, "on", DRUM_CHANNEL, note, vel))
                events.append(MidiEvent(tick + DRUM_HIT_TICKS, "off", DRUM_CHANNEL, note, 0))
            continue
        if slop > 0 and rng.random() < slop:
            tick = max(0, tick + rng.choice((-SLOP_MAX_TICKS, SLOP_MAX_TICKS)))
        vel = role.vel + (ACCENT_BOOST if ch == "X" else 0) + rng.randint(-VEL_JITTER, VEL_JITTER)
        events.append(MidiEvent(tick, "on", DRUM_CHANNEL, note, _clamp_vel(vel)))
        events.append(MidiEvent(tick + DRUM_HIT_TICKS, "off", DRUM_CHANNEL, note, 0))
    return events


def _bass_events(role: BassRole, bar: int, rng: random.Random, phrase_ticks: int) -> list[MidiEvent]:
    events = []
    bar_tick = bar * TICKS_PER_BAR
    for step, note, beats in role.notes:
        # M-2: a note loops with a period of however many bars it spans —
        # short notes repeat every bar (v0.x behavior), a 32-beat drone
        # attacks once and just sounds.
        period_bars = max(1, math.ceil(beats / BEATS_PER_BAR))
        if bar % period_bars != 0:
            continue
        tick = bar_tick + step * TICKS_PER_STEP
        vel = _clamp_vel(role.vel + rng.randint(-VEL_JITTER, VEL_JITTER))
        # Clip at phrase end so the next phrase's attack lands on a clean grid.
        off = min(tick + max(1, int(round(beats * TICKS_PER_BEAT))), phrase_ticks - 1)
        if off <= tick:
            continue
        events.append(MidiEvent(tick, "on", BASS_CHANNEL, note, vel))
        events.append(MidiEvent(off, "off", BASS_CHANNEL, note, 0))
    return events


def cc_value(from_val: float, to_val: float, progress: float) -> int:
    """Linear ramp position -> 7-bit CC value. progress in [0, 1]."""
    return max(0, min(127, int(round(127 * (from_val + (to_val - from_val) * progress)))))


def _control_events(role: ControlsRole, total_bars: int) -> list[MidiEvent]:
    """Render CC ramps to one update per 16th step, deduped on value change.

    Ramps are clipped to the phrase end; a ramp starting past the last bar
    is dropped. Emitted once per phrase (not per bar — ramps span bars).
    """
    events = []
    for ramp in role.ramps:
        if ramp.start_bar >= total_bars:
            continue
        end_bar = min(ramp.start_bar + ramp.over_bars, total_bars)
        start_tick = ramp.start_bar * TICKS_PER_BAR
        span_ticks = (end_bar - ramp.start_bar) * TICKS_PER_BAR
        last_value = None
        for offset in range(0, span_ticks + 1, TICKS_PER_STEP):
            progress = min(1.0, offset / span_ticks) if span_ticks else 1.0
            value = cc_value(ramp.from_val, ramp.to_val, progress)
            if value != last_value:
                events.append(MidiEvent(start_tick + offset, "cc", ramp.channel, ramp.cc, value))
                last_value = value
    return events


def _pad_phrase_events(role: PadRole, total_bars: int) -> list[MidiEvent]:
    """Render the whole progression: voice-led changes, optional sustain.

    First chord uses the spec's voicing; every later chord is voice-led
    from the previous one (harmony.voice_lead — minimal movement, M-1).
    hold=True sustains each chord until its next change; hold=False keeps
    the v0.x behavior of retriggering on every bar.
    """
    from .harmony import voice_lead  # local import: keeps spec/harmony import order acyclic

    changes = [(bar, chord) for bar, chord in role.progression if bar < total_bars]
    if not changes:
        return []
    events = []
    notes: list[int] = []
    for i, (start_bar, chord) in enumerate(changes):
        end_bar = changes[i + 1][0] if i + 1 < len(changes) else total_bars
        notes = chord_to_midi(chord, role.voicing) if i == 0 else voice_lead(notes, chord)
        if role.hold:
            spans = [(start_bar * TICKS_PER_BAR, end_bar * TICKS_PER_BAR - 1)]
        else:
            spans = [(bar * TICKS_PER_BAR, (bar + 1) * TICKS_PER_BAR - 1)
                     for bar in range(start_bar, end_bar)]
        for on_tick, off_tick in spans:
            for note in notes:
                events.append(MidiEvent(on_tick, "on", PAD_CHANNEL, note, role.vel))
                events.append(MidiEvent(off_tick, "off", PAD_CHANNEL, note, 0))
    return events


def render(spec: PatternSpec, seed: int = 0) -> list[MidiEvent]:
    """Render a full phrase (spec.for_bars bars) to a sorted event list."""
    rng = random.Random(seed)
    events: list[MidiEvent] = []
    phrase_ticks = spec.for_bars * TICKS_PER_BAR
    # Iterate role-major in a fixed order so the RNG draw sequence is
    # independent of dict insertion order (determinism, FS1).
    for name in ("kick", "snare", "hats", "bass"):
        role = spec.roles.get(name)
        if role is None:
            continue
        for bar in range(spec.for_bars):
            if isinstance(role, DrumRole):
                events.extend(_drum_events(name, role, bar, rng, spec.feel))
            elif isinstance(role, BassRole):
                events.extend(_bass_events(role, bar, rng, phrase_ticks))
    pad = spec.roles.get("pad")
    if isinstance(pad, PadRole):
        events.extend(_pad_phrase_events(pad, spec.for_bars))
    controls = spec.roles.get("controls")
    if isinstance(controls, ControlsRole):
        events.extend(_control_events(controls, spec.for_bars))
    events.sort()
    return events


def total_ticks(spec: PatternSpec) -> int:
    return spec.for_bars * TICKS_PER_BAR
