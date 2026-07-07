"""Instant control layer: typed intent -> immediate CC ramp, no LLM in the path.

The mind reacts at phrase cadence (bars of latency); this layer reacts at
tick cadence. When the human types "darker", a deterministic CC ramp starts
on the next tick and lands within a bar, while the structural change follows
at the phrase boundary. Both surfaces write the same CC numbers, so the mix
stays coherent.

CC contract (E-1): Surge pre-wires Macros 1-8 to CC 41-48 — no MIDI learn.
The PATCH defines what each macro means for that sound (one macro can move
cutoff + reverb + drive together). Apollo-compatible patches wire:
  Macro 1 / CC 41 = energy    (intensity, drive, presence)
  Macro 2 / CC 42 = brightness (filter opening, air)
  Macro 3 / CC 43 = space     (send level, reverb size/mix)
  Macro 4 / CC 44 = motion    (LFO depth, movement)
Legacy patches wired for the pre-E-1 contract still work: energy mirrors to
CC 1 (modwheel) and brightness to CC 74.

Pure Python, no I/O: LiveControls.on_tick() returns MidiEvents; the caller
sends them. Fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .interpreter import MidiEvent, TICKS_PER_BAR, TICKS_PER_STEP

CC_ENERGY = 41      # Surge Macro 1
CC_BRIGHTNESS = 42  # Surge Macro 2
CC_SPACE = 43       # Surge Macro 3
CC_MOTION = 44      # Surge Macro 4

# Pre-E-1 contract, mirrored so old patches keep responding.
LEGACY_MIRROR = {CC_ENERGY: 1, CC_BRIGHTNESS: 74}

# keyword (substring, lowercase) -> target levels. First match wins, ordered
# most-specific first. Related CCs ramp together — one word, one gesture.
INTENT_TARGETS: list[tuple[str, dict[int, float]]] = [
    ("darker", {CC_ENERGY: 0.25, CC_BRIGHTNESS: 0.15, CC_SPACE: 0.55}),
    ("dark", {CC_ENERGY: 0.3, CC_BRIGHTNESS: 0.2, CC_SPACE: 0.5}),
    ("brighter", {CC_BRIGHTNESS: 0.85, CC_SPACE: 0.35}),
    ("bright", {CC_BRIGHTNESS: 0.8}),
    ("open", {CC_BRIGHTNESS: 0.85}),
    ("peak", {CC_ENERGY: 1.0, CC_BRIGHTNESS: 0.9, CC_MOTION: 0.7}),
    ("build", {CC_ENERGY: 0.85, CC_BRIGHTNESS: 0.7, CC_MOTION: 0.6}),
    ("lift", {CC_ENERGY: 0.8, CC_BRIGHTNESS: 0.7}),
    ("energy", {CC_ENERGY: 0.9, CC_MOTION: 0.6}),
    ("calm", {CC_ENERGY: 0.3, CC_BRIGHTNESS: 0.35, CC_MOTION: 0.2, CC_SPACE: 0.6}),
    ("down", {CC_ENERGY: 0.35, CC_BRIGHTNESS: 0.3}),
    ("strip", {CC_ENERGY: 0.2, CC_SPACE: 0.2, CC_MOTION: 0.1}),
    ("space", {CC_SPACE: 0.9}),
    ("wash", {CC_SPACE: 0.9, CC_MOTION: 0.5}),
    ("dry", {CC_SPACE: 0.1}),
    ("motion", {CC_MOTION: 0.8}),
    ("movement", {CC_MOTION: 0.8}),
    ("still", {CC_MOTION: 0.1}),
]

DEFAULT_LEVELS = {CC_ENERGY: 0.6, CC_BRIGHTNESS: 0.6, CC_SPACE: 0.4, CC_MOTION: 0.3}


def match_intent(text: str) -> dict[int, float] | None:
    """Return CC targets for an intent line, or None if nothing matches."""
    lowered = (text or "").lower()
    for keyword, targets in INTENT_TARGETS:
        if keyword in lowered:
            return dict(targets)
    return None


@dataclass
class _Ramp:
    cc: int
    channel: int
    start_tick: int
    span_ticks: int
    from_val: float
    to_val: float

    def value_at(self, tick: int) -> float:
        if self.span_ticks <= 0 or tick >= self.start_tick + self.span_ticks:
            return self.to_val
        progress = max(0, tick - self.start_tick) / self.span_ticks
        return self.from_val + (self.to_val - self.from_val) * progress


class LiveControls:
    """Tracks current CC levels and emits ramp events tick by tick.

    trigger() starts a ramp from the CURRENT level (mid-flight retriggers
    pick up where the sound actually is, no jumps). on_tick() returns the
    events due now — call it every tick, send what it returns.
    """

    def __init__(self, channel: int = 0, ramp_bars: float = 1.0):
        self.channel = channel
        self.ramp_ticks = max(1, int(round(ramp_bars * TICKS_PER_BAR)))
        self.levels: dict[int, float] = dict(DEFAULT_LEVELS)
        self._ramps: dict[int, _Ramp] = {}
        self._sent: dict[int, int] = {}  # cc -> last 7-bit value emitted

    def trigger(self, intent: str, now_tick: int) -> bool:
        """Start ramps for a matched intent. Returns True if it matched."""
        targets = match_intent(intent)
        if not targets:
            return False
        for cc, target in targets.items():
            self._ramps[cc] = _Ramp(
                cc=cc, channel=self.channel, start_tick=now_tick,
                span_ticks=self.ramp_ticks,
                from_val=self.levels.get(cc, DEFAULT_LEVELS.get(cc, 0.5)),
                to_val=target,
            )
        return True

    def on_tick(self, tick: int) -> list[MidiEvent]:
        """Events due at this tick. Updates at 16th resolution, deduped."""
        if not self._ramps or tick % TICKS_PER_STEP != 0:
            return []
        events = []
        done = []
        for cc, ramp in self._ramps.items():
            level = ramp.value_at(tick)
            self.levels[cc] = level
            value = max(0, min(127, int(round(127 * level))))
            if self._sent.get(cc) != value:
                self._sent[cc] = value
                events.append(MidiEvent(tick, "cc", ramp.channel, cc, value))
                legacy = LEGACY_MIRROR.get(cc)
                if legacy is not None:
                    events.append(MidiEvent(tick, "cc", ramp.channel, legacy, value))
            if tick >= ramp.start_tick + ramp.span_ticks:
                done.append(cc)
        for cc in done:
            del self._ramps[cc]
        return events
