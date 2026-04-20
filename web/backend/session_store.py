"""Session state — persisted to SQLite (via web.backend.db) so sessions
survive backend restarts. In-memory dict is a write-through cache."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import db


class Session:
    def __init__(self, session_id: str, user_id: int) -> None:
        self.id = session_id
        self.user_id = user_id
        # Phase tracks where we are in the 7-step pipeline
        self.phase: str = "init"
        # LLM message histories keyed by phase
        self.messages: dict[str, list[dict]] = {}
        # Shared mutable state passed through every tool call
        self.context_variables: dict = {}
        # Results from critic and validator phases
        self.critic_verdict: Optional[str] = None
        self.critic_problems: list[str] = []
        self.structured_problems: list[dict] = []
        self.validator_status: Optional[str] = None
        self.validator_issues: list[str] = []
        # Set after build_session succeeds
        self.session_name: Optional[str] = None
        self.created_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        ctx = self.context_variables
        playlist = ctx.get("playlist", [])
        safe_playlist = [
            {
                "id": t.get("id", ""),
                "display_name": t.get("display_name", ""),
                "bpm": t.get("bpm"),
                "camelot_key": t.get("camelot_key"),
                "duration_sec": t.get("duration_sec"),
                "genre": t.get("genre"),
            }
            for t in playlist
        ]
        return {
            "id": self.id,
            "user_id": self.user_id,
            "phase": self.phase,
            "genre": ctx.get("genre"),
            "duration_min": ctx.get("duration_min"),
            "mood": ctx.get("mood"),
            "playlist": safe_playlist,
            "session_name": self.session_name or ctx.get("last_build"),
            "critic_verdict": self.critic_verdict,
            "critic_problems": self.critic_problems,
            "structured_problems": self.structured_problems,
            "validator_status": self.validator_status,
            "validator_issues": self.validator_issues,
            "created_at": self.created_at,
        }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _serialize(self) -> str:
        """JSON blob holding everything `to_dict` doesn't cover — chat history,
        full context_variables, and other mutable state needed to resume.

        Private keys (leading underscore) in context_variables are stripped:
        the editor pipeline installs a `_progress` callback there during long
        tool calls and callables are not JSON-serialisable.
        """
        safe_ctx = {
            k: v for k, v in self.context_variables.items()
            if not k.startswith("_")
        }
        payload = {
            "phase": self.phase,
            "messages": self.messages,
            "context_variables": safe_ctx,
            "critic_verdict": self.critic_verdict,
            "critic_problems": self.critic_problems,
            "structured_problems": self.structured_problems,
            "validator_status": self.validator_status,
            "validator_issues": self.validator_issues,
            "session_name": self.session_name,
        }
        return json.dumps(payload, default=str)

    @classmethod
    def _from_row(cls, row: dict) -> "Session":
        s = cls(row["id"], int(row["user_id"]))
        s.created_at = row["created_at"]
        data = json.loads(row["data"])
        s.phase = data.get("phase", "init")
        s.messages = data.get("messages", {})
        s.context_variables = data.get("context_variables", {})
        s.critic_verdict = data.get("critic_verdict")
        s.critic_problems = data.get("critic_problems", [])
        s.structured_problems = data.get("structured_problems", [])
        s.validator_status = data.get("validator_status")
        s.validator_issues = data.get("validator_issues", [])
        s.session_name = data.get("session_name")
        return s


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._by_user: dict[int, list[str]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazily rehydrate the in-memory cache from SQLite on first access.

        Kept lazy (not in __init__) so tests can monkeypatch db.DB_PATH before
        the store reads from disk.
        """
        if self._loaded:
            return
        self._loaded = True
        try:
            rows = db.list_all_sessions()
        except Exception:
            # First-run before init_db, or migration in flight — start empty
            # and let init_db create the table; subsequent saves will populate.
            return
        for row in rows:
            s = Session._from_row(row)
            self._sessions[s.id] = s
            self._by_user.setdefault(s.user_id, []).append(s.id)

    def create(self, user_id: int) -> Session:
        self._ensure_loaded()
        sid = str(uuid.uuid4())
        s = Session(sid, user_id)
        self._sessions[sid] = s
        self._by_user.setdefault(user_id, []).append(sid)
        self.save(s)
        return s

    def get(self, session_id: str) -> Optional[Session]:
        self._ensure_loaded()
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: int) -> list[Session]:
        self._ensure_loaded()
        return [
            self._sessions[i]
            for i in self._by_user.get(user_id, [])
            if i in self._sessions
        ]

    def delete(self, session_id: str) -> None:
        self._ensure_loaded()
        s = self._sessions.pop(session_id, None)
        if s:
            ids = self._by_user.get(s.user_id, [])
            if session_id in ids:
                ids.remove(session_id)
        try:
            db.delete_session_row(session_id)
        except Exception:
            pass  # same best-effort semantics as save()

    def save(self, session: Session) -> None:
        """Write-through persist. Called after each WS message mutates state."""
        try:
            db.upsert_session(
                session.id, session.user_id, session.created_at, session._serialize()
            )
        except Exception:
            # Persistence is best-effort — a write failure must not crash the
            # live pipeline. The in-memory state is still the truth until the
            # next restart.
            pass

    # Test helper — resets the cache so a fresh DB can be re-loaded.
    def _reset(self) -> None:
        self._sessions.clear()
        self._by_user.clear()
        self._loaded = False


store = SessionStore()
