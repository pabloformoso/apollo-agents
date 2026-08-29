"""SQLite user store."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("APOLLO_DB_PATH") or (Path(__file__).parent / "apollo.db"))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
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
        c.commit()


def create_user(username: str, email: str, hashed_password: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, email, hashed_password) VALUES (?, ?, ?)",
            (username, email, hashed_password),
        )
        c.commit()
        user_id = cur.lastrowid
        if user_id is None:
            raise RuntimeError("INSERT returned no lastrowid")
        return user_id


def get_user_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Session persistence — chat/pipeline state survives backend restarts so the
# frontend's session ID doesn't become stale when uvicorn reloads.
# ---------------------------------------------------------------------------

def list_all_sessions() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, user_id, created_at, data FROM sessions"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_session(session_id: str, user_id: int, created_at: str, data: str) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO sessions (id, user_id, created_at, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data = excluded.data
            """,
            (session_id, user_id, created_at, data),
        )
        c.commit()


def delete_session_row(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        c.commit()


# ---------------------------------------------------------------------------
# Playlists (v2.2.1) — named track collections per user. `track_id` is the
# string id from `tracks/tracks.json`; ratings/playlists do not duplicate the
# catalog. Positions are 0-indexed and dense (compacted on remove/reorder).
# ---------------------------------------------------------------------------

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_playlist(user_id: int, name: str) -> dict:
    now = _now_iso()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO playlists (user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, name, now, now),
        )
        c.commit()
        pid = cur.lastrowid
        if pid is None:
            raise RuntimeError("INSERT returned no lastrowid")
    return {"id": pid, "user_id": user_id, "name": name, "created_at": now, "updated_at": now, "track_count": 0}


def list_playlists_by_user(user_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """
            SELECT p.id, p.user_id, p.name, p.created_at, p.updated_at,
                   COALESCE(COUNT(pt.track_id), 0) AS track_count
            FROM playlists p
            LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
            WHERE p.user_id = ?
            GROUP BY p.id
            ORDER BY p.updated_at DESC, p.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_playlist(playlist_id: int) -> dict | None:
    """Return the playlist row + ordered track_ids, or None if missing.

    Caller is responsible for hydrating `track_ids` against the catalog.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT id, user_id, name, created_at, updated_at FROM playlists WHERE id = ?",
            (playlist_id,),
        ).fetchone()
        if not row:
            return None
        track_rows = c.execute(
            "SELECT track_id, position FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
        out = dict(row)
        out["track_ids"] = [r["track_id"] for r in track_rows]
        return out


def rename_playlist(playlist_id: int, name: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?",
            (name, _now_iso(), playlist_id),
        )
        c.commit()
        return cur.rowcount > 0


def delete_playlist(playlist_id: int) -> bool:
    with _conn() as c:
        # SQLite doesn't enforce ON DELETE CASCADE without PRAGMA, so do it
        # explicitly to keep the schema portable.
        c.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        cur = c.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        c.commit()
        return cur.rowcount > 0


def _touch_playlist(c: sqlite3.Connection, playlist_id: int) -> None:
    c.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (_now_iso(), playlist_id))


def add_tracks_to_playlist(playlist_id: int, track_ids: list[str]) -> int:
    """Append `track_ids` at the end of the playlist. Duplicates are allowed.
    Returns the new total count of tracks in the playlist.

    The read-modify-write sequence is wrapped in a `BEGIN IMMEDIATE`
    transaction so concurrent appends from two clients (e.g. two open tabs
    or async callers) cannot both observe the same `MAX(position)+1` and
    then collide on the `(playlist_id, position)` PRIMARY KEY. `IMMEDIATE`
    acquires a RESERVED lock at BEGIN time, serialising writers without
    blocking readers; the second caller waits until we commit.
    """
    if not track_ids:
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM playlist_tracks WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            return row["n"] if row else 0

    c = _conn()
    # Disable sqlite3's implicit transaction management so we can issue an
    # explicit BEGIN IMMEDIATE that serialises concurrent writers.
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()
        next_pos = int(row["next_pos"]) if row else 0
        for tid in track_ids:
            c.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                (playlist_id, tid, next_pos),
            )
            next_pos += 1
        _touch_playlist(c, playlist_id)
        c.execute("COMMIT")
        return next_pos
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def remove_track_from_playlist(playlist_id: int, track_id: str) -> bool:
    """Remove the FIRST occurrence of `track_id` and compact positions.

    Returns True if a row was removed.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT position FROM playlist_tracks WHERE playlist_id = ? AND track_id = ? ORDER BY position LIMIT 1",
            (playlist_id, track_id),
        ).fetchone()
        if not row:
            return False
        pos = int(row["position"])
        c.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND position = ?",
            (playlist_id, pos),
        )
        # Re-pack positions: rewrite all rows in order with dense positions.
        rows = c.execute(
            "SELECT track_id, position FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
        c.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        for new_pos, r in enumerate(rows):
            c.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                (playlist_id, r["track_id"], new_pos),
            )
        _touch_playlist(c, playlist_id)
        c.commit()
        return True


def reorder_playlist_tracks(playlist_id: int, track_ids: list[str]) -> bool:
    """Replace the playlist's order atomically.

    `track_ids` must match the multiset of current track_ids (same elements,
    same multiplicities). Returns False if the multiset doesn't match — the
    caller should reject with 422.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
        current = sorted(r["track_id"] for r in rows)
        proposed = sorted(track_ids)
        if current != proposed:
            return False
        c.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        for pos, tid in enumerate(track_ids):
            c.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                (playlist_id, tid, pos),
            )
        _touch_playlist(c, playlist_id)
        c.commit()
        return True


# ---------------------------------------------------------------------------
# Per-user track ratings (1–5). Used by the catalog favorites filter.
# ---------------------------------------------------------------------------

def upsert_track_rating(user_id: int, track_id: str, rating: int) -> None:
    """Insert or update the rating row for (user_id, track_id)."""
    with _conn() as c:
        c.execute(
            """
            INSERT INTO track_ratings (user_id, track_id, rating, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, track_id) DO UPDATE SET
                rating     = excluded.rating,
                updated_at = excluded.updated_at
            """,
            (user_id, track_id, rating),
        )
        c.commit()


def delete_track_rating(user_id: int, track_id: str) -> None:
    """Idempotent — removing a rating that doesn't exist is not an error."""
    with _conn() as c:
        c.execute(
            "DELETE FROM track_ratings WHERE user_id = ? AND track_id = ?",
            (user_id, track_id),
        )
        c.commit()


def get_user_ratings(user_id: int) -> dict[str, int]:
    """Return {track_id: rating} for every rating the user has set."""
    with _conn() as c:
        rows = c.execute(
            "SELECT track_id, rating FROM track_ratings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {r["track_id"]: r["rating"] for r in rows}


# ---------------------------------------------------------------------------
# OAuth refresh tokens (v2.7) — Fernet-encrypted at rest. The encryption key
# is derived from JWT_SECRET by youtube_auth._fernet so we never persist a
# usable refresh token even if the DB file leaks without the env.
# Callers pass already-encrypted token strings; this module is intentionally
# crypto-agnostic so unit tests can exercise the SQL paths without pulling
# in the cryptography stack.
# ---------------------------------------------------------------------------


def save_oauth_token(
    user_id: int,
    provider: str,
    refresh_token_encrypted: str,
    *,
    access_token: str | None = None,
    expires_at: str | None = None,
    scope: str | None = None,
    channel_id: str | None = None,
    channel_title: str | None = None,
) -> None:
    """Upsert an OAuth token row. `refresh_token_encrypted` is opaque to
    this module; the caller is responsible for encryption."""
    with _conn() as c:
        c.execute(
            """
            INSERT INTO oauth_tokens
                (user_id, provider, refresh_token, access_token,
                 expires_at, scope, channel_id, channel_title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                refresh_token = excluded.refresh_token,
                access_token  = excluded.access_token,
                expires_at    = excluded.expires_at,
                scope         = excluded.scope,
                channel_id    = excluded.channel_id,
                channel_title = excluded.channel_title
            """,
            (user_id, provider, refresh_token_encrypted, access_token,
             expires_at, scope, channel_id, channel_title),
        )
        c.commit()


def get_oauth_token(user_id: int, provider: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            """
            SELECT user_id, provider, refresh_token, access_token,
                   expires_at, scope, channel_id, channel_title, connected_at
            FROM oauth_tokens
            WHERE user_id = ? AND provider = ?
            """,
            (user_id, provider),
        ).fetchone()
        return dict(row) if row else None


def update_oauth_access_token(
    user_id: int,
    provider: str,
    *,
    access_token: str | None,
    expires_at: str | None,
) -> None:
    """Refresh just the access-token cache after a successful token refresh.
    The encrypted refresh_token is left untouched."""
    with _conn() as c:
        c.execute(
            """
            UPDATE oauth_tokens
            SET access_token = ?, expires_at = ?
            WHERE user_id = ? AND provider = ?
            """,
            (access_token, expires_at, user_id, provider),
        )
        c.commit()


def delete_oauth_token(user_id: int, provider: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM oauth_tokens WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        c.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# G6 — the Generations Library (docs/acestep-wizard-plan.md §"G6 contract").
#
# Generations live only in the wizard page's state until this store: close
# the tab and the history is gone, while ACE-Step's result files sit on its
# disk forever. Every write here is a HOOK on an existing generator endpoint,
# so the page stays dumb and the record survives it.
#
# Two rules the callers depend on:
#
# * **Every mutation is user-scoped in the SQL itself**, not in the caller.
#   A poll or a publish carries a task id the browser supplied; matching on
#   ``user_id`` here is what stops one user's poll from rewriting another's
#   row. The "unknown to the store" answer (a task released before G6, or
#   someone else's) is a plain ``False``/``0``, never an exception — the
#   poll endpoint must keep answering either way.
# * **A re-poll is a no-op.** ``save_generation_takes`` upserts by
#   ``(generation_id, idx)`` and deliberately leaves ``state`` and
#   ``published_track_id`` alone, so a second done-poll of a take the user
#   already published or discarded cannot reset it to ``fresh``.
#
# JSON columns are parsed on the way out (``request``, ``metas``): the
# encoding is this module's business, and a corrupt value degrades to an
# empty object rather than breaking the feed.
# ---------------------------------------------------------------------------

#: ``generations.status`` vocabulary. ``stale`` is "ACE answered and does
#: not know this task" — distinct from a transport blip, which leaves the
#: row ``pending`` (never conflate the two: one is terminal, one is not).
GENERATION_STATUSES = ("pending", "done", "failed", "stale")

#: ``generation_takes.state``. ``published`` is reachable ONLY through a
#: successful publish (:func:`mark_take_published`), never through the
#: PATCH endpoint.
TAKE_STATES = ("fresh", "published", "discarded")

#: Feed page size guards, shared with the endpoint's query params.
DEFAULT_GENERATIONS_LIMIT = 20
MAX_GENERATIONS_LIMIT = 100


def _loads(raw: object) -> dict:
    """Parse a JSON column into a dict; anything else becomes ``{}``."""
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _take_row(row: sqlite3.Row) -> dict:
    """One stored take in the poll endpoint's vocabulary.

    ``index`` rather than ``idx``: that is what the wizard's poll response
    calls it, and the library renders through the same take components.
    """
    return {
        "index": row["idx"],
        "file": row["file"],
        "decoded_path": row["decoded_path"],
        "metas": _loads(row["metas_json"]),
        "prompt": row["prompt"],
        "lyrics": row["lyrics"],
        "seed_value": row["seed_value"],
        "state": row["state"],
        "published_track_id": row["published_track_id"],
    }


def _generation_row(row: sqlite3.Row, takes: list[dict]) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "request": _loads(row["request_json"]),
        "takes": takes,
    }


def _takes_for(
    c: sqlite3.Connection, generation_ids: list[str]
) -> dict[str, list[dict]]:
    """Takes for a page of generations in ONE query (no N+1 on the feed)."""
    if not generation_ids:
        return {}
    marks = ",".join("?" * len(generation_ids))
    rows = c.execute(
        f"""
        SELECT generation_id, idx, file, decoded_path, metas_json, prompt,
               lyrics, seed_value, state, published_track_id
        FROM generation_takes
        WHERE generation_id IN ({marks})
        ORDER BY generation_id, idx
        """,
        generation_ids,
    ).fetchall()
    out: dict[str, list[dict]] = {gid: [] for gid in generation_ids}
    for row in rows:
        out[row["generation_id"]].append(_take_row(row))
    return out


def record_generation(
    generation_id: str,
    user_id: int,
    request: dict,
    *,
    status: str = "pending",
) -> bool:
    """Insert one generation. Returns False if the id is already recorded.

    ``ON CONFLICT DO NOTHING`` rather than an upsert: the id is ACE's task
    id, so a collision means "already recorded" and the existing row —
    with its takes and its created_at — is the one worth keeping.
    """
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO generations (id, user_id, created_at, status, request_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (generation_id, user_id, _now_iso(), status, json.dumps(request)),
        )
        c.commit()
        return cur.rowcount > 0


def get_generation(generation_id: str) -> dict | None:
    """One generation with its takes, or None. Caller checks ``user_id``.

    Ownership is the caller's call here, exactly as with
    :func:`get_playlist`, so the endpoint can answer 404 for "unknown" and
    "someone else's" with one sentence.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT id, user_id, created_at, status, request_json "
            "FROM generations WHERE id = ?",
            (generation_id,),
        ).fetchone()
        if not row:
            return None
        takes = _takes_for(c, [row["id"]])
        return _generation_row(row, takes[row["id"]])


def list_generations_by_user(
    user_id: int,
    *,
    limit: int = DEFAULT_GENERATIONS_LIMIT,
    offset: int = 0,
) -> list[dict]:
    """The feed: newest first, takes embedded, one user only.

    ``rowid`` breaks ties on ``created_at``: the stamp has second
    resolution, and a batch released in the same second must still come
    back in a stable, insertion-ordered sequence.
    """
    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, user_id, created_at, status, request_json
            FROM generations
            WHERE user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, int(limit), int(offset)),
        ).fetchall()
        takes = _takes_for(c, [r["id"] for r in rows])
        return [_generation_row(r, takes.get(r["id"], [])) for r in rows]


def set_generation_status(generation_id: str, user_id: int, status: str) -> bool:
    """Move one generation to ``status``. False = unknown or not this user's."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE generations SET status = ? WHERE id = ? AND user_id = ?",
            (status, generation_id, user_id),
        )
        c.commit()
        return cur.rowcount > 0


def save_generation_takes(
    generation_id: str,
    user_id: int,
    takes: list[dict],
    *,
    status: str = "done",
) -> bool:
    """Persist a finished generation's takes + status. **Idempotent.**

    Returns False without writing anything when the id is unknown or
    belongs to another user — that is the "polling a task the store never
    saw" case, which must stay a normal poll.

    The upsert rewrites the CONTENT columns only. ``state`` and
    ``published_track_id`` are the user's, not ACE's: a second done-poll
    of a take that has since been published or discarded must not walk it
    back to ``fresh``.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE generations SET status = ? WHERE id = ? AND user_id = ?",
            (status, generation_id, user_id),
        )
        if cur.rowcount == 0:
            return False
        for take in takes:
            c.execute(
                """
                INSERT INTO generation_takes
                    (generation_id, idx, file, decoded_path, metas_json,
                     prompt, lyrics, seed_value, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'fresh')
                ON CONFLICT(generation_id, idx) DO UPDATE SET
                    file         = excluded.file,
                    decoded_path = excluded.decoded_path,
                    metas_json   = excluded.metas_json,
                    prompt       = excluded.prompt,
                    lyrics       = excluded.lyrics,
                    seed_value   = excluded.seed_value
                """,
                (
                    generation_id,
                    int(take.get("index", 0)),
                    take.get("file"),
                    take.get("decoded_path"),
                    json.dumps(take.get("metas") or {}),
                    take.get("prompt"),
                    take.get("lyrics"),
                    take.get("seed_value"),
                ),
            )
        c.commit()
        return True


def set_take_state(generation_id: str, idx: int, state: str) -> bool:
    """Set one take's ``state``. False when there is no such take.

    ``published_track_id`` is deliberately left in place: it records that
    this take WAS published as that track, which stays true after the user
    discards the row from their feed.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE generation_takes SET state = ? WHERE generation_id = ? AND idx = ?",
            (state, generation_id, idx),
        )
        c.commit()
        return cur.rowcount > 0


def mark_take_published(
    user_id: int, decoded_path: str, published_track_id: str
) -> int:
    """Mark the take at ``decoded_path`` published. Returns rows matched.

    Publish carries no task id (ACE's records expire, its files do not),
    so the take is found by the one thing both sides hold: the DECODED
    path the page persisted when the take arrived. ``0`` means "no take of
    this user's has that path" — a normal outcome for a take generated
    before G6, and the caller logs it rather than failing the publish.
    """
    with _conn() as c:
        cur = c.execute(
            """
            UPDATE generation_takes
            SET state = 'published', published_track_id = ?
            WHERE decoded_path = ?
              AND generation_id IN (SELECT id FROM generations WHERE user_id = ?)
            """,
            (published_track_id, decoded_path, user_id),
        )
        c.commit()
        return cur.rowcount
