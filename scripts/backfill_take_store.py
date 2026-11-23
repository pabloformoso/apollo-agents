"""Copy every recorded take that Apollo has no copy of into its take store.

Takes generated before the take store existed live only in ACE's tmp
directory, so they could not be played, scored or published while ACE
was stopped. This copies them, straight from ACE's disk — run it ON THE
GPU HOST (jarvis), from the main checkout, as the user that owns the
repo:

    python3 scripts/backfill_take_store.py --dry-run
    python3 scripts/backfill_take_store.py

Idempotent: a take already in the store is skipped, so it is also the
repair for a take whose copy failed at generation time (the backend logs
``take store — could not copy``). Reads ``apollo.db`` read-only and
writes nothing but the store. Standard library only — no venv needed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from web.backend import take_store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "web" / "backend" / "apollo.db"))
    ap.add_argument("--dry-run", action="store_true", help="say what would be copied, copy nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT DISTINCT decoded_path FROM generation_takes WHERE decoded_path IS NOT NULL"
    ).fetchall()
    conn.close()

    copied = present = missing = unnamed = 0
    copied_bytes = 0
    for (decoded,) in rows:
        if take_store.name_for(decoded) is None:
            unnamed += 1
            print(f"skip (not a take file name): {decoded}")
            continue
        if take_store.local_copy(decoded) is not None:
            present += 1
            continue
        source = Path(decoded)
        if not source.is_file():
            missing += 1
            print(f"missing on ACE's disk: {decoded}")
            continue
        size = source.stat().st_size
        if args.dry_run:
            print(f"would copy {source.name} ({size / 1e6:.1f} MB)")
        else:
            part = take_store.staging_path(decoded)
            shutil.copyfile(source, part)
            os.replace(part, take_store.stored_path(decoded))
        copied += 1
        copied_bytes += size

    verb = "would copy" if args.dry_run else "copied"
    print(
        f"\n{verb} {copied} ({copied_bytes / 1e9:.2f} GB) · already stored {present} · "
        f"missing {missing} · unusable name {unnamed} → {take_store.takes_dir()}"
    )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
