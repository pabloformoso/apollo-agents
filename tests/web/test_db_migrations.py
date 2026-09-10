"""The migration runner, and the connection pragmas it runs against.

The load-bearing test here is :func:`test_fresh_migrate_matches_legacy_init_db`.
``db.init_db`` is now an alias for ``migrations.migrate``, so comparing
one against the other would compare the runner with itself. Instead
:func:`_legacy_init_db` below is a frozen copy of the ``init_db`` body as
it stood at 76cae54, before the runner existed — the schema that is
actually on disk in prod and on every developer's machine. If m0001 ever
drifts from it, new installs and old ones stop agreeing, and that is the
failure this file exists to catch.
"""
from __future__ import annotations

import sqlite3

import pytest

from web.backend import db
from web.backend import migrations
from web.backend.migrations import Migration


# ---------------------------------------------------------------------------
# The pre-migration schema, frozen. DO NOT update this to match a change in
# m0001 — if the two disagree, one of them is wrong about prod.
# ---------------------------------------------------------------------------

def _legacy_init_db(path) -> None:
    """``db.init_db()`` exactly as it was before the runner (76cae54)."""
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    with c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                username         TEXT    UNIQUE NOT NULL,
                email            TEXT    UNIQUE NOT NULL,
                hashed_password  TEXT    NOT NULL,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT    NOT NULL,
                data       TEXT    NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                name       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_playlists_user ON playlists(user_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id INTEGER NOT NULL,
                track_id    TEXT    NOT NULL,
                position    INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, position),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS track_ratings (
                user_id    INTEGER NOT NULL,
                track_id   TEXT    NOT NULL,
                rating     INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                updated_at TEXT    NOT NULL,
                PRIMARY KEY (user_id, track_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id           TEXT    PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                created_at   TEXT    NOT NULL,
                status       TEXT    NOT NULL,
                request_json TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_generations_user "
            "ON generations(user_id, created_at)"
        )
        c.execute("""
            CREATE TABLE IF NOT EXISTS generation_takes (
                generation_id      TEXT    NOT NULL,
                idx                INTEGER NOT NULL,
                file               TEXT,
                decoded_path       TEXT,
                metas_json         TEXT,
                prompt             TEXT,
                lyrics             TEXT,
                seed_value         TEXT,
                state              TEXT    NOT NULL DEFAULT 'fresh',
                published_track_id TEXT,
                PRIMARY KEY (generation_id, idx),
                FOREIGN KEY (generation_id) REFERENCES generations(id)
                    ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id       INTEGER NOT NULL,
                provider      TEXT    NOT NULL,
                refresh_token TEXT    NOT NULL,
                access_token  TEXT,
                expires_at    TEXT,
                scope         TEXT,
                channel_id    TEXT,
                channel_title TEXT,
                connected_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, provider),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        c.commit()

        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "keycloak_sub" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN keycloak_sub TEXT")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_keycloak_sub "
            "ON users(keycloak_sub) WHERE keycloak_sub IS NOT NULL"
        )
    c.close()


def _schema_dump(path) -> list[tuple]:
    """Every object in the database, name-ordered, definition included."""
    c = sqlite3.connect(str(path))
    try:
        return c.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    finally:
        c.close()


def _user_version(path) -> int:
    c = sqlite3.connect(str(path))
    try:
        return int(c.execute("PRAGMA user_version").fetchone()[0])
    finally:
        c.close()


def _migrate_file(path, **kwargs) -> int:
    c = sqlite3.connect(str(path))
    try:
        return migrations.migrate(c, **kwargs)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# (a) fresh file: the runner reproduces the pre-runner schema exactly
# ---------------------------------------------------------------------------

def test_fresh_migrate_matches_legacy_init_db(tmp_path):
    legacy = tmp_path / "legacy.db"
    migrated = tmp_path / "migrated.db"

    _legacy_init_db(legacy)
    _migrate_file(migrated)

    assert _schema_dump(migrated) == _schema_dump(legacy)


def test_fresh_migrate_lands_on_the_latest_version(tmp_path):
    path = tmp_path / "fresh.db"
    assert _migrate_file(path) == migrations.latest_version()
    assert _user_version(path) == migrations.latest_version()


# ---------------------------------------------------------------------------
# (b) an existing production database adopts the runner by doing nothing
#     but bumping the counter
# ---------------------------------------------------------------------------

def test_existing_db_only_gains_a_version(tmp_path):
    path = tmp_path / "existing.db"
    _legacy_init_db(path)
    before = _schema_dump(path)
    assert _user_version(path) == 0

    _migrate_file(path)

    assert _schema_dump(path) == before
    assert _user_version(path) == migrations.latest_version()


def test_existing_db_keeps_its_rows(tmp_path):
    """The counter bump must not be a data migration by accident."""
    path = tmp_path / "existing.db"
    _legacy_init_db(path)
    c = sqlite3.connect(str(path))
    c.execute(
        "INSERT INTO users (username, email, hashed_password) VALUES (?, ?, ?)",
        ("alice", "a@t.io", "h"),
    )
    c.commit()
    c.close()

    _migrate_file(path)

    c = sqlite3.connect(str(path))
    rows = c.execute("SELECT username, email FROM users").fetchall()
    c.close()
    assert rows == [("alice", "a@t.io")]


# ---------------------------------------------------------------------------
# (c) idempotence
# ---------------------------------------------------------------------------

def test_migrate_twice_is_a_no_op(tmp_path):
    path = tmp_path / "twice.db"
    _migrate_file(path)
    after_first = _schema_dump(path)
    version = _user_version(path)

    assert _migrate_file(path) == version
    assert _schema_dump(path) == after_first
    assert _user_version(path) == version


def test_up_to_date_run_never_takes_the_write_lock(tmp_path):
    """The common case — every boot after the first — must not write.

    A run that opened a transaction on a current database would serialise
    every backend restart behind whatever else holds the write lock, for
    no schema change at all. The holder takes RESERVED (``BEGIN
    IMMEDIATE``), which is what blocks another writer; with
    ``busy_timeout = 0`` a runner that tried to ``BEGIN IMMEDIATE`` here
    would raise "database is locked" rather than wait.
    """
    path = tmp_path / "locked.db"
    _migrate_file(path)

    holder = sqlite3.connect(str(path))
    holder.isolation_level = None
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("CREATE TABLE holder_wrote_this (x TEXT)")
    try:
        c = sqlite3.connect(str(path))
        c.execute("PRAGMA busy_timeout = 0")
        try:
            assert migrations.migrate(c) == migrations.latest_version()
        finally:
            c.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_no_backup_is_written_for_a_fresh_database(tmp_path):
    """A first install has nothing to restore; it should not litter."""
    path = tmp_path / "fresh.db"
    _migrate_file(path)
    assert list(tmp_path.glob("*.bak")) == []


def test_backup_is_written_before_an_existing_db_is_touched(tmp_path):
    path = tmp_path / "existing.db"
    _legacy_init_db(path)
    c = sqlite3.connect(str(path))
    c.execute(
        "INSERT INTO users (username, email, hashed_password) VALUES (?, ?, ?)",
        ("alice", "a@t.io", "h"),
    )
    c.commit()
    c.close()

    _migrate_file(path)

    backups = list(tmp_path.glob("existing.db.*.bak"))
    assert len(backups) == 1
    # The snapshot must be a usable database, not a truncated copy: it is
    # the only rollback path, since there is no down().
    snap = sqlite3.connect(str(backups[0]))
    try:
        assert snap.execute("SELECT username FROM users").fetchall() == [("alice",)]
        assert int(snap.execute("PRAGMA user_version").fetchone()[0]) == 0
    finally:
        snap.close()


# ---------------------------------------------------------------------------
# (d) a failing migration is a no-op, DDL included
# ---------------------------------------------------------------------------

def _fake(version, sql=None, raises=False):
    def up(c):
        if sql:
            c.execute(sql)
        if raises:
            raise RuntimeError(f"m{version:04d} blew up")

    return Migration(version, f"fake{version}", up)


def test_a_raising_migration_rolls_back_everything(tmp_path):
    path = tmp_path / "boom.db"
    _migrate_file(path)
    before = _schema_dump(path)
    version = _user_version(path)

    plan = [
        *migrations.load_migrations(),
        _fake(version + 1, "CREATE TABLE never_committed (x TEXT)"),
        _fake(version + 2, "CREATE TABLE also_never (x TEXT)", raises=True),
    ]
    with pytest.raises(RuntimeError, match="blew up"):
        _migrate_file(path, backup=False, migrations=plan)

    assert _user_version(path) == version
    assert _schema_dump(path) == before


def test_a_raising_migration_rolls_back_data_too(tmp_path):
    """DDL and DML are in the same transaction — both or neither."""
    path = tmp_path / "boom_data.db"
    _migrate_file(path)
    version = _user_version(path)

    def up(c):
        c.execute(
            "INSERT INTO users (username, email, hashed_password) "
            "VALUES ('ghost', 'g@t.io', 'h')"
        )
        raise RuntimeError("blew up after writing")

    plan = [*migrations.load_migrations(), Migration(version + 1, "ghost", up)]
    with pytest.raises(RuntimeError, match="blew up"):
        _migrate_file(path, backup=False, migrations=plan)

    c = sqlite3.connect(str(path))
    try:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    finally:
        c.close()
    assert _user_version(path) == version


def test_migrations_run_in_order_and_stop_at_the_version_reached(tmp_path):
    path = tmp_path / "ordered.db"
    _migrate_file(path)
    version = _user_version(path)

    order: list[int] = []

    def make(v):
        def up(c):
            order.append(v)
            c.execute(f"CREATE TABLE step_{v} (x TEXT)")

        return Migration(v, f"step{v}", up)

    plan = [*migrations.load_migrations(), make(version + 1), make(version + 2)]
    assert _migrate_file(path, backup=False, migrations=plan) == version + 2
    assert order == [version + 1, version + 2]

    # A second run re-applies nothing: `CREATE TABLE` without IF NOT
    # EXISTS would raise if it did.
    order.clear()
    assert _migrate_file(path, backup=False, migrations=plan) == version + 2
    assert order == []


# ---------------------------------------------------------------------------
# (e) the guard against two branches both claiming m0007
# ---------------------------------------------------------------------------

def test_versions_are_unique_and_contiguous_from_one():
    versions = [m.version for m in migrations.load_migrations()]
    assert versions, "no migrations discovered — the package did not load"
    assert versions == list(range(1, len(versions) + 1))


def test_every_migration_has_a_distinct_name():
    names = [m.name for m in migrations.load_migrations()]
    assert len(set(names)) == len(names)


def test_filename_number_matches_declared_version():
    import importlib
    import pkgutil
    from pathlib import Path as _Path

    pkg_dir = _Path(migrations.__file__).parent
    seen = 0
    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        match = migrations._MODULE_RE.match(mod_info.name)
        if not match:
            continue
        module = importlib.import_module(f"{migrations.__name__}.{mod_info.name}")
        assert module.VERSION == int(match.group(1)), mod_info.name
        seen += 1
    assert seen == len(migrations.load_migrations())


def test_a_duplicate_version_is_refused(monkeypatch, tmp_path):
    """Simulate the bad merge: two modules, same number."""
    import importlib

    real = importlib.import_module

    dup = tmp_path / "m0001_duplicate.py"
    dup.write_text(
        "VERSION = 1\nNAME = 'duplicate'\ndef up(c):\n    pass\n",
        encoding="utf-8",
    )

    class _FakeInfo:
        def __init__(self, name):
            self.name = name

    pkg_dir = str(__import__("pathlib").Path(migrations.__file__).parent)

    def fake_iter_modules(paths):
        assert paths == [pkg_dir]
        return [_FakeInfo("m0001_baseline"), _FakeInfo("m0001_duplicate")]

    def fake_import(name, *a, **kw):
        if name.endswith("m0001_duplicate"):
            spec = importlib.util.spec_from_file_location(name, dup)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        return real(name, *a, **kw)

    monkeypatch.setattr(migrations.pkgutil, "iter_modules", fake_iter_modules)
    monkeypatch.setattr(migrations.importlib, "import_module", fake_import)

    with pytest.raises(RuntimeError, match="unique and contiguous"):
        migrations.load_migrations()


def test_baseline_is_version_one():
    first = migrations.load_migrations()[0]
    assert (first.version, first.name) == (1, "baseline")


# ---------------------------------------------------------------------------
# (f) connection hardening
# ---------------------------------------------------------------------------

def test_conn_is_wal_with_a_busy_timeout(tmp_db):
    c = db._conn()
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS
    finally:
        c.close()


def test_foreign_keys_stay_off(tmp_db):
    """Not an oversight — see the comment in ``db._conn``.

    Six tables declare a foreign key and none is enforced;
    ``delete_playlist`` removes children by hand because of it. Turning
    enforcement on is a behaviour change and belongs in its own PR.
    """
    c = db._conn()
    try:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        c.close()


def test_readers_are_not_blocked_by_a_writer(tmp_db):
    """The point of WAL, stated as behaviour.

    The writer's transaction is deliberately big enough to spill the page
    cache, which is what forces a rollback-journal writer to take an
    EXCLUSIVE lock and lock readers out. Both readers run with
    ``busy_timeout = 0``, so if WAL were off they would raise "database
    is locked" instead of merely waiting.
    """
    db.init_db()

    writer = db._conn()
    writer.isolation_level = None
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT INTO users (username, email, hashed_password) "
        "VALUES ('w', 'w@t.io', 'h')"
    )
    payload = "x" * 4096
    for i in range(1500):  # ~6 MB, well past the default 2 MB page cache
        writer.execute(
            "INSERT INTO sessions (id, user_id, created_at, data) "
            "VALUES (?, 1, '2026-01-01', ?)",
            (f"s{i}", payload),
        )
    try:
        for _ in range(2):
            reader = sqlite3.connect(str(tmp_db))
            reader.execute("PRAGMA busy_timeout = 0")
            try:
                # Proceeds, and sees the pre-transaction snapshot — the
                # writer has not committed.
                assert reader.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                assert reader.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()[0] == 0
            finally:
                reader.close()
        writer.execute("COMMIT")
    finally:
        writer.close()

    after = db._conn()
    try:
        assert after.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        after.close()


# ---------------------------------------------------------------------------
# The 12-step rebuild utility — nothing uses it yet, so this is its only
# proof that it works the day someone needs it.
# ---------------------------------------------------------------------------

def test_rebuild_table_relaxes_a_not_null_and_keeps_rows_and_indexes(tmp_path):
    path = tmp_path / "rebuild.db"
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    c.execute("CREATE INDEX idx_t_name ON t(name)")
    c.execute("INSERT INTO t (id, name) VALUES (1, 'a'), (2, 'b')")
    c.commit()

    migrations.rebuild_table(
        c,
        "t",
        "id INTEGER PRIMARY KEY, name TEXT",
        copy=["id", "name"],
    )
    c.commit()

    assert c.execute("SELECT id, name FROM t ORDER BY id").fetchall() == [
        (1, "a"),
        (2, "b"),
    ]
    # The relaxed constraint actually took effect...
    c.execute("INSERT INTO t (id, name) VALUES (3, NULL)")
    # ...and the index survived the drop/rename.
    idx = c.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 't'"
    ).fetchall()
    assert ("idx_t_name",) in idx
    assert not any(
        row[0].endswith("__migrating")
        for row in c.execute("SELECT name FROM sqlite_master")
    )
    c.close()


def test_rebuild_table_can_backfill_while_copying(tmp_path):
    path = tmp_path / "backfill.db"
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    c.execute("INSERT INTO t (id, name) VALUES (1, 'a'), (2, NULL)")
    c.commit()

    migrations.rebuild_table(
        c,
        "t",
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL",
        copy={"id": "id", "name": "COALESCE(name, 'unknown')"},
    )
    c.commit()

    assert c.execute("SELECT id, name FROM t ORDER BY id").fetchall() == [
        (1, "a"),
        (2, "unknown"),
    ]
    c.close()


def test_rebuild_table_refuses_when_foreign_keys_are_on(tmp_path):
    path = tmp_path / "fk.db"
    c = sqlite3.connect(str(path))
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    c.commit()
    with pytest.raises(RuntimeError, match="foreign_keys OFF"):
        migrations.rebuild_table(c, "t", "id INTEGER PRIMARY KEY", copy=["id"])
    c.close()


def test_add_column_if_missing_is_idempotent(tmp_path):
    path = tmp_path / "addcol.db"
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    migrations.add_column_if_missing(c, "t", "nickname", "TEXT")
    migrations.add_column_if_missing(c, "t", "nickname", "TEXT")
    cols = [r[1] for r in c.execute("PRAGMA table_info(t)")]
    assert cols == ["id", "nickname"]
    c.close()


def test_db_still_exposes_the_old_private_helper():
    """``_add_column_if_missing`` kept working for one release."""
    assert db._add_column_if_missing is migrations.add_column_if_missing


def test_backup_path_puts_the_stamp_before_dot_bak():
    """Same convention as ``main.py._catalog_backup_path``; .gitignore
    matches ``web/backend/apollo.db.*.bak`` and nothing else."""
    assert migrations.backup_path(
        "/x/apollo.db", stamp="20260910-120000"
    ) == "/x/apollo.db.20260910-120000.bak"
