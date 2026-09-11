"""Schema-editing helpers a migration's ``up()`` can call.

They live here rather than in ``db.py`` so a migration never has to import
the module whose schema it is changing. ``db`` imports this package, not
the other way round.

Every helper takes the connection the runner is already holding — it is
inside ``BEGIN IMMEDIATE``, so a helper must never ``BEGIN``, ``COMMIT``,
or issue a PRAGMA that SQLite refuses inside a transaction
(``foreign_keys``, ``journal_mode``), and must never ``VACUUM``.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence


def add_column_if_missing(
    c: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    """Idempotent ``ALTER TABLE ... ADD COLUMN``.

    Adding a nullable column is still the common case and ALTER is still
    the right tool for it — what changed in 2026-09-10 is that this is no
    longer the *mechanism*. Before the migration runner existed, every
    boot re-ran every ALTER and the ``PRAGMA table_info`` check was the
    only thing making that safe. Now a migration runs once, and the check
    is a belt-and-braces guard for the one case the version counter
    cannot see: a column an operator added by hand.

    SQLite's ``ADD COLUMN`` cannot add a NOT NULL column without a
    non-NULL default, and cannot add a UNIQUE or PRIMARY KEY column at
    all. For those, and for anything that removes or relaxes a
    constraint, use :func:`rebuild_table`.
    """
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def rebuild_table(
    c: sqlite3.Connection,
    table: str,
    new_schema: str,
    *,
    copy: Sequence[str] | Mapping[str, str],
) -> None:
    """SQLite's 12-step table rebuild: create new, copy, drop, rename.

    This is the *only* way to change a column's type, drop a constraint,
    relax a NOT NULL, or re-order columns — SQLite's ALTER TABLE does
    none of those. ``KEYCLOAK_PASSWORD_SENTINEL`` in ``db.py`` exists
    solely because ``users.hashed_password NOT NULL`` could not be
    relaxed when there was nowhere to put a rebuild; this is that
    somewhere. Nothing calls it yet, and that is fine — a mechanism with
    no home is exactly how the sentinel happened.

    ``new_schema`` is the body of the new ``CREATE TABLE`` (everything
    between the parentheses). ``copy`` names the columns to carry over:
    a sequence copies them straight across, a mapping copies
    ``{destination: source expression}`` so a rebuild can backfill
    (``{"hashed_password": "COALESCE(hashed_password, '')"}``).

    Indexes and triggers attached to ``table`` are captured before the
    drop and re-created verbatim after the rename, so a rebuild does not
    silently cost the table its indexes. Views that name the table are
    NOT touched — SQLite leaves them dangling and a migration that
    changes a viewed column has to drop and re-create the view itself.
    Nothing in this schema uses views today.

    Order matters: DROP comes before RENAME. Since SQLite 3.25,
    ``ALTER TABLE ... RENAME TO`` rewrites references to the renamed
    table in triggers and views, so renaming the new table into place
    while the old one still exists would edit the very definitions we
    are about to re-create. The SQLite docs call this out under "Making
    Other Kinds Of Table Schema Changes"; this follows their sequence.
    """
    if c.execute("PRAGMA foreign_keys").fetchone()[0]:
        # Step 1 of the documented procedure is `PRAGMA foreign_keys=OFF`,
        # and a PRAGMA cannot do that from inside the runner's
        # transaction — it is a silent no-op there. Apollo never turns
        # them on (see `db._conn`), so this only fires if that changes.
        raise RuntimeError(
            f"rebuild_table({table!r}) needs foreign_keys OFF; it cannot be "
            "turned off inside a transaction, so the caller must do it "
            "before the migration runs"
        )

    tmp = f"{table}__migrating"
    # sql IS NULL for auto-indexes (those SQLite creates for UNIQUE and
    # non-INTEGER PRIMARY KEY); they come back with the new CREATE TABLE.
    recreate = [
        row[0]
        for row in c.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE tbl_name = ? AND type IN ('index', 'trigger') "
            "AND sql IS NOT NULL ORDER BY name",
            (table,),
        )
    ]

    if isinstance(copy, Mapping):
        dest = list(copy)
        source = [copy[d] for d in dest]
    else:
        dest = list(copy)
        source = list(copy)

    c.execute(f"CREATE TABLE {tmp} ({new_schema})")
    if dest:
        c.execute(
            f"INSERT INTO {tmp} ({', '.join(dest)}) "
            f"SELECT {', '.join(source)} FROM {table}"
        )
    c.execute(f"DROP TABLE {table}")
    c.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
    for stmt in recreate:
        c.execute(stmt)
