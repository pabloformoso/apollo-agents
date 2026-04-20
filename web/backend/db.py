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
