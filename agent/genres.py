"""One definition per genre — the single source of truth.

A genre used to live in SIX places across three files: ``BPM_GENRE_RANGES``
and ``GENRE_THEMES`` in both ``main.py`` and ``agent/tools.py``,
``GENRE_STYLE_PROMPTS`` in ``agent/tools.py``, and ``GENRE_NEIGHBOURS`` in
``agent/live_engine.py``. Adding one meant six edits, and five of the six
failures were SILENT:

* no BPM window → the raw detection is stored verbatim, which poisons tempo
  matching for every set that touches the genre
* no theme → artwork falls back to ``abstract`` without a word
* no style prompt → ACE generates off-genre and the take cannot be promoted
* no neighbours → an endless set cannot widen out of it

Only the theme mirror had a parity test, and it caught a real drift on
2026-09-08 — which is the argument for this module rather than against it.

**Why the defaults live in code and not only in the database.** A BPM window
is not user data, it is a decision with consequences: get it wrong and the
whole catalog's tempo matching degrades. It belongs in git history, reviewable
in a PR. And it has to keep working for ``python main.py --build-catalog``,
which runs standalone in Docker with madmom and knows nothing about the web
app's SQLite — worktrees and CI have no database at all.

**Why the database layer exists anyway.** Apollo is meant to be deployable at
home for someone's own music, which means adding a genre has to be possible
from the catalog UI rather than by editing Python. Those additions are that
installation's data, so they live in SQLite and are merged over these
defaults at load time.

The layering matters in one specific way: a default corrected here reaches
every installation on the next update. Seeding the database instead would
freeze today's values into every install forever, and a wrong BPM window
would never get fixed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

#: Shipped genres. Each entry is complete by construction — the test suite
#: refuses a partial one, because a partial genre is exactly the silent
#: failure this module exists to prevent.
#:
#: ``bpm``: one octave wide (``hi == 2 * lo``) wherever the material is slow
#: or beatless; librosa reads drones and pads at 2-4x their real pulse, and
#: the window drives the octave ladder that corrects it. Older entries
#: predate that rule and are left as they are — changing a window silently
#: re-tags a catalog.
#:
#: ``neighbours``: which genres may stand in when a set has exhausted its
#: own. Declared, never inferred from tempo — a soul jazz entry stored at
#: 165 BPM matched a 164 BPM synthware track and put techno on a live
#: meditation broadcast (2026-09-07). Written symmetrically; the test suite
#: enforces it.
GENRE_DEFAULTS: dict[str, dict[str, Any]] = {
    "aural": {
        "bpm": (48, 96),
        "theme": {
            "artwork_style": 'abstract',
            "title_color": '#8FD8F0',
            "title_stroke_color": '#07202C',
            "bg_color": [6, 16, 26],
            "waveform_color": [143, 216, 240],
            "particle_color": [190, 232, 248],
            "bg_darken": 0.8,
        },
        "style_prompt": (
            'ethereal beatless ambient: weightless evolving pads, submarine '
            'and cosmic textures, very long reverb, no drums, dark and '
            'spacious with slow swells'
        ),
        "neighbours": frozenset(['chillout', 'healing', 'lofi - ambient']),
    },
    "chillout": {
        "bpm": (60, 120),
        "theme": {
            "artwork_style": 'organic-zen',
            "title_color": '#DCE7E3',
            "title_stroke_color": '#2F4440',
            "bg_color": [14, 20, 19],
            "waveform_color": [150, 190, 180],
            "particle_color": [180, 215, 205],
            "bg_darken": 0.85,
            "title_font_size": 36,
        },
        "style_prompt": (
            'downtempo chillout: relaxed broken beat, mellow synth pads, soft '
            'bass, airy and melodic'
        ),
        "neighbours": frozenset(['aural', 'cocktail house', 'healing', 'lofi - ambient', 'soul jazz']),
    },
    "cocktail house": {
        "bpm": (102, 126),
        "theme": {
            "artwork_style": 'deep-house-neon',
            "title_color": '#E8B86C',
            "title_stroke_color": '#3A1F1A',
            "bg_color": [22, 10, 16],
            "waveform_color": [232, 184, 108],
            "particle_color": [255, 210, 140],
            "bg_darken": 0.75,
            "title_font_size": 32,
        },
        "style_prompt": (
            'cocktail lounge house: laid-back nu-disco groove, brushed '
            'percussion, warm Rhodes and muted guitar, sophisticated and '
            'unhurried'
        ),
        "neighbours": frozenset(['chillout', 'deep house', 'soul jazz']),
    },
    "cyberpunk": {
        "bpm": (120, 160),
        "theme": {
            "artwork_style": 'dark-techno',
            "title_color": '#00FF88',
            "title_stroke_color": '#004422',
            "bg_color": [8, 8, 14],
            "waveform_color": [0, 255, 136],
            "particle_color": [0, 200, 100],
            "bg_darken": 0.75,
            "title_font_size": 32,
        },
        "style_prompt": (
            'cyberpunk electronic: gritty synth arpeggios, distorted bass, '
            'industrial percussion, neon-noir and menacing'
        ),
        "neighbours": frozenset(['synthware', 'techno']),
    },
    "deep house": {
        "bpm": (115, 135),
        "theme": {
            "artwork_style": 'deep-house-neon',
            "title_color": '#6A5AFF',
            "title_stroke_color": '#1A0A3E',
            "bg_color": [12, 8, 28],
            "waveform_color": [106, 90, 255],
            "particle_color": [140, 120, 255],
            "bg_darken": 0.7,
            "title_font_size": 32,
        },
        "style_prompt": (
            'deep house: rolling four-on-the-floor kick, warm sub bass, '
            'smooth pad chords, subtle percussion, hypnotic late-night groove'
        ),
        "neighbours": frozenset(['cocktail house', 'synthware', 'techno']),
    },
    "healing": {
        "bpm": (50, 100),
        "theme": {
            "artwork_style": 'healing-aura',
            "title_color": '#9FE0D0',
            "title_stroke_color": '#0C2A2A',
            "bg_color": [8, 18, 22],
            "waveform_color": [159, 224, 208],
            "particle_color": [200, 240, 230],
            "bg_darken": 0.85,
            "video_bg_darken": 0.45,
            "title_font_size": 32,
        },
        "style_prompt": (
            'healing meditation music: slow binaural drones, breathy flutes '
            'and soft chimes, long reverb tails, no percussion, deeply calm '
            'and spacious'
        ),
        "neighbours": frozenset(['aural', 'chillout', 'lofi - ambient']),
    },
    "lofi": {
        "bpm": (60, 110),
        "theme": {
            "artwork_style": 'anime',
            "title_color": '#E8D5B7',
            "title_stroke_color": '#5C4A32',
            "bg_color": [18, 15, 12],
            "waveform_color": [180, 160, 130],
            "particle_color": [200, 180, 150],
            "bg_darken": 0.85,
            "title_font_size": 36,
        },
        "style_prompt": (
            'lo-fi ambient: warm tape saturation, soft dusty drums, mellow '
            'jazz-tinged chords, gentle vinyl crackle, unhurried and hazy'
        ),
        "neighbours": frozenset(),
    },
    "lofi - ambient": {
        "bpm": (60, 110),
        "theme": {
            "artwork_style": 'anime',
            "title_color": '#E8D5B7',
            "title_stroke_color": '#5C4A32',
            "bg_color": [18, 15, 12],
            "waveform_color": [180, 160, 130],
            "particle_color": [200, 180, 150],
            "bg_darken": 0.85,
            "title_font_size": 36,
        },
        "style_prompt": (
            'lo-fi ambient: warm tape saturation, soft dusty drums, mellow '
            'jazz-tinged chords, gentle vinyl crackle, unhurried and hazy'
        ),
        "neighbours": frozenset(['aural', 'chillout', 'healing']),
    },
    "soul jazz": {
        "bpm": (75, 140),
        "theme": {
            "artwork_style": 'organic-zen',
            "title_color": '#D98E3B',
            "title_stroke_color": '#2A140A',
            "bg_color": [20, 12, 8],
            "waveform_color": [217, 142, 59],
            "particle_color": [240, 180, 100],
            "bg_darken": 0.8,
            "title_font_size": 32,
        },
        "style_prompt": (
            'soul jazz: live drums with brushes, upright bass walking lines, '
            'Rhodes and Hammond organ, muted trumpet or sax, smoky and warm'
        ),
        "neighbours": frozenset(['chillout', 'cocktail house']),
    },
    "synthware": {
        "bpm": (85, 170),
        "theme": {
            "artwork_style": 'dark-techno',
            "title_color": '#F45BD0',
            "title_stroke_color": '#1A0322',
            "bg_color": [18, 4, 24],
            "waveform_color": [244, 91, 208],
            "particle_color": [120, 240, 232],
            "bg_darken": 0.4,
        },
        "style_prompt": (
            'retro synth electro: analog synth leads, acid bassline, crisp '
            'electro drums, glitch artefacts and tape hiss, neon and driving'
        ),
        "neighbours": frozenset(['cyberpunk', 'deep house', 'techno']),
    },
    "techno": {
        "bpm": (120, 160),
        "theme": {
            "artwork_style": 'dark-techno',
            "title_color": '#FF1744',
            "title_stroke_color": '#4A0010',
            "bg_color": [5, 2, 8],
            "waveform_color": [255, 23, 68],
            "particle_color": [255, 50, 80],
            "bg_darken": 0.85,
            "title_font_size": 32,
        },
        "style_prompt": (
            'techno: driving four-on-the-floor kick, hypnotic sequenced '
            'synths, industrial textures, relentless and dark'
        ),
        "neighbours": frozenset(['cyberpunk', 'deep house', 'synthware']),
    },
}


# ---------------------------------------------------------------------------
# Layer 2 — genres added by this installation
# ---------------------------------------------------------------------------

#: Set by the web layer at import time to a callable returning the same
#: shape as ``GENRE_DEFAULTS``.
#:
#: A callable rather than an import because the dependency only runs one
#: way: ``main.py`` and ``agent/`` must keep working with no database at
#: all. ``python main.py --build-catalog`` runs standalone in Docker, and
#: worktrees and CI have no ``apollo.db`` — so this stays ``None`` there and
#: the defaults are the whole answer.
_db_loader: Callable[[], dict[str, dict[str, Any]]] | None = None


def register_loader(loader: Callable[[], dict[str, dict[str, Any]]] | None) -> None:
    """Install (or clear) the source of installation-added genres."""
    global _db_loader
    _db_loader = loader


def all_genres() -> dict[str, dict[str, Any]]:
    """Defaults with this installation's additions merged over them.

    Merged per FIELD, not per genre: an installation that only overrides a
    BPM window keeps the shipped theme and style prompt. Replacing whole
    entries would mean the UI had to re-supply everything to change one
    number, and a half-filled override is the silent-failure case again.

    A loader that raises is ignored, deliberately loudly in the log but not
    fatally: a broken database must not take the CLI down with it, since the
    defaults alone are a working configuration.
    """
    merged: dict[str, dict[str, Any]] = {g: dict(d) for g, d in GENRE_DEFAULTS.items()}
    if _db_loader is None:
        return merged
    try:
        added = _db_loader()
    except Exception as exc:  # noqa: BLE001 — see docstring
        print(f"[genres] installation genres unavailable, using defaults: {exc}", flush=True)
        return merged
    for name, entry in (added or {}).items():
        key = (name or "").strip().lower()
        if not key:
            continue
        base = merged.get(key, {})
        merged[key] = {**base, **{k: v for k, v in entry.items() if v is not None}}
    return merged


# ---------------------------------------------------------------------------
# Views — the shapes the rest of the codebase already speaks
# ---------------------------------------------------------------------------
#
# Each returns a fresh dict, so a caller mutating what it got cannot
# reach back into the definitions. The old module-level constants derive
# from these, which is what keeps 40-odd call sites unchanged.


def bpm_ranges() -> dict[str, tuple[int, int]]:
    return {
        g: tuple(d["bpm"])  # type: ignore[misc]
        for g, d in all_genres().items()
        if d.get("bpm")
    }


def themes() -> dict[str, dict[str, Any]]:
    return {
        g: dict(d["theme"]) for g, d in all_genres().items() if d.get("theme")
    }


def style_prompts() -> dict[str, str]:
    return {
        g: d["style_prompt"]
        for g, d in all_genres().items()
        if d.get("style_prompt")
    }


def neighbours() -> dict[str, frozenset[str]]:
    """Adjacency, with any asymmetry an installation introduced repaired.

    A UI that adds "my ambient" as a neighbour of healing cannot be
    expected to also edit healing. Left one-way, widening would work in one
    direction only — a set anchored on healing could reach the new genre
    while one anchored there could never come back, which is exactly the
    one-way door that put techno on a meditation stream.
    """
    out: dict[str, set[str]] = {
        g: set(d.get("neighbours") or ()) for g, d in all_genres().items()
    }
    for genre, ns in list(out.items()):
        for n in ns:
            out.setdefault(n, set()).add(genre)
    return {g: frozenset(ns) for g, ns in out.items() if ns}


def is_defined(genre: str) -> bool:
    """Whether ``genre`` has a COMPLETE definition.

    Complete means all four fields. A partial one is the failure this
    module exists to prevent, so callers can screen for it instead of
    discovering it as off-genre audio or missing artwork.
    """
    d = all_genres().get((genre or "").strip().lower())
    if not d:
        return False
    return all(d.get(k) for k in ("bpm", "theme", "style_prompt", "neighbours"))


def missing_fields(genre: str) -> list[str]:
    """Which of the four fields ``genre`` lacks. Empty means complete."""
    d = all_genres().get((genre or "").strip().lower())
    if not d:
        return ["bpm", "theme", "style_prompt", "neighbours"]
    return [k for k in ("bpm", "theme", "style_prompt", "neighbours") if not d.get(k)]


# ---------------------------------------------------------------------------
# Live views of the four legacy names
# ---------------------------------------------------------------------------


class _LiveMapping(Mapping):
    """A read-only dict-alike that resolves from the definitions on access.

    This is what lets ``BPM_GENRE_RANGES`` and friends keep their names and
    their ~40 call sites while gaining two properties they did not have:
    one definition behind all of them, and visibility of a genre this
    installation added after the process started. A constant built at import
    time would need a restart to see a genre added from the catalog UI —
    which is the whole feature.

    Read-only on purpose. These used to be plain dicts, so a caller could
    have mutated one and silently reconfigured the process; ``Mapping``
    turns that into a TypeError at the point of the mistake.

    Recomputed per access rather than cached. There are eleven entries and a
    handful of dict merges, against a catalog build that spends a minute per
    track — and a cache would need invalidating from the UI, which is a
    staleness bug waiting for the day someone adds a genre and it does not
    appear.
    """

    __slots__ = ("_producer", "_label")

    def __init__(self, producer: Callable[[], dict], label: str) -> None:
        self._producer = producer
        self._label = label

    def __getitem__(self, key):
        return self._producer()[key]

    def __iter__(self):
        return iter(self._producer())

    def __len__(self) -> int:
        return len(self._producer())

    def __repr__(self) -> str:
        return f"<{self._label} {dict(self._producer())!r}>"


BPM_RANGES = _LiveMapping(bpm_ranges, "BPM_RANGES")
THEMES = _LiveMapping(themes, "THEMES")
STYLE_PROMPTS = _LiveMapping(style_prompts, "STYLE_PROMPTS")
NEIGHBOURS = _LiveMapping(neighbours, "NEIGHBOURS")
