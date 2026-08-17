"""
Per-genre catalog configuration — the single source of truth.

``main.py`` owns the pipeline that consumes these, but it imports librosa,
moviepy and friends at module scope, so anything that only needs the genre
tables (``agent/tools.py``, and through it the async render endpoint in
``web/backend/render.py``) cannot import it just to read two dicts. Both
tables therefore live here, in a module with no dependencies beyond the
standard library, and ``main.py`` re-exports them under their historic names.

Before this module existed each side kept its own copy and they drifted:
``agent/tools.py`` was missing ``cocktail house`` and ``soul jazz`` for a
release, which silently flattened the arranger's energy curve for those
genres and dropped their colors from web-rendered sessions. Add a genre
here once and every consumer sees it.
"""
from __future__ import annotations

# BPM ranges per genre folder — used for clamping auto-detected BPM in
# main.py's detect_bpm(), and for scaling the energy curve in the agent's
# playlist arranger. A genre missing from this table degrades to a wide
# fallback range, which flattens the energy curve rather than crashing.
BPM_GENRE_RANGES: dict[str, tuple[int, int]] = {
    "lofi - ambient": (60, 110),
    "lofi": (60, 110),
    "techno": (120, 160),
    "cyberpunk": (120, 160),
    "deep house": (115, 135),
    # Slower house cousin for late-night lounge / cocktail bar sets —
    # sits between lofi (60-110) and deep house (115-135) without
    # overlap on either side. Lower bound 102 catches the slower
    # nu-disco end; upper bound 126 stops short of standard club house.
    "cocktail house": (102, 126),
    # Soul / jazz — covers slow-burn ballads through up-tempo acid-jazz
    # and soul-jazz grooves. Lower bound 75 leaves room for smoky
    # late-night ballads; upper bound 140 catches the faster fusion /
    # acid-jazz end without colliding with deep house territory.
    "soul jazz": (75, 140),
    # Healing — binaural meditation drones, flute and chime beds. These
    # have no percussive transient for librosa to lock onto, so it
    # routinely reads them at 3-4x their real pulse (a 58 BPM drone
    # detected as 232). The window is deliberately exactly one octave
    # wide (50→100, a 2:1 ratio) so at most one rung of the octave
    # ladder can land inside it — a wider window would let two
    # candidates qualify and the midpoint tie-break would pick
    # arbitrarily. Without this range these tracks get tagged at techno
    # tempo and poison BPM matching for the whole set.
    "healing": (50, 100),
}

# Default themes per genre folder for smart-generated sessions.
# ``artwork_style`` must name a key in main.py's ARTWORK_PROMPTS —
# _generate_artwork() falls back to "abstract" on an unknown style, and
# that fallback is silent.
GENRE_THEMES: dict[str, dict] = {
    "lofi - ambient": {
        "artwork_style": "anime",
        "title_color": "#E8D5B7",
        "title_stroke_color": "#5C4A32",
        "bg_color": [18, 15, 12],
        "waveform_color": [180, 160, 130],
        "particle_color": [200, 180, 150],
        "bg_darken": 0.85,
        "title_font_size": 36,
    },
    "lofi": {
        "artwork_style": "anime",
        "title_color": "#E8D5B7",
        "title_stroke_color": "#5C4A32",
        "bg_color": [18, 15, 12],
        "waveform_color": [180, 160, 130],
        "particle_color": [200, 180, 150],
        "bg_darken": 0.85,
        "title_font_size": 36,
    },
    "deep house": {
        "artwork_style": "deep-house-neon",
        "title_color": "#6A5AFF",
        "title_stroke_color": "#1A0A3E",
        "bg_color": [12, 8, 28],
        "waveform_color": [106, 90, 255],
        "particle_color": [140, 120, 255],
        "bg_darken": 0.7,
        "title_font_size": 32,
    },
    "techno": {
        "artwork_style": "dark-techno",
        "title_color": "#FF1744",
        "title_stroke_color": "#4A0010",
        "bg_color": [5, 2, 8],
        "waveform_color": [255, 23, 68],
        "particle_color": [255, 50, 80],
        "bg_darken": 0.85,
        "title_font_size": 32,
    },
    "cyberpunk": {
        "artwork_style": "dark-techno",
        "title_color": "#00FF88",
        "title_stroke_color": "#004422",
        "bg_color": [8, 8, 14],
        "waveform_color": [0, 255, 136],
        "particle_color": [0, 200, 100],
        "bg_darken": 0.75,
        "title_font_size": 32,
    },
    # Cocktail house — late-night lounge / hotel-bar vibe. Warm amber
    # title on a deep burgundy backdrop, golden particles. Reuses the
    # ``deep-house-neon`` artwork preset because it's the closest
    # sibling on the existing DALL-E style list; swap to a custom
    # ``cocktail-lounge`` preset once the prompt-template work lands.
    "cocktail house": {
        "artwork_style": "deep-house-neon",
        "title_color": "#E8B86C",
        "title_stroke_color": "#3A1F1A",
        "bg_color": [22, 10, 16],
        "waveform_color": [232, 184, 108],
        "particle_color": [255, 210, 140],
        "bg_darken": 0.75,
        "title_font_size": 32,
    },
    # Soul / jazz — warm analog feel, smoky club / golden-hour vinyl.
    # Burnt-orange title on dark espresso backdrop, amber particles.
    # Reuses ``organic-zen`` artwork preset (warm painterly, earth
    # tones, golden hour) as the closest match on the existing DALL-E
    # style list.
    "soul jazz": {
        "artwork_style": "organic-zen",
        "title_color": "#D98E3B",
        "title_stroke_color": "#2A140A",
        "bg_color": [20, 12, 8],
        "waveform_color": [217, 142, 59],
        "particle_color": [240, 180, 100],
        "bg_darken": 0.8,
        "title_font_size": 32,
    },
    # Healing — binaural meditation / spa. Soft jade title over a deep
    # teal-black backdrop, pale mint particles. Gets its own
    # ``healing-aura`` artwork preset rather than borrowing
    # ``organic-zen``: that one is warm desert / golden hour, which
    # fights the cool high-key stillness this genre is going for.
    # ``bg_darken`` is high (0.85) because the artwork is deliberately
    # bright — without it the pale backdrop swallows the title.
    "healing": {
        "artwork_style": "healing-aura",
        "title_color": "#9FE0D0",
        "title_stroke_color": "#0C2A2A",
        "bg_color": [8, 18, 22],
        "waveform_color": [159, 224, 208],
        "particle_color": [200, 240, 230],
        "bg_darken": 0.85,
        "title_font_size": 32,
    },
}
