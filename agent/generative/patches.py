"""Per-genre patch registry (E-2 / issue #67) — which Surge patch each role expects.

v1 curation verified against the patch library installed on the target
machine (factory + 3rd-party bundles); `location` is the patch-browser path
(Author/Category) so a human can find it in two clicks. `character` is
written for two readers: the human doing setup, and later the mind when
patch choice becomes its decision (E-5).

The engine cannot load patches yet (that's E-5) — this registry is the
CONTRACT: the spike prints it at startup and the human matches Surge to it.
Drum entries are a stopgap: Surge is not a drum sampler; one patch pitches
all three drum notes. Good enough to monitor the groove, wrong for release
audio — a sampler instance is the real answer (tracked in E-9 territory).
"""

from __future__ import annotations

PATCH_REGISTRY: dict[str, dict[str, dict[str, str]]] = {
    "deep": {
        "bass": {"patch": "FM Bass 1", "location": "Factory / Basses",
                 "character": "clean FM sub with a round attack — sits under a 4/4 kick"},
        "pad": {"patch": "MKS-70 Warm Pad", "location": "Factory / Pads",
                "character": "warm analog-style pad, unobtrusive — deep house stab/held duty"},
        "drums": {"patch": "Drum One", "location": "Factory / Percussion",
                  "character": "stopgap synth kit — pitches kick/snare/hat notes acceptably"},
    },
    "ambient": {
        "bass": {"patch": "Deep End", "location": "Factory / Basses",
                 "character": "slow dark sub — drone duty, no attack transient"},
        "pad": {"patch": "Deep Space 1", "location": "Inigo Kennedy / Pads",
                "character": "vast evolving space pad — the sound that sold the ear test"},
    },
    "lofi": {
        "bass": {"patch": "E-Bass", "location": "Factory / Basses",
                 "character": "electric-bass-ish, soft fingered attack — lazy root lines"},
        "pad": {"patch": "Soft Suitcase", "location": "Factory / Keys",
                "character": "suitcase EP — jazzy chord loops ARE the lofi idiom"},
        "drums": {"patch": "Drum One", "location": "Factory / Percussion",
                  "character": "stopgap synth kit — see module docstring"},
    },
}

# role -> (0-indexed MIDI channel, which instance/port should receive it)
ROLE_ROUTING = {
    "bass": ("channel 1", "main instance, Scene A"),
    "pad": ("channel 2", "main instance, Scene B"),
    "drums": ("channel 10", "drum instance (second loopMIDI port)"),
    "lead": ("channel 3", "main instance (Scene B key-split, or a third port — see setup doc)"),
}


def get_patch(genre: str, role: str) -> dict[str, str] | None:
    return PATCH_REGISTRY.get(genre, {}).get(role)


def expected_setup(genre: str) -> str:
    """Human-readable setup table the spike prints at startup."""
    entries = PATCH_REGISTRY.get(genre)
    if not entries:
        return f"[setup] no patch registry for genre {genre!r}"
    lines = [f"[setup] expected Surge state for --genre {genre} "
             f"(docs/surge-multitimbral-setup.md):"]
    for role, info in entries.items():
        channel, target = ROLE_ROUTING[role]
        lines.append(f"[setup]   {role:<5} -> {info['patch']!r} ({info['location']}) "
                     f"on {channel} = {target}")
    return "\n".join(lines)
