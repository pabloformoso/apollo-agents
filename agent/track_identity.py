"""Piece identity for catalog tracks — the take-aware layer (v3.10).

A "piece" is one musical composition; the catalog can hold it under
several track ids ("takes"):

- Suno downloads a generation as two takes; the second lands as
  ``<name> (1).wav`` and ``--build-catalog`` records it with
  ``variant_of=<base stem>`` and an id suffixed ``-v2``
  (see ``main._make_track_id``).
- Collision renames add bare numeric suffixes (``-2``, ``-v3``) to
  non-UUID ids (aural batch).
- Some second takes were saved by hand as ``<name> bis`` files — same
  piece, separate id AND separate display name.

The 2026-08-05 meditation session played 91 tracks with zero id-level
repeats and still delivered at least 5 audible repeats: the anti-repeat
machinery keyed on ids, and takes are different ids. This module gives
every track a set of PIECE KEYS so exclusion works at the piece level.

What is deliberately NOT collapsed: same-stem ids with different UUID
tails (e.g. the 13 ``lofi_2-quiet_pages-<uuid>`` entries). Those are
separate *generations* from one prompt — distinct compositions with
distinct curated display names — and folding them would gut catalog
variety. UUID identity is per-generation identity.

Two keys per track, matched independently (a candidate is "the same
piece" as a played track when EITHER key collides):

1. **Structural key** — from ``variant_of`` when set (slugified with
   the genre prefix, which reconstructs the base take's id by the same
   formula ``_make_track_id`` used to build it), else the id with
   take/collision suffixes stripped — but only for ids WITHOUT a UUID
   tail, per the rule above.
2. **Name key** — genre + display_name normalised (lowercase, trailing
   take markers like " bis" / " (alt)" / " (1)" stripped). Links the
   hand-saved 'x bis' pairs, whose ids/variant_of carry no link. Safe
   against the quiet_pages family because distinct generations carry
   distinct curated names.
"""
from __future__ import annotations

import re

_UUID_TAIL = re.compile(
    r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
# -v2 / -v3 … possibly chained. Deliberately NOT matching bare "-2" /
# "-9": those also appear in legit slugs ('sector-9') and synthetic
# test ids ('te-1'), and collision renames (disambiguate_collisions)
# can't be told apart from them without catalog context. The bare-"-N"
# collision pairs therefore stay unlinked structurally — the name key
# still catches them when their display names align.
_TAKE_SUFFIX = re.compile(r"(?:-v\d+)+$")
# Trailing take markers in curated display names. Deliberately NOT
# matching bare trailing digits: titles like 'Sector 9' or the E2E
# mocks' 'Track 1'/'Track 2' are distinct pieces, not takes.
_NAME_TAKE_MARKER = re.compile(
    r"(?:\s+bis|\s+\(alt\)|\s+\(1\)|\s+v\d+)$", re.IGNORECASE
)


def _slugify(text: str) -> str:
    """Mirror of main._slugify / tools._slugify (kept dependency-free)."""
    slug = text.lower()
    for ch in [" ", "/", "\\", "(", ")", ".", ","]:
        slug = slug.replace(ch, "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def piece_keys(track: dict) -> frozenset[str]:
    """The track's piece-identity keys (see module docstring).

    Always non-empty for tracks with an id; unknown/empty tracks yield
    an empty set (which never matches anything).
    """
    keys: set[str] = set()
    genre = _slugify(str(track.get("genre_folder") or track.get("genre") or ""))

    tid = str(track.get("id") or "")
    variant_of = track.get("variant_of")
    if variant_of:
        # Reconstruct the base take's id with the same formula
        # _make_track_id uses — this is what links 'x-v2' to 'x'.
        keys.add(f"struct::{genre}--{_slugify(str(variant_of))}")
    elif tid:
        if _UUID_TAIL.search(tid):
            # UUID identity is per-generation identity — never strip.
            keys.add(f"struct::{tid}")
        else:
            keys.add(f"struct::{_TAKE_SUFFIX.sub('', tid)}")

    name = str(track.get("display_name") or "").strip().lower()
    if name:
        base_name = _NAME_TAKE_MARKER.sub("", name).strip()
        if base_name:
            keys.add(f"name::{genre}::{base_name}")

    return frozenset(keys)


def piece_exclusion_set(tracks: list[dict]) -> set[str]:
    """Union of piece keys across ``tracks`` — the exclusion pool."""
    pool: set[str] = set()
    for t in tracks:
        pool |= piece_keys(t)
    return pool


def shares_piece(track: dict, exclusion: set[str]) -> bool:
    """True when ``track`` is (a take of) any piece in ``exclusion``."""
    if not exclusion:
        return False
    return bool(piece_keys(track) & exclusion)


def dedupe_takes(tracks: list[dict]) -> list[dict]:
    """Keep one take per piece, order preserved (first occurrence wins).

    Used by the planner so an initial playlist never schedules two
    takes of the same piece, and by pick_next_track so its candidate
    table never shows twins.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for t in tracks:
        keys = piece_keys(t)
        if keys & seen:
            continue
        seen |= keys
        out.append(t)
    return out
