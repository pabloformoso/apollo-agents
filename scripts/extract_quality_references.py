"""Extract quality reference ranges from the channel's own catalog (S-1 / #71).

    uv run python scripts/extract_quality_references.py --tracks-dir <main-checkout>/tracks

Deterministic: fixed name sort, first N WAVs per genre. Genre->folder map is
explicit in agent/generative/bench.py (lofi AND ambient share 'lofi - ambient').
Writes agent/generative/quality_references.json (committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.generative.bench import GENRE_FOLDERS, REFERENCES_PATH, extract_references


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tracks-dir", default="tracks")
    parser.add_argument("-n", type=int, default=5)
    parser.add_argument("--sr-limit", type=int, default=120,
                        help="analyze at most this many seconds per track")
    parser.add_argument("-o", "--out", default=str(REFERENCES_PATH))
    args = parser.parse_args()

    dirs = {genre: Path(args.tracks_dir) / folder for genre, folder in GENRE_FOLDERS.items()}
    refs = extract_references(dirs, n=args.n, sr_limit=args.sr_limit)
    if not refs:
        print(f"no WAVs found under {args.tracks_dir}")
        return 1
    Path(args.out).write_text(json.dumps(refs, indent=2) + "\n", encoding="utf-8")
    summary = ", ".join(f"{genre} ({len(ref['files'])} files)" for genre, ref in refs.items())
    print(f"wrote {args.out}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
