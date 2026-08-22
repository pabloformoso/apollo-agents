"""Audit stored beatgrids for bars that disagree with their own metadata.

Found 2026-08-22 while chasing dead air on the healing stream. A beatgrid
can store ``beats_per_bar: 4`` while its ``downbeats_sec`` are spaced
exactly TWO beats apart — the metadata contradicts the data sitting next
to it.

Why it matters: the phrase-lock reasons in bars. If a "bar" is half its
nominal length, a 16-bar phrase boundary is really an 8-bar one, so the
crossfade anchors land somewhere the music does not agree with.

Scale (2026-08-22, 510 catalogued tracks):

    aural            118/179   65.9%
    Healing           17/47    36.2%
    synthware          7/86     8.1%
    lofi - ambient     5/83     6.0%
    cocktail house     2/25     8.0%
    soul jazz          1/30     3.3%
    deep house         0/60     0.0%
    TOTAL            150/510   29.4%

The gradient is the diagnosis: the rate tracks how percussive the genre
is. Deep house, with an unambiguous kick, is clean. Drone material gives
madmom nothing to anchor on and it settles into 2-beat groupings.

READ-ONLY. This reports; it does not touch tracks.json. The repair is a
musical decision, not a mechanical one — see the note at the bottom of
the output.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CATALOG = os.path.join(_ROOT, "tracks", "tracks.json")

#: A bar shorter than this many beats is treated as disagreeing with a
#: nominal 4/4. Set at 3.0 rather than just under 4 so ordinary detection
#: jitter does not get flagged: the real cases cluster hard at 2.0.
SUSPECT_BEATS_PER_BAR = 3.0

MIN_DOWNBEATS = 3


def implied_beats_per_bar(track: dict) -> float | None:
    """Beats per bar implied by the spacing of the stored downbeats.

    Uses the MEDIAN gap: a mean would be dragged by the long tail that
    appears when the detector drops a downbeat over a quiet passage.

    Returns None when there is not enough grid to judge.
    """
    grid = track.get("beatgrid") or {}
    downbeats = grid.get("downbeats_sec") or []
    bpm = track.get("bpm") or 0
    if len(downbeats) < MIN_DOWNBEATS or not bpm:
        return None
    gaps = [b - a for a, b in zip(downbeats, downbeats[1:]) if b > a]
    if not gaps:
        return None
    return statistics.median(gaps) / (60.0 / bpm)


def audit(tracks: list[dict]) -> list[dict]:
    """Return one row per track that has a judgeable, disagreeing grid."""
    rows = []
    for track in tracks:
        implied = implied_beats_per_bar(track)
        if implied is None or implied >= SUSPECT_BEATS_PER_BAR:
            continue
        grid = track.get("beatgrid") or {}
        rows.append({
            "id": track.get("id"),
            "display_name": track.get("display_name"),
            "genre_folder": track.get("genre_folder"),
            "bpm": track.get("bpm"),
            "stored_beats_per_bar": grid.get("beats_per_bar"),
            "implied_beats_per_bar": round(implied, 2),
            "source": grid.get("source"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG)
    ap.add_argument("--genre", default=None, help="Limit to one genre_folder.")
    ap.add_argument("--json", action="store_true", help="Emit rows as JSON.")
    args = ap.parse_args()

    with open(args.catalog, encoding="utf-8") as fh:
        tracks = json.load(fh)["tracks"]
    if args.genre:
        tracks = [t for t in tracks
                  if (t.get("genre_folder") or "").lower() == args.genre.lower()]

    rows = audit(tracks)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    judgeable = collections.Counter()
    flagged = collections.Counter()
    for t in tracks:
        if implied_beats_per_bar(t) is None:
            continue
        judgeable[t.get("genre_folder")] += 1
    for r in rows:
        flagged[r["genre_folder"]] += 1

    print(f"catalog: {args.catalog}")
    print(f"{'genre':<20} {'flagged':>8} {'judgeable':>10} {'rate':>7}")
    for genre, n in sorted(judgeable.items(), key=lambda kv: -flagged[kv[0]]):
        f = flagged[genre]
        print(f"{genre:<20} {f:>8} {n:>10} {100 * f / n:>6.1f}%")
    tot_f, tot_n = sum(flagged.values()), sum(judgeable.values())
    if tot_n:
        print(f"{'TOTAL':<20} {tot_f:>8} {tot_n:>10} {100 * tot_f / tot_n:>6.1f}%")

    if rows:
        print("\nflagged tracks:")
        for r in sorted(rows, key=lambda r: (r["genre_folder"] or "", r["display_name"] or "")):
            print(f"  [{r['genre_folder']}] {r['display_name']}  "
                  f"{r['bpm']} BPM  stored={r['stored_beats_per_bar']} "
                  f"implied={r['implied_beats_per_bar']}")

    print(
        "\nNOTE: re-running madmom will NOT fix these. It is deterministic on\n"
        "the same audio, so it reproduces the same grouping. Repair means\n"
        "choosing one of:\n"
        "  (a) store beats_per_bar=2 — honest metadata, but the phrase tiers\n"
        "      then count 2-beat bars and 4/4 phrasing is still lost;\n"
        "  (b) keep every other downbeat to rebuild 4-beat bars — musically\n"
        "      right IF the piece really is in 4/4, but something has to\n"
        "      decide WHICH half to keep, and picking wrong shifts every\n"
        "      phrase boundary by two beats.\n"
        "That choice is musical, not mechanical, which is why this script\n"
        "only reports."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
