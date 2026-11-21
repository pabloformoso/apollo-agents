"""The MCP tools. What is NOT here matters as much as what is.

The MCP signs in AS the operator, so the token it holds can publish to the
catalog and go live. Neither is exposed, and neither is deleting anything:

* **publishing** writes into ``tracks/``, which every future session draws
  from — a human decision, made in Generations with the take in their ears;
* **live sets** are public broadcasts and hold the shared GPU for hours;
* **deleting** is not reversible.

So the limit is the tool list itself: there is no code path from here to
those endpoints. Two more guards sit in front of the backend's own:

* before anything that loads ACE (``generate``, ``ace_service start``) the
  server asks whether a set is on air and refuses with a sentence that
  says why — the backend answers 409 anyway, this only says it first;
* tool results never contain a token.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .auth import AuthError, Session, TokenStore
from .client import ApolloClient, ApolloError, decoded_take_path
from .config import Config

ON_AIR = (
    "A live set is on air. ACE would take ~11 GB of the shared GPU from the live DJ, "
    "so nothing that loads ACE runs until the set ends."
)
MAX_WAIT_SEC = 1800


def _take_view(take: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": take.get("index"),
        "path": decoded_take_path(str(take.get("file") or "")),
        "metas": take.get("metas"),
        "seed": take.get("seed_value"),
        **({"state": take["state"]} if "state" in take else {}),
        **({"published_track_id": take["published_track_id"]} if take.get("published_track_id") else {}),
    }


def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    view = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "eta_seconds": task.get("eta_seconds"),
        "takes": [_take_view(t) for t in task.get("takes") or []],
    }
    if task.get("degraded"):
        view["note"] = "Apollo could not reach ACE on this poll; the task is still pending."
    if task.get("result_parse_error"):
        view["result_parse_error"] = task["result_parse_error"]
    return view


def _suffix(content_type: str, path: str) -> str:
    if "wav" in content_type:
        return ".wav"
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    return Path(path).suffix or ".audio"


def build_server(config: Config | None = None, http: httpx.AsyncClient | None = None) -> MCPServer:
    config = config or Config.from_env()
    http = http or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    session = Session(config, http, TokenStore(config.token_file))
    api = ApolloClient(config.base_url, http, session)
    mcp = MCPServer("apollo")

    async def call(coro):
        try:
            return await coro
        except AuthError as exc:
            raise ToolError(str(exc)) from exc
        except ApolloError as exc:
            raise ToolError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not reach Apollo at {config.base_url}: {exc}") from exc

    async def refuse_if_on_air() -> None:
        service = await call(api.service())
        if service.get("blocked_by_live"):
            raise ToolError(ON_AIR)

    async def find_take(task_id: str, take_index: int) -> dict[str, Any]:
        task = await call(api.task(task_id))
        for take in task.get("takes") or []:
            if take.get("index") == take_index:
                return take
        raise ToolError(
            f"Task {task_id} has no take {take_index} (status {task.get('status')!r}, "
            f"{len(task.get('takes') or [])} take(s))."
        )

    @mcp.tool()
    async def login_status() -> dict[str, Any]:
        """Whether this MCP is signed in to Apollo, and until when. Never returns the token."""
        tokens = TokenStore(config.token_file).load()
        if tokens is None:
            return {"signed_in": False, "how": "Run `apollo-mcp login` in a terminal."}
        return {
            "signed_in": tokens.apollo_valid(),
            "apollo": config.base_url,
            "expires": datetime.fromtimestamp(tokens.apollo_exp, timezone.utc).isoformat(),
            "renewable": tokens.refresh_valid(),
        }

    @mcp.tool()
    async def apollo_status() -> dict[str, Any]:
        """ACE and the live set, before doing anything else.

        Returns whether ACE is reachable and loaded, its service state, queue,
        and ``blocked_by_live`` — when true a set is on air and nothing that
        loads ACE may run.
        """
        health, service = await asyncio.gather(call(api.health()), call(api.service()))
        return {
            "ace_reachable": health.get("available"),
            "service_state": service.get("state"),
            "ace_ready": service.get("ready"),
            "model_loaded": service.get("loaded"),
            "blocked_by_live": bool(health.get("blocked_by_live") or service.get("blocked_by_live")),
            "pending_results": service.get("pending_results"),
            "queue": health.get("stats"),
            "can_manage_ace": service.get("can_manage"),
            "reason": service.get("reason"),
        }

    @mcp.tool()
    async def list_genres() -> list[dict[str, Any]]:
        """Valid ``genre_folder`` values with their BPM window, default BPM and style prompt."""
        return (await call(api.genres())).get("genres", [])

    @mcp.tool()
    async def ace_service(action: Literal["start", "stop"]) -> dict[str, Any]:
        """Start or stop the ACE-Step service on the GPU host.

        Start refuses while a live set is on air. Stop is refused by Apollo
        while a generation's results are still pending.
        """
        if action == "start":
            await refuse_if_on_air()
        return await call(api.service_action(action))

    @mcp.tool()
    async def generate(
        prompt: str,
        genre_folder: str,
        lyrics: str = "[Instrumental]",
        audio_duration: float | None = None,
        bpm: int | None = None,
        key_scale: str | None = None,
        batch_size: int = 1,
        vocal_language: str | None = None,
    ) -> dict[str, Any]:
        """Release one generation to ACE-Step. Returns the task id to poll.

        ``prompt`` is the caption: style, instruments, mood, texture. Apollo
        prefixes the genre's own style prompt. Keep tempo and key OUT of it:
        they go in ``bpm`` / ``key_scale`` (``bpm`` defaults to the centre of
        the genre's window). ``lyrics`` carries structure tags such as
        ``[Intro - ambient]``, ``[Build]``, ``[Drop]``, ``[Breakdown]``,
        ``[Outro]``; ``[Instrumental]`` for no structure. ``audio_duration``
        is seconds. Refused while a live set is on air.
        """
        await refuse_if_on_air()
        body: dict[str, Any] = {
            "prompt": prompt,
            "genre_folder": genre_folder,
            "lyrics": lyrics,
            "batch_size": batch_size,
        }
        optional = {
            "audio_duration": audio_duration,
            "bpm": bpm,
            "key_scale": key_scale,
            "vocal_language": vocal_language,
        }
        body.update({k: v for k, v in optional.items() if v is not None})
        return await call(api.create_task(body))

    @mcp.tool()
    async def get_task(task_id: str) -> dict[str, Any]:
        """One poll of a generation: status (pending/done/failed) and its takes with real metas."""
        return _task_view(await call(api.task(task_id)))

    @mcp.tool()
    async def wait_for_task(task_id: str, timeout_sec: int = 900) -> dict[str, Any]:
        """Poll a generation every 5 s until it is done or failed (or the timeout passes)."""
        deadline = time.monotonic() + min(max(timeout_sec, 5), MAX_WAIT_SEC)
        while True:
            view = _task_view(await call(api.task(task_id)))
            if view["status"] != "pending" or time.monotonic() >= deadline:
                if view["status"] == "pending":
                    view["note"] = "Still pending at the timeout; poll again with get_task."
                return view
            await asyncio.sleep(5)

    @mcp.tool()
    async def download_take(task_id: str, take_index: int = 0, dest_dir: str | None = None) -> dict[str, Any]:
        """Save a take's audio locally (through Apollo's proxy) to listen to or analyse it."""
        take = await find_take(task_id, take_index)
        file = str(take.get("file") or "")
        directory = Path(dest_dir).expanduser() if dest_dir else config.download_dir
        stem = directory / f"{task_id}__{take_index}"
        dest, size, content_type = await call(api.download(file, stem.with_suffix(".tmp")))
        final = dest.with_suffix(_suffix(content_type, decoded_take_path(file)))
        dest.replace(final)
        return {"path": str(final), "bytes": size, "content_type": content_type, "metas": take.get("metas")}

    @mcp.tool()
    async def list_generations(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """The operator's generations, newest first, with their takes and states."""
        rows = await call(api.generations(limit, offset))
        out = []
        for row in rows:
            request = row.get("request") or {}
            out.append({
                "id": row.get("id"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "genre_folder": request.get("genre_folder"),
                "prompt": request.get("user_prompt") or request.get("prompt"),
                "takes": [_take_view(t) for t in row.get("takes") or []],
            })
        return out

    @mcp.tool()
    async def mark_take(generation_id: str, take_index: int, state: Literal["discarded", "fresh"]) -> dict[str, Any]:
        """Discard a take, or restore a discarded one. Publishing is NOT available here."""
        return await call(api.set_take_state(generation_id, take_index, state))

    @mcp.tool()
    async def critique_take(task_id: str, take_index: int, genre_folder: str) -> dict[str, Any]:
        """Score a take against its genre's reference bands (CPU only) plus an LLM reading.

        Advisory: it never gates anything. ``passed`` is null when the genre
        has no references.
        """
        take = await find_take(task_id, take_index)
        metas = take.get("metas") or {}
        body = {
            "file": decoded_take_path(str(take.get("file") or "")),
            "metas": {k: metas.get(k) for k in ("bpm", "keyscale", "duration") if metas.get(k) is not None},
            "prompt": take.get("prompt"),
            "genre_folder": genre_folder,
        }
        return await call(api.critique(body))

    @mcp.tool()
    async def search_catalog(query: str | None = None, genre: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Search the published catalog by name/id substring and/or genre folder."""
        data = await call(api.catalog(genre))
        tracks = data.get("tracks") or []
        if query:
            needle = query.lower()
            tracks = [
                t for t in tracks
                if needle in str(t.get("display_name") or "").lower() or needle in str(t.get("id") or "").lower()
            ]
        keep = ("id", "display_name", "genre_folder", "bpm", "camelot_key", "duration_sec", "user_rating")
        return {
            "total": len(tracks),
            "tracks": [{k: t.get(k) for k in keep if k in t} for t in tracks[: max(1, min(limit, 500))]],
            "genres": data.get("genres"),
        }

    @mcp.tool()
    async def list_sessions() -> list[dict[str, Any]]:
        """The operator's sessions (read-only): id, name, genre, phase, track count."""
        rows = await call(api.sessions())
        keep = ("id", "session_name", "genre", "phase", "mood", "created_at", "duration_min")
        return [{**{k: s.get(k) for k in keep if k in s}, "tracks": len(s.get("playlist") or [])} for s in rows]

    return mcp
