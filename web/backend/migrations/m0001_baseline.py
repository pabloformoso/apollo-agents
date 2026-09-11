"""The schema as it stood on 2026-09-10 — the baseline every DB starts from.

This is the body of the old ``db.init_db()``, verbatim. That function was
already an idempotent migration; it simply never had a version number.
Every statement is ``CREATE ... IF NOT EXISTS`` plus one guarded ALTER, so
running it is a full create on an empty file and an exact no-op on a
database an older build already made — which is what lets an existing
install adopt the runner by doing nothing but bumping ``user_version``
from 0 to 1.

Nothing was rewritten on the way in, deliberately: a baseline that is a
tidied-up version of the old schema is a baseline that no longer matches
the databases already in the field, and the difference would surface
months later as a column that exists on new installs only. The one
change is the removed ``c.commit()`` — the runner owns the transaction
now, and a commit here would end it early and defeat the all-or-nothing
guarantee.

The SQL strings keep the indentation they had inside the old ``with
_conn() as c:`` block, which is why they sit four spaces deeper than this
function's body. That is not a formatting slip and a linter must not
"fix" it: SQLite stores the TEXT of a ``CREATE`` statement in
``sqlite_master.sql`` byte for byte, so re-indenting the literal changes
what a new database records — and a schema diff between a machine that
ran the old code and one that ran the new would light up for no reason
at all. ``test_fresh_migrate_matches_legacy_init_db`` compares those
strings and fails on a single space.

Future changes go in ``m0002_*.py`` and beyond. This file is history and
must never be edited.
"""
from __future__ import annotations

import sqlite3

from ._helpers import add_column_if_missing

VERSION = 1
NAME = "baseline"


def up(c: sqlite3.Connection) -> None:
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
    # Playlists (v2.2.1) — named track collections per user.
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
    # Track ratings (v2.2.2) — per-user 1–5 score, drives favorites filter.
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
    # v2.7 — OAuth refresh tokens for third-party providers (YouTube
    # today, room for more). Refresh tokens are Fernet-encrypted at
    # rest with a key derived from JWT_SECRET (see
    # web/backend/youtube_auth._fernet); the access_token cache is
    # also stored so we avoid a refresh round-trip when it's fresh.
    # G6 — the Generations Library. ACE-Step's job records are mortal
    # (in-memory, 24 h, gone with the process the VRAM protocol stops
    # between batches) while its result FILES are not, so this is the
    # only durable record that a generation ever happened. `id` IS the
    # ACE task_id: there is no second identity to keep in sync, and it
    # is what the poll/refresh lanes already hold.
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
    # The feed's one query: newest-first for ONE user.
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_generations_user "
        "ON generations(user_id, created_at)"
    )
    # No separate index on generation_takes(generation_id): the
    # PRIMARY KEY's own index is (generation_id, idx), whose leading
    # column already serves every lookup this table gets. A second
    # index on the same prefix would only cost writes.
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

    # v3.11 — Keycloak identity. Nullable and UNIQUE: local accounts
    # keep NULL (SQLite allows many NULLs in a UNIQUE column), while a
    # federated account is keyed by the realm's immutable ``sub``.
    # Never key on email or username — both are editable in Keycloak
    # and re-pointing a row at a different human is a whole-account
    # takeover, ratings and playlists included.
    add_column_if_missing(c, "users", "keycloak_sub", "TEXT")
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_keycloak_sub "
        "ON users(keycloak_sub) WHERE keycloak_sub IS NOT NULL"
    )
