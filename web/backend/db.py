"""SQLite user store."""
from __future__ import annotations

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
    Returns the new total count of tracks in the playlist."""
    if not track_ids:
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM playlist_tracks WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            return row["n"] if row else 0

    with _conn() as c:
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
        c.commit()
        return next_pos


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
