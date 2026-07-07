"""Pattern-spec: the slow-plane -> fast-plane contract (FS1-FS4).

A PatternSpec is the ONLY thing the mind hands to the muscle. It is:
- self-contained (the fast plane needs no LLM to interpret it),
- validated on ingest (bad input raises SpecError; the engine keeps
  playing the previous spec — reject-and-hold),
- carries `reason` (accountability, FS4) and `rethink_in_bars`
  (slow-plane cadence control).

Theory-light by design (Q3): drum roles are 16th-note step strings,
bass is an explicit note list, pad is a chord name. The musicality
lives in the mind, the schema stays dumb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STEPS_PER_BAR = 16  # 16th-note grid

BPM_MIN, BPM_MAX = 60.0, 200.0
BARS_MIN, BARS_MAX = 1, 32
VEL_MIN, VEL_MAX = 1, 127
SWING_MIN, SWING_MAX = 0.0, 0.5

_CAMELOT_RE = re.compile(r"^(1[0-2]|[1-9])[AB]$")
_NOTE_RE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
_CHORD_RE = re.compile(r"^([A-G][#b]?)(maj7|maj9|m7b5|min7|min9|min|m7|m9|m6|m|7|9|6|add9|sus2|sus4|dim|aug)?$")

DRUM_ROLES = ("kick", "snare", "hats")
PITCHED_ROLES = ("bass", "pad")
ALLOWED_ROLES = DRUM_ROLES + PITCHED_ROLES + ("controls",)

VOICINGS = ("close", "wide")

# Named drum patterns expand to a 16-step string. 'x' = hit, 'X' = accent.
NAMED_PATTERNS = {
    "4-on-floor": "x...x...x...x...",
    "offbeat": "..x...x...x...x.",
    "8ths": "x.x.x.x.x.x.x.x.",
    "16ths": "xxxxxxxxxxxxxxxx",
    "backbeat": "....x.......x...",
}

_PATTERN_CHARS = set("xX.")

_NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

CHORD_QUALITIES = {
    "": (0, 4, 7),
    "m": (0, 3, 7),
    "min": (0, 3, 7),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10),
    "9": (0, 4, 7, 10, 14),
    "maj7": (0, 4, 7, 11),
    "maj9": (0, 4, 7, 11, 14),
    "m7": (0, 3, 7, 10),
    "min7": (0, 3, 7, 10),
    "m9": (0, 3, 7, 10, 14),
    "min9": (0, 3, 7, 10, 14),
    "m7b5": (0, 3, 6, 10),
    "add9": (0, 4, 7, 14),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
}


class SpecError(ValueError):
    """A pattern-spec failed validation. The engine must reject-and-hold."""


def note_to_midi(name: str) -> int:
    """'A1' -> 33 (scientific pitch, C4 = 60)."""
    m = _NOTE_RE.match(name or "")
    if not m:
        raise SpecError(f"invalid note name: {name!r}")
    letter, accidental, octave = m.group(1), m.group(2), int(m.group(3))
    pc = _NOTE_PC[letter] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    midi = 12 * (octave + 1) + pc
    if not 0 <= midi <= 127:
        raise SpecError(f"note out of MIDI range: {name!r}")
    return midi


def chord_to_midi(chord: str, voicing: str = "close") -> list[int]:
    """'Am9' -> MIDI note numbers around octave 3/4. Deterministic."""
    m = _CHORD_RE.match(chord or "")
    if not m:
        raise SpecError(f"invalid chord name: {chord!r}")
    root_name, quality = m.group(1), m.group(2) or ""
    intervals = CHORD_QUALITIES[quality]
    pc = _NOTE_PC[root_name[0]] + (1 if root_name.endswith("#") else -1 if root_name.endswith("b") else 0)
    root = 48 + (pc % 12)  # around C3
    notes = [root + i for i in intervals]
    if voicing == "wide":
        notes = [root - 12] + notes[1:]
    return notes


def expand_pattern(pattern: str) -> str:
    """Named pattern or raw step string -> canonical 16-step string."""
    if pattern in NAMED_PATTERNS:
        return NAMED_PATTERNS[pattern]
    if not pattern or set(pattern) - _PATTERN_CHARS:
        raise SpecError(
            f"invalid pattern {pattern!r}: use a named pattern "
            f"({', '.join(sorted(NAMED_PATTERNS))}) or steps of x/X/."
        )
    if STEPS_PER_BAR % len(pattern) != 0:
        raise SpecError(f"pattern length {len(pattern)} does not divide {STEPS_PER_BAR}")
    return "".join(ch + "." * (STEPS_PER_BAR // len(pattern) - 1) for ch in pattern)


def _check_vel(value, role: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not VEL_MIN <= value <= VEL_MAX:
        raise SpecError(f"{role}: velocity must be an int in [{VEL_MIN}, {VEL_MAX}], got {value!r}")
    return value


@dataclass(frozen=True)
class DrumRole:
    pattern: str  # canonical 16-step string
    vel: int = 100
    swing: float = 0.0

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "DrumRole":
        if not isinstance(d, dict):
            raise SpecError(f"{name}: role must be an object, got {d!r}")
        pattern = expand_pattern(d.get("pattern", ""))
        vel = _check_vel(d.get("vel", 100), name)
        swing = d.get("swing", 0.0)
        if not isinstance(swing, (int, float)) or not SWING_MIN <= swing <= SWING_MAX:
            raise SpecError(f"{name}: swing must be in [{SWING_MIN}, {SWING_MAX}], got {swing!r}")
        return cls(pattern=pattern, vel=vel, swing=float(swing))


@dataclass(frozen=True)
class BassRole:
    notes: tuple[tuple[int, int, float], ...]  # (step 0-15, midi note, duration in beats)
    vel: int = 90

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "BassRole":
        if not isinstance(d, dict):
            raise SpecError(f"{name}: role must be an object, got {d!r}")
        raw = d.get("notes")
        if not isinstance(raw, list) or not raw:
            raise SpecError(f"{name}: 'notes' must be a non-empty list of [step, note, beats]")
        notes = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                raise SpecError(f"{name}: each note must be [step, note, beats], got {item!r}")
            step, note_name, beats = item
            if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step < STEPS_PER_BAR:
                raise SpecError(f"{name}: step must be an int in [0, {STEPS_PER_BAR - 1}], got {step!r}")
            # v3.0 (M-2): durations may span the whole phrase (drones). The
            # interpreter clips the note-off at the phrase end.
            if not isinstance(beats, (int, float)) or not 0 < beats <= BARS_MAX * 4:
                raise SpecError(f"{name}: duration must be in (0, {BARS_MAX * 4}] beats, got {beats!r}")
            notes.append((step, note_to_midi(note_name), float(beats)))
        vel = _check_vel(d.get("vel", 90), name)
        return cls(notes=tuple(notes), vel=vel)


@dataclass(frozen=True)
class PadRole:
    progression: tuple[tuple[int, str], ...]  # (bar, chord) — first entry at bar 0
    voicing: str = "close"
    vel: int = 60
    hold: bool = False  # True: sustain each chord until the next change; False: retrigger per bar

    @property
    def chord(self) -> str:
        """First chord — back-compat convenience for single-chord specs."""
        return self.progression[0][1]

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "PadRole":
        if not isinstance(d, dict):
            raise SpecError(f"{name}: role must be an object, got {d!r}")
        voicing = d.get("voicing", "close")
        if voicing not in VOICINGS:
            raise SpecError(f"{name}: voicing must be one of {VOICINGS}, got {voicing!r}")

        raw_prog = d.get("progression")
        if raw_prog is None:
            # v0.x single-chord form stays valid: a 1-entry progression.
            raw_prog = [[0, d.get("chord", "")]]
        if not isinstance(raw_prog, list) or not raw_prog:
            raise SpecError(f"{name}: 'progression' must be a non-empty list of [bar, chord]")
        progression = []
        prev_bar = None
        for item in raw_prog:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise SpecError(f"{name}: each progression entry must be [bar, chord], got {item!r}")
            bar, chord = item
            if not isinstance(bar, int) or isinstance(bar, bool) or not 0 <= bar < BARS_MAX:
                raise SpecError(f"{name}: progression bar must be an int in [0, {BARS_MAX - 1}], got {bar!r}")
            if prev_bar is None and bar != 0:
                raise SpecError(f"{name}: progression must start at bar 0, got bar {bar}")
            if prev_bar is not None and bar <= prev_bar:
                raise SpecError(f"{name}: progression bars must be strictly increasing, got {bar} after {prev_bar}")
            chord_to_midi(chord, voicing)  # validate now, render later
            progression.append((bar, chord))
            prev_bar = bar

        hold = d.get("hold", False)
        if not isinstance(hold, bool):
            raise SpecError(f"{name}: hold must be a boolean, got {hold!r}")
        vel = _check_vel(d.get("vel", 60), name)
        return cls(progression=tuple(progression), voicing=voicing, vel=vel, hold=hold)


@dataclass(frozen=True)
class ControlRamp:
    cc: int              # MIDI CC number (1 = mod/energy, 74 = brightness by convention)
    from_val: float      # 0.0-1.0
    to_val: float        # 0.0-1.0
    start_bar: int       # bar within the phrase the ramp starts on
    over_bars: int       # ramp length in bars (clipped to phrase end at render)
    channel: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "ControlRamp":
        if not isinstance(d, dict):
            raise SpecError(f"controls: each ramp must be an object, got {d!r}")
        cc = d.get("cc")
        if not isinstance(cc, int) or isinstance(cc, bool) or not 0 <= cc <= 127:
            raise SpecError(f"controls: cc must be an int in [0, 127], got {cc!r}")
        vals = {}
        for key in ("from", "to"):
            v = d.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0:
                raise SpecError(f"controls: '{key}' must be in [0.0, 1.0], got {v!r}")
            vals[key] = float(v)
        start_bar = d.get("start_bar", 0)
        if not isinstance(start_bar, int) or isinstance(start_bar, bool) or not 0 <= start_bar < BARS_MAX:
            raise SpecError(f"controls: start_bar must be an int in [0, {BARS_MAX - 1}], got {start_bar!r}")
        over_bars = d.get("over_bars", 1)
        if not isinstance(over_bars, int) or isinstance(over_bars, bool) or not BARS_MIN <= over_bars <= BARS_MAX:
            raise SpecError(f"controls: over_bars must be an int in [{BARS_MIN}, {BARS_MAX}], got {over_bars!r}")
        channel = d.get("channel", 0)
        if not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 15:
            raise SpecError(f"controls: channel must be an int in [0, 15], got {channel!r}")
        return cls(cc=cc, from_val=vals["from"], to_val=vals["to"],
                   start_bar=start_bar, over_bars=over_bars, channel=channel)


@dataclass(frozen=True)
class ControlsRole:
    ramps: tuple[ControlRamp, ...]

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "ControlsRole":
        if not isinstance(d, dict):
            raise SpecError(f"{name}: role must be an object, got {d!r}")
        raw = d.get("ramps")
        if not isinstance(raw, list) or not raw:
            raise SpecError(f"{name}: 'ramps' must be a non-empty list")
        return cls(ramps=tuple(ControlRamp.from_dict(r) for r in raw))


_ROLE_CLASSES = {"kick": DrumRole, "snare": DrumRole, "hats": DrumRole, "bass": BassRole,
                 "pad": PadRole, "controls": ControlsRole}


@dataclass(frozen=True)
class FeelSpec:
    """M-5: performance imperfection, rendered deterministically from the seed.

    timing_slop: probability a snare/hat hit drifts +-1 tick off the grid
    (the kick never drifts — it anchors). ghost_notes: density of extra
    low-velocity hats/snare hits on empty 16th steps. Both 0.0-1.0;
    0/0 renders byte-identical to a spec with no feel at all.
    """
    timing_slop: float = 0.0
    ghost_notes: float = 0.0

    @classmethod
    def from_dict(cls, d) -> "FeelSpec":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise SpecError(f"feel must be an object, got {d!r}")
        vals = {}
        for key in ("timing_slop", "ghost_notes"):
            v = d.get(key, 0.0)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0:
                raise SpecError(f"feel.{key} must be in [0.0, 1.0], got {v!r}")
            vals[key] = float(v)
        return cls(timing_slop=vals["timing_slop"], ghost_notes=vals["ghost_notes"])


def _check_scale(key: str, roles: dict) -> None:
    """M-3: pitched notes must belong to the Camelot key's scale.

    Local import — scales.py imports SpecError from this module, so the
    dependency must stay one-way at import time.
    """
    from .scales import camelot_scale, key_name, pc_name

    scale = camelot_scale(key)
    for name, role in roles.items():
        if isinstance(role, BassRole):
            for _step, note, _beats in role.notes:
                if note % 12 not in scale:
                    raise SpecError(
                        f"{name}: {pc_name(note)} is outside {key} ({key_name(key)}) — "
                        f'stay in the scale or set "chromatic": true and justify it in reason'
                    )
        elif isinstance(role, PadRole):
            for _bar, chord in role.progression:
                for note in chord_to_midi(chord, "close"):
                    if note % 12 not in scale:
                        raise SpecError(
                            f"{name}: chord {chord} contains {pc_name(note)}, outside {key} "
                            f'({key_name(key)}) — stay in the scale or set "chromatic": true '
                            f"and justify it in reason"
                        )


@dataclass(frozen=True)
class PatternSpec:
    for_bars: int
    bpm: float
    key: str  # Camelot, consistent with tracks.json
    roles: dict = field(default_factory=dict)
    reason: str = ""
    rethink_in_bars: int = 0  # 0 -> defaults to for_bars
    chromatic: bool = False  # True: skip scale guardrails (must be justified in reason)
    feel: FeelSpec = FeelSpec()  # no slop, no ghosts by default

    @classmethod
    def from_dict(cls, d: dict) -> "PatternSpec":
        """Validate a raw dict (e.g. straight from the LLM). Raises SpecError."""
        if not isinstance(d, dict):
            raise SpecError(f"spec must be an object, got {type(d).__name__}")

        for_bars = d.get("for_bars")
        if not isinstance(for_bars, int) or isinstance(for_bars, bool) or not BARS_MIN <= for_bars <= BARS_MAX:
            raise SpecError(f"for_bars must be an int in [{BARS_MIN}, {BARS_MAX}], got {for_bars!r}")

        bpm = d.get("bpm")
        if not isinstance(bpm, (int, float)) or not BPM_MIN <= bpm <= BPM_MAX:
            raise SpecError(f"bpm must be in [{BPM_MIN}, {BPM_MAX}], got {bpm!r}")

        key = d.get("key", "")
        if not isinstance(key, str) or not _CAMELOT_RE.match(key):
            raise SpecError(f"key must be Camelot (1A-12B), got {key!r}")

        raw_roles = d.get("roles")
        if not isinstance(raw_roles, dict) or not raw_roles:
            raise SpecError("roles must be a non-empty object")
        roles = {}
        for name, role_dict in raw_roles.items():
            role_cls = _ROLE_CLASSES.get(name)
            if role_cls is None:
                raise SpecError(f"unknown role {name!r}: allowed roles are {ALLOWED_ROLES}")
            roles[name] = role_cls.from_dict(name, role_dict)

        reason = d.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise SpecError("reason is required — every spec must state why (FS4)")

        rethink = d.get("rethink_in_bars", for_bars)
        if not isinstance(rethink, int) or isinstance(rethink, bool) or not BARS_MIN <= rethink <= BARS_MAX:
            raise SpecError(f"rethink_in_bars must be an int in [{BARS_MIN}, {BARS_MAX}], got {rethink!r}")

        chromatic = d.get("chromatic", False)
        if not isinstance(chromatic, bool):
            raise SpecError(f"chromatic must be a boolean, got {chromatic!r}")
        if not chromatic:
            _check_scale(key, roles)

        feel = FeelSpec.from_dict(d.get("feel"))

        return cls(for_bars=for_bars, bpm=float(bpm), key=key, roles=roles,
                   reason=reason.strip(), rethink_in_bars=rethink, chromatic=chromatic,
                   feel=feel)

    def summary(self) -> str:
        """One-line human/LLM-readable summary, used by state.py."""
        parts = []
        for name in ALLOWED_ROLES:
            role = self.roles.get(name)
            if role is None:
                continue
            if isinstance(role, DrumRole):
                parts.append(f"{name}={role.pattern}(v{role.vel}"
                             + (f",sw{role.swing:.2f})" if role.swing else ")"))
            elif isinstance(role, BassRole):
                parts.append(f"bass={len(role.notes)}notes(v{role.vel})")
            elif isinstance(role, PadRole):
                chords = "-".join(c for _, c in role.progression)
                parts.append(f"pad={chords}/{role.voicing}"
                             + ("[hold]" if role.hold else "") + f"(v{role.vel})")
            else:  # ControlsRole
                ramps = ",".join(f"cc{r.cc}:{r.from_val:.2f}->{r.to_val:.2f}" for r in role.ramps)
                parts.append(f"controls=[{ramps}]")
        return f"{self.bpm:g}bpm {self.key} {self.for_bars}bars | " + " ".join(parts)
