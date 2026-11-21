"""A thin async client over the slice of Apollo's API the MCP uses.

Every method maps to one endpoint and returns its JSON unchanged. Refusals
are raised as :class:`ApolloError` carrying the backend's ``detail``
VERBATIM — the 409 VRAM message, an ingest refusal or a 403 are sentences
the operator acts on, and paraphrasing them forks the wording (the rule
web/CLAUDE.md applies to the wizard holds here too).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from .auth import Session


class ApolloError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Apollo answered {status}: {detail}")
        self.status = status
        self.detail = detail


def decoded_take_path(file: str) -> str:
    """The take's ACE path, decoded ONCE — the page's ``decodedTakePath``.

    A take's ``file`` is either a bare path or ``/v1/audio?path=<quoted>``
    with the path quoted ``safe=""``. ``unquote`` and never ``parse_qs``:
    the latter turns a ``+`` in a filename into a space.
    """
    marker = "path="
    if "?" in file and marker in file.split("?", 1)[1]:
        query = file.split("?", 1)[1]
        for part in query.split("&"):
            if part.startswith(marker):
                return unquote(part[len(marker):])
    return file


class ApolloClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient, session: Session):
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.session = session

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One request; on a 401 the token is renewed and the request sent once more."""
        for attempt in (0, 1):
            token = await self.session.token(force_refresh=attempt == 1)
            resp = await self.http.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
            if resp.status_code != 401:
                return resp
        return resp

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = await self._send(method, path, **kwargs)
        if resp.status_code >= 400:
            raise ApolloError(resp.status_code, _detail(resp))
        return resp.json()

    # --- status ------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        return await self._json("GET", "/api/generator/health")

    async def service(self) -> dict[str, Any]:
        return await self._json("GET", "/api/generator/service")

    async def service_action(self, action: str) -> dict[str, Any]:
        return await self._json("POST", f"/api/generator/service/{action}")

    async def genres(self) -> dict[str, Any]:
        return await self._json("GET", "/api/generator/genres")

    # --- generation --------------------------------------------------------
    async def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._json("POST", "/api/generator/tasks", json=body)

    async def task(self, task_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/api/generator/tasks/{task_id}")

    async def generations(self, limit: int, offset: int) -> list[dict[str, Any]]:
        return await self._json(
            "GET", "/api/generator/generations", params={"limit": limit, "offset": offset}
        )

    async def set_take_state(self, generation_id: str, index: int, state: str) -> dict[str, Any]:
        return await self._json(
            "PATCH",
            f"/api/generator/generations/{generation_id}/takes/{index}",
            json={"state": state},
        )

    async def critique(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._json("POST", "/api/generator/critique", json=body)

    async def download(self, file: str, dest: Path) -> tuple[Path, int, str]:
        """Stream a take through Apollo's audio proxy into ``dest``.

        ``path`` is the take's ``file`` UNREWRITTEN — the proxy's contract.
        Written to a ``.part`` first so an interrupted download never
        leaves a truncated file under the final name.
        """
        token = await self.session.token()
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        async with self.http.stream(
            "GET",
            self.base_url + "/api/generator/audio",
            params={"path": file},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise ApolloError(resp.status_code, _detail(resp))
            content_type = resp.headers.get("content-type", "")
            size = 0
            with part.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
                    size += len(chunk)
        part.replace(dest)
        return dest, size, content_type

    # --- library -----------------------------------------------------------
    async def catalog(self, genre: str | None) -> dict[str, Any]:
        params = {"genre": genre} if genre else None
        return await self._json("GET", "/api/catalog", params=params)

    async def sessions(self) -> list[dict[str, Any]]:
        return await self._json("GET", "/api/sessions")


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:500] or resp.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and all(isinstance(e, dict) and "msg" in e for e in detail):
        # FastAPI's 422: one "field: message" per error, the field without
        # the "body" prefix, so the agent can fix the argument it sent.
        return "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', []) if p != 'body')}: {e['msg']}" for e in detail
        )
    return str(detail if detail is not None else body)[:500]
