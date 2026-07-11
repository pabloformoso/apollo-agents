"""Section arc (v3.2 S-4 / issue #73): sessions with a shape.

Slow-plane only — the instant control layer never sees this. An ArcSpec is
an ordered list of sections with phrase counts and energy/density targets;
ArcState tracks where the session is and injects "you are in <section>,
energy target X" into the musical state each phrase.

Validation follows the house rule (FS3 reject-and-hold): a malformed arc —
including a bad revision proposed by the mind — raises SpecError and the
caller keeps the previous arc.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .spec import SpecError

SECTION_PHRASES_MAX = 64


@dataclass(frozen=True)
class Section:
    name: str
    phrases: int
    energy_target: float
    density_target: float

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        if not isinstance(d, dict):
            raise SpecError(f"arc section must be an object, got {d!r}")
        name = d.get("name", "")
        if not isinstance(name, str) or not name.strip():
            raise SpecError("arc section needs a non-empty name")
        phrases = d.get("phrases")
        if not isinstance(phrases, int) or isinstance(phrases, bool) \
                or not 1 <= phrases <= SECTION_PHRASES_MAX:
            raise SpecError(f"{name}: phrases must be an int in [1, {SECTION_PHRASES_MAX}], got {phrases!r}")
        targets = {}
        for key in ("energy_target", "density_target"):
            v = d.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0:
                raise SpecError(f"{name}: {key} must be in [0.0, 1.0], got {v!r}")
            targets[key] = float(v)
        return cls(name=name.strip(), phrases=phrases, **targets)


@dataclass(frozen=True)
class ArcSpec:
    sections: tuple[Section, ...]

    @classmethod
    def from_dict(cls, d) -> "ArcSpec":
        if isinstance(d, dict):
            d = d.get("sections")
        if not isinstance(d, list) or not d:
            raise SpecError("arc must be a non-empty list of sections")
        return cls(sections=tuple(Section.from_dict(s) for s in d))

    @property
    def total_phrases(self) -> int:
        return sum(s.phrases for s in self.sections)


class ArcState:
    """Position tracking + reject-and-hold revision."""

    def __init__(self, arc: ArcSpec):
        self.arc = arc
        self.phrase_index = 0

    def current(self) -> Section:
        i = self.phrase_index % self.arc.total_phrases  # arcs loop (24/7 streams)
        for section in self.arc.sections:
            if i < section.phrases:
                return section
            i -= section.phrases
        return self.arc.sections[-1]  # unreachable, defensive

    def section_position(self) -> tuple[int, int]:
        """(phrase within section 1-based, section length)."""
        i = self.phrase_index % self.arc.total_phrases
        for section in self.arc.sections:
            if i < section.phrases:
                return i + 1, section.phrases
            i -= section.phrases
        return 1, self.arc.sections[-1].phrases

    def advance(self) -> None:
        self.phrase_index += 1

    def revise(self, raw) -> None:
        """Replace the arc from a raw dict/list. SpecError -> hold the old arc."""
        new_arc = ArcSpec.from_dict(raw)  # raises SpecError; caller holds
        self.arc = new_arc
        self.phrase_index = 0

    def describe(self) -> dict:
        section = self.current()
        pos, length = self.section_position()
        return {
            "section": section.name,
            "section_phrase": f"{pos}/{length}",
            "energy_target": section.energy_target,
            "density_target": section.density_target,
            "arc": " -> ".join(s.name for s in self.arc.sections),
        }


def apply_arc_to_spec(spec_dict: dict, section: Section) -> dict:
    """Map the section targets onto a spec (pure dict transform).

    density_target -> the S-3 density dial on every drum role (pattern is
    the skeleton, density dresses it). energy_target -> velocity scaling on
    EVERY role that has one: energy is how hard the whole mix plays, not
    just how many notes the drums have — without this a sustained pad
    drowns the density signal in the RMS energy proxy.
    Used by --no-llm arc-following and the S-4 correlation test.
    """
    from .spec import DRUM_ROLES

    vel_scale = 0.4 + 0.7 * section.energy_target  # 0.4x quiet .. 1.1x pushing
    out = {**spec_dict, "roles": {k: dict(v) for k, v in spec_dict["roles"].items()}}
    for name, role in out["roles"].items():
        if name in DRUM_ROLES:
            role["density"] = section.density_target
        if "vel" in role:
            role["vel"] = max(1, min(127, int(round(role["vel"] * vel_scale))))
    return out
