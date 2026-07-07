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

DRUM_NOTES = {"kick": 36, "snare": 38, "hats": 42, "perc": 37, "shaker": 70, "clap": 39}

# apply_density removal priority: weakest metric position first (S-3 / #72).
# Class order: off-16ths -> off-8ths -> beats 2&4 -> downbeats.
_STEP_WEAKNESS = ([1, 3, 5, 7, 9, 11, 13, 15], [2, 6, 10, 14], [4, 12], [0, 8])
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


def apply_density(pattern: str, density: float, rng: random.Random) -> str:
    """Deterministic density transform of a 16-step pattern (S-3 / #72).

    target hit-count = round(density * 16). Below the written count, hits
    are removed weakest-beat-first (off-16ths, then off-8ths, then beats,
    then downbeats; seeded tie-break within a class). Above it, plain 'x'
    embellishments are added on empty steps, weakest positions first.
    Monotonic in note count for a fixed pattern + RNG stream position.
    """
    steps = list(pattern)
    written = [i for i, ch in enumerate(steps) if ch != "."]
    target = round(density * len(steps))
    if target < len(written):
        removable = []
        for weakness_class in _STEP_WEAKNESS:
            in_class = [i for i in weakness_class if steps[i] != "."]
            removable.extend(rng.sample(in_class, len(in_class)))
        for i in removable[: len(written) - target]:
            steps[i] = "."
    elif target > len(written):
        addable = []
        for weakness_class in _STEP_WEAKNESS:
            in_class = [i for i in weakness_class if steps[i] == "."]
            addable.extend(rng.sample(in_class, len(in_class)))
        for i in addable[: target - len(written)]:
            steps[i] = "x"
    return "".join(steps)


def _fill_steps(pattern: str, name: str, rng: random.Random) -> str:
    """Deterministic last-bar fill: add hits on empty steps in the bar's
    second half (steps 8-15); the kick's downbeat (step 0) is never touched
    — fills never rewrite the anchor."""
    steps = list(pattern)
    candidates = [i for i in range(8, STEPS_PER_BAR) if steps[i] == "."]
    if name == "kick" and 0 in candidates:
        candidates.remove(0)
    density_frac = sum(1 for ch in steps if ch != ".") / len(steps)
    extra = min(len(candidates), 1 + int(3 * density_frac))
    for i in rng.sample(candidates, extra) if candidates else []:
        steps[i] = "x"
    return "".join(steps)


def _drum_events(name: str, role: DrumRole, bar: int, rng: random.Random,
                 feel=None, pattern: str | None = None) -> list[MidiEvent]:
    # feel=0/0 (or None) draws NOTHING extra from the RNG, so a spec without
    # feel renders byte-identical to pre-M-5 output (determinism, FS1).
    # `pattern` overrides role.pattern (density/fill transforms, S-3) — the
    # transform happens ONCE per role in render(), never per bar.
    slop = feel.timing_slop if feel is not None and name != "kick" else 0.0
    ghosts = feel.ghost_notes if feel is not None and name != "kick" else 0.0
    events = []
    note = DRUM_NOTES[name]
    bar_tick = bar * TICKS_PER_BAR
    swing_ticks = int(round(role.swing * TICKS_PER_STEP))
    for step, ch in enumerate(pattern if pattern is not None else role.pattern):
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
    # independent of dict insertion order (determinism, FS1). New S-3 roles
    # sit AFTER hats and BEFORE bass so pre-S-3 specs keep their exact RNG
    # draw order (byte-identical output).
    for name in ("kick", "snare", "hats", "perc", "shaker", "clap", "bass"):
        role = spec.roles.get(name)
        if role is None:
            continue
        pattern = None
        fill_pattern = None
        if isinstance(role, DrumRole):
            if role.density is not None:
                pattern = apply_density(role.pattern, role.density, rng)
            if role.fill == "auto":
                fill_pattern = _fill_steps(pattern if pattern is not None else role.pattern,
                                           name, rng)
        for bar in range(spec.for_bars):
            if isinstance(role, DrumRole):
                bar_pattern = fill_pattern if (fill_pattern is not None
                                               and bar == spec.for_bars - 1) else pattern
                events.extend(_drum_events(name, role, bar, rng, spec.feel, pattern=bar_pattern))
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
