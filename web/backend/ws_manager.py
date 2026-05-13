"""WebSocket connection manager — one connection per active session.

v2.5.1 added a ``channel`` parameter so a single ``session_id`` can host two
independent connections at once: the planning channel (``"planning"``,
default — used by ``/ws/sessions/{id}``) and the live channel (``"live"`` —
used by ``/ws/live/{id}``). Connections in different channels are
addressed by the ``(session_id, channel)`` tuple internally; the public
API stays positional/string-id-keyed for the planning path and accepts an
optional ``channel`` kwarg for the live path.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import WebSocket


class WSManager:
    def __init__(self) -> None:
        # Keyed on (session_id, channel) so the planning + live websockets
        # can coexist on the same session id without overwriting each other.
        self._connections: dict[tuple[str, str], WebSocket] = {}

    @staticmethod
    def _key(session_id: str, channel: str) -> tuple[str, str]:
        return (session_id, channel)

    async def connect(
        self, session_id: str, ws: WebSocket, channel: str = "planning"
    ) -> None:
        await ws.accept()
        self._connections[self._key(session_id, channel)] = ws

    def disconnect(self, session_id: str, channel: str = "planning") -> None:
        self._connections.pop(self._key(session_id, channel), None)

    async def send(
        self, session_id: str, data: dict, channel: str = "planning"
    ) -> None:
        ws = self._connections.get(self._key(session_id, channel))
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(session_id, channel)

    async def receive(
        self, session_id: str, channel: str = "planning"
    ) -> Optional[dict]:
        ws = self._connections.get(self._key(session_id, channel))
        if not ws:
            return None
        try:
            text = await ws.receive_text()
            return json.loads(text)
        except Exception:
            return None

    def is_connected(self, session_id: str, channel: str = "planning") -> bool:
        return self._key(session_id, channel) in self._connections

    async def displace_existing(
        self,
        session_id: str,
        code: int,
        reason: str,
        channel: str = "planning",
    ) -> bool:
        """Close any existing WS on this ``(session_id, channel)`` slot.

        Used by the live handler (v2.7.2) so a refresh or "I opened a
        second tab" scenario takes over the slot cleanly instead of
        silently overwriting the dict entry and leaving the previous
        handler reading from a socket that's been replaced under it
        (the failure mode that motivated viewer-mode in the first place).

        Returns ``True`` if a connection was displaced, ``False`` if the
        slot was already empty. The caller's next ``connect`` registers
        the replacement; the displaced handler's ``await
        ws_manager.receive(...)`` returns ``None`` on the now-closed
        socket and exits cleanly through its ``finally`` block.

        The frontend distinguishes a displacement from a generic
        disconnect via the close ``code`` and surfaces an honest message
        ("Live session moved to another window") instead of the
        misleading "Reconnecting..." banner.
        """
        key = self._key(session_id, channel)
        existing = self._connections.get(key)
        if existing is None:
            return False
        try:
            await existing.close(code=code, reason=reason)
        except Exception:
            # Already closing / closed; that's fine — the old handler
            # will still see ``receive_text()`` raise and exit.
            pass
        # Pop before the new connect() call so a same-tick race between
        # the displaced handler's finally and our caller's connect()
        # can't accidentally re-clear the new entry.
        self._connections.pop(key, None)
        return True


ws_manager = WSManager()
