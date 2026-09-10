"""Versioned schema migrations for the Apollo SQLite database.

Until 2026-09-10 the schema was ``CREATE TABLE IF NOT EXISTS`` all the way
down plus one idempotent ALTER, re-run on every boot. That expresses
exactly one kind of change — "add a thing that was not there" — and
nothing else: no backfill, no data reshape, and above all no constraint
change, because SQLite's ALTER TABLE cannot drop or relax one.
``db.KEYCLOAK_PASSWORD_SENTINEL`` is what that limit looks like when it
bites; its own comment says so.

Writing a migration
-------------------

Add ``mNNNN_short_name.py`` next to this file::

    VERSION = 7
    NAME = "short_name"

    def up(c):
        c.execute("ALTER TABLE users ADD COLUMN nickname TEXT")

``NNNN`` in the filename must equal ``VERSION``, versions must be unique
and contiguous from 1, and :func:`load_migrations` refuses to run if they
are not — that check is the guard against two branches both claiming
``m0007``, which is how hand-rolled runners usually fail. It runs on
every boot, so a bad merge fails at startup rather than halfway through a
migration.

``up()`` is handed the connection the runner already holds, INSIDE its
transaction. It must not ``BEGIN``, ``COMMIT``, ``VACUUM``, or set a
PRAGMA that SQLite ignores inside a transaction (``foreign_keys``,
``journal_mode``). Use :func:`add_column_if_missing` and
:func:`rebuild_table` from ``._helpers`` for the two shapes that need
care.

Design
------

**The counter is ``PRAGMA user_version``, not a table.** A
``schema_migrations`` table would itself need a migration to come into
existence — the bootstrap problem the counter does not have. It is a
4-byte field in the database header, so it cannot be half-written, and
reading it needs no schema at all.

**The whole run is one transaction.** SQLite's DDL is transactional, so a
crash or a raise anywhere in the run leaves both the DDL and the version
counter exactly as they were; there is no half-migrated state to
diagnose at 3am. ``BEGIN IMMEDIATE`` takes the write lock up front, so
two backends booting at once cannot both decide they are the one
migrating — the same pattern, for the same reason, as
``db.add_tracks_to_playlist``.

**There is no ``down()``.** For a single-operator SQLite app the rollback
is the file: :func:`migrate` writes ``<name>.<stamp>.bak`` before it
touches anything, mirroring the convention ``main.py``'s
``_catalog_backup_path`` already uses for ``tracks.json``. A ``down()``
nobody has ever executed is untested code, and the day it is needed is
the worst possible day to find out it was wrong.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable, NamedTuple

from ._helpers import add_column_if_missing, rebuild_table

__all__ = [
    "Migration",
    "add_column_if_missing",
    "backup_path",
    "current_version",
    "latest_version",
    "load_migrations",
    "migrate",
    "rebuild_table",
]

#: ``m0001_baseline`` — the number is the VERSION, and it is checked.
_MODULE_RE = re.compile(r"^m(\d{4})_[a-z0-9_]+$")


class Migration(NamedTuple):
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def load_migrations() -> list[Migration]:
    """Every migration module in this package, ordered, validated.

    Discovery is by directory scan rather than a hand-kept list: adding a
    migration should be one file, not one file plus a registration line
    somebody forgets. The validation below is what buys that safety.
    """
    found: list[Migration] = []
    for mod_info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        match = _MODULE_RE.match(mod_info.name)
        if not match:
            continue
        module = importlib.import_module(f"{__name__}.{mod_info.name}")
        for attr in ("VERSION", "NAME", "up"):
            if not hasattr(module, attr):
                raise RuntimeError(
                    f"migration {mod_info.name} is missing {attr!r}"
                )
        version = int(module.VERSION)
        if version != int(match.group(1)):
            raise RuntimeError(
                f"migration {mod_info.name} declares VERSION={version}; the "
                f"filename says {int(match.group(1))}. They must agree — the "
                "filename is what a reviewer sorts by."
            )
        found.append(Migration(version, str(module.NAME), module.up))

    found.sort(key=lambda m: m.version)
    expected = list(range(1, len(found) + 1))
    actual = [m.version for m in found]
    if actual != expected:
        raise RuntimeError(
            "migration VERSIONs must be unique and contiguous from 1; found "
            f"{actual}. Two branches claiming the same number is the usual "
            "cause — renumber the later one rather than skipping."
        )
    return found


def latest_version() -> int:
    """The version a fully migrated database is at."""
    return len(load_migrations())


def current_version(c: sqlite3.Connection) -> int:
    return int(c.execute("PRAGMA user_version").fetchone()[0])


def backup_path(db_path: str, *, stamp: str | None = None) -> str:
    """``<name>.<stamp>.bak`` — the stamp goes BEFORE ``.bak``.

    Same shape and same reason as ``main.py._catalog_backup_path``:
    ``.gitignore`` carries the convention, and a backup named the other
    way round sits in ``git status`` as untracked noise forever.
    """
    return f"{db_path}.{stamp or time.strftime('%Y%m%d-%H%M%S')}.bak"


def _main_db_file(c: sqlite3.Connection) -> str:
    """The file behind the ``main`` schema, or ``''`` for in-memory."""
    for row in c.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2] or ""
    return ""


def _has_content(c: sqlite3.Connection) -> bool:
    """Is there anything in here worth backing up?"""
    row = c.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchone()
    return int(row[0]) > 0


def _backup(c: sqlite3.Connection) -> str | None:
    """Snapshot the database file before migrating. Returns the path.

    Uses SQLite's online backup API rather than copying the file: with
    WAL on (``db._conn`` turns it on) the committed truth is spread
    across ``apollo.db`` and ``apollo.db-wal``, so a plain ``cp`` of the
    first one alone can hand you a database missing its most recent
    commits. ``Connection.backup`` writes one self-contained file that
    can simply be moved back into place.

    Skipped for an in-memory database and for one with no tables yet —
    there is nothing to restore, and a fresh install should not litter.
    """
    path = _main_db_file(c)
    if not path or not _has_content(c):
        return None
    dest_path = backup_path(path)
    dest = sqlite3.connect(dest_path)
    try:
        c.backup(dest)
    finally:
        dest.close()
    return dest_path


def migrate(
    c: sqlite3.Connection,
    *,
    backup: bool = True,
    migrations: list[Migration] | None = None,
) -> int:
    """Bring ``c`` up to the latest schema version. Returns that version.

    A no-op — no backup, no write, no lock — when the database is already
    current, which is every boot after the first.

    ``backup=False`` is for callers that already hold a snapshot (and for
    tests); ``migrations`` overrides discovery, which only tests should
    need.
    """
    plan = load_migrations() if migrations is None else list(migrations)
    target = max((m.version for m in plan), default=0)
    version = current_version(c)
    if version >= target:
        return version

    # Outside the lock on purpose: SQLite's backup API restarts itself if
    # the source connection writes mid-copy, so snapshotting from inside
    # our own write transaction is asking for trouble. The cost is that
    # the loser of a two-process race writes a .bak it turns out not to
    # need — a spare copy of an unchanged database, which is the harmless
    # side of that trade.
    if backup:
        _backup(c)

    # Explicit transaction control: sqlite3's implicit handling would open
    # a DEFERRED transaction on the first write, which takes the write
    # lock too late to stop a second process from starting its own run.
    previous_isolation = c.isolation_level
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        # Re-read under the lock. The loser of a two-process race gets
        # here after the winner has committed, and must not re-run
        # anything: `IF NOT EXISTS` would survive it, a backfill would not.
        version = current_version(c)
        for migration in plan:
            if migration.version <= version:
                continue
            migration.up(c)
            # PRAGMA takes no bound parameters, hence the f-string; the
            # value is an int from our own module, never user input.
            c.execute(f"PRAGMA user_version = {int(migration.version)}")
            version = migration.version
        c.execute("COMMIT")
    except Exception:
        # `BEGIN IMMEDIATE` itself can fail (busy_timeout expired against
        # another process's run). Rolling back with no transaction open
        # raises, and would replace the real error with a confusing one.
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.isolation_level = previous_isolation
    return version
