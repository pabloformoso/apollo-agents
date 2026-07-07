"""spec -> MIDI event stream. Pure, deterministic with seed (FS1).

No I/O, no LLM, no clock — just math. Same spec + same seed must produce a
byte-identical event list; the humanization (velocity jitter) draws from a
seeded RNG so determinism survives.

Grid: TICKS_PER_BEAT ticks per quarter note, 4 beats per bar, 16th-note
steps (TICKS_PER_STEP ticks each). Swing delays every odd 16th step by
`swing` fraction of a step — the classic hat shuffle.
"""

from __future__ import annotations

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


@dataclass(frozen=True, order=True)
class MidiEvent:
    tick: int
    kind: str  # "on" | "off" | "cc" (for cc: note = controller number, velocity = value)
    channel: int
    note: int
    velocity: int


def _clamp_vel(v: int) -> int:
    return max(1, min(127, v))


def _drum_events(name: str, role: DrumRole, bar: int, rng: random.Random) -> list[MidiEvent]:
    events = []
    note = DRUM_NOTES[name]
    bar_tick = bar * TICKS_PER_BAR
    swing_ticks = int(round(role.swing * TICKS_PER_STEP))
    for step, ch in enumerate(role.pattern):
        if ch == ".":
            continue
        tick = bar_tick + step * TICKS_PER_STEP + (swing_ticks if step % 2 == 1 else 0)
        vel = role.vel + (ACCENT_BOOST if ch == "X" else 0) + rng.randint(-VEL_JITTER, VEL_JITTER)
        events.append(MidiEvent(tick, "on", DRUM_CHANNEL, note, _clamp_vel(vel)))
        events.append(MidiEvent(tick + DRUM_HIT_TICKS, "off", DRUM_CHANNEL, note, 0))
    return events


def _bass_events(role: BassRole, bar: int, rng: random.Random) -> list[MidiEvent]:
    events = []
    bar_tick = bar * TICKS_PER_BAR
    for step, note, beats in role.notes:
        tick = bar_tick + step * TICKS_PER_STEP
        vel = _clamp_vel(role.vel + rng.randint(-VEL_JITTER, VEL_JITTER))
        events.append(MidiEvent(tick, "on", BASS_CHANNEL, note, vel))
        events.append(MidiEvent(tick + max(1, int(round(beats * TICKS_PER_BEAT))), "off", BASS_CHANNEL, note, 0))
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


def _pad_events(role: PadRole, bar: int) -> list[MidiEvent]:
    bar_tick = bar * TICKS_PER_BAR
    events = []
    for note in chord_to_midi(role.chord, role.voicing):
        events.append(MidiEvent(bar_tick, "on", PAD_CHANNEL, note, role.vel))
        events.append(MidiEvent(bar_tick + TICKS_PER_BAR - 1, "off", PAD_CHANNEL, note, 0))
    return events


def render(spec: PatternSpec, seed: int = 0) -> list[MidiEvent]:
    """Render a full phrase (spec.for_bars bars) to a sorted event list."""
    rng = random.Random(seed)
    events: list[MidiEvent] = []
    # Iterate role-major in a fixed order so the RNG draw sequence is
    # independent of dict insertion order (determinism, FS1).
    for name in ("kick", "snare", "hats", "bass", "pad"):
        role = spec.roles.get(name)
        if role is None:
            continue
        for bar in range(spec.for_bars):
            if isinstance(role, DrumRole):
                events.extend(_drum_events(name, role, bar, rng))
            elif isinstance(role, BassRole):
                events.extend(_bass_events(role, bar, rng))
            elif isinstance(role, PadRole):
                events.extend(_pad_events(role, bar))
    controls = spec.roles.get("controls")
    if isinstance(controls, ControlsRole):
        events.extend(_control_events(controls, spec.for_bars))
    events.sort()
    return events


def total_ticks(spec: PatternSpec) -> int:
    return spec.for_bars * TICKS_PER_BAR
