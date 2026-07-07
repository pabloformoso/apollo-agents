"""Genre packs (M-6): idiom in one place — starter spec + a brief for the mind.

Each pack carries:
- `brief`: prepended to the mind's system prompt so every phrase decision
  happens inside the genre's vocabulary (tempo band, role palette, density,
  feel) instead of being re-derived from scratch each call.
- `starter`: the seed spec the spike opens with, doubling as the few-shot
  example in the prompt — one spec that both *validates* and *sounds* like
  the genre.

The starters are validated by the test suite (tests import and parse them),
so an idiom drift that breaks the schema fails CI, not the live set.
"""

from __future__ import annotations

GENRE_PACKS: dict[str, dict] = {
    "deep": {
        "brief": """GENRE: deep house.
- Tempo 118-124 BPM, never leave this band. 4/4, kick on every beat.
- Palette: kick + offbeat hats always; bass syncopated, rides the root and fifth;
  pad = lush minor 7th/9th chords, retriggered (hold=false) for pump, held for breakdowns.
- Density: groove is king — change ONE element per phrase, keep the rest locked.
- Builds via hats density and CC 74 opening; breakdowns drop the kick, hold the pad.""",
        "starter": {
            "for_bars": 8,
            "bpm": 122,
            "key": "8A",
            "roles": {
                "kick": {"pattern": "4-on-floor", "vel": 110},
                "hats": {"pattern": "offbeat", "vel": 80, "swing": 0.12},
                "bass": {"notes": [[0, "A1", 1.0], [6, "A1", 0.5], [10, "E2", 0.5], [12, "G1", 1.0]], "vel": 92},
                "pad": {"chord": "Am9", "voicing": "wide", "vel": 55},
            },
            "reason": "seed groove — establish a deep 122bpm Am foundation before the mind takes over",
            "rethink_in_bars": 8,
        },
    },
    "ambient": {
        "brief": """GENRE: ambient.
- Tempo 60-75 BPM. Usually NO drums at all — omit kick/snare/hats unless a heartbeat
  pulse is explicitly wanted (then: sparse kick, vel < 70).
- Palette: held pad progressions (hold=true, ALWAYS), chord changes every 2-4 bars,
  wide voicings; bass = long drones (16-32 beats) on the tonic or fifth.
- Harmony is the melody: minor 9ths, maj7ths, sus chords. Movement comes from
  voice-led changes and slow CC 74 swells (4-8 bars), never from rhythm.
- Density: LESS. If in doubt, remove a role. Silence is material.""",
        "starter": {
            "for_bars": 8,
            "bpm": 70,
            "key": "8A",
            "roles": {
                "pad": {"progression": [[0, "Am9"], [2, "Fmaj7"], [4, "Cmaj7"], [6, "Em7"]],
                        "voicing": "wide", "hold": True, "vel": 60},
                "bass": {"notes": [[0, "A1", 32.0]], "vel": 58},
                "controls": {"ramps": [{"cc": 74, "from": 0.25, "to": 0.55, "start_bar": 0, "over_bars": 8}]},
            },
            "reason": "seed meditation — Am9 to Em7 voice-led drift over a low A drone, filter breathing open",
            "rethink_in_bars": 8,
        },
    },
    "lofi": {
        "brief": """GENRE: lofi hip-hop.
- Tempo 72-88 BPM. Head-nod, not dance: kick is sparse and lazy (never 4-on-floor),
  snare on 2 and 4, hats swung HARD (swing 0.25-0.4), low velocities throughout.
- Palette: two-to-four chord loops (hold=true), jazzy colors (m9, maj7, 7),
  bass follows the chord roots with long relaxed notes (2-4 beats).
- Imperfection is the aesthetic: velocities low and uneven, density modest.
- Evolve by swapping ONE chord or ONE drum pattern per phrase; the loop must
  stay recognizable — listeners are studying to this.""",
        "starter": {
            "for_bars": 8,
            "bpm": 78,
            "key": "8A",
            "roles": {
                "kick": {"pattern": "x......x..x.....", "vel": 96},
                "snare": {"pattern": "....x.......x...", "vel": 70},
                "hats": {"pattern": "x.x.x.x.x.x.x.x.", "swing": 0.3, "vel": 52},
                "bass": {"notes": [[0, "A1", 3.0], [12, "E2", 2.0]], "vel": 76},
                "pad": {"progression": [[0, "Am9"], [4, "Fmaj7"]], "voicing": "close", "hold": True, "vel": 58},
            },
            "feel": {"timing_slop": 0.5, "ghost_notes": 0.4},
            "reason": "seed head-nod — dusty 78bpm two-chord loop, swung hats, lazy bass",
            "rethink_in_bars": 8,
        },
    },
}


def genre_prompt_section(genre: str) -> str:
    """Brief + few-shot example for the mind's system prompt."""
    import json

    pack = GENRE_PACKS.get(genre)
    if pack is None:
        return ""
    return (
        f"\n{pack['brief']}\n\n"
        "Example of an idiomatic spec for this genre (match its register, then evolve):\n"
        f"{json.dumps(pack['starter'], ensure_ascii=False)}\n"
    )
