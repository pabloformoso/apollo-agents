"""
Async streaming pipeline bridge.

Wraps the 7 agent phases from agent/run.py as async functions that emit
WebSocket events instead of printing to stdout. Imports system prompts,
schema builders, and tool functions directly from the existing agent code.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Callable

# Make the project root importable
_PROJECT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_DIR))

# ---------------------------------------------------------------------------
# Import system prompts, parsers, and schema helpers from existing agent code
# ---------------------------------------------------------------------------
from agent.run import (  # noqa: E402
    _GENRE_GUARD_SYSTEM,
    _PLANNER_SYSTEM,
    _CRITIC_SYSTEM,
    _EDITOR_SYSTEM,
    _VALIDATOR_SYSTEM,
    _parse_confirmed_block,
    _parse_critic_response,
    _parse_validator_response,
    _build_anthropic_schemas,
    _build_openai_schemas,
    _run_tool,
    enforce_mentioned_genre,
    genre_guard_system,
    parse_textual_tool_call,
)

# ---------------------------------------------------------------------------
# Import tool functions used in each phase
# ---------------------------------------------------------------------------
from agent.tools import (  # noqa: E402
    list_genres,
    get_catalog,
    propose_playlist,
    show_playlist,
    analyze_transition,
    get_energy_arc,
    swap_track,
    move_track,
    suggest_bridge_track,
    insert_bridge_track,
    build_session,
    validate_audio,
    read_memory,
    write_session_record,
    get_user_playlists,
    get_playlist_tracks,
    get_user_ratings,
    get_favorite_tracks,
)

# ---------------------------------------------------------------------------
# Provider / model — mirror agent/run.py detection
# ---------------------------------------------------------------------------
_PROVIDER_ENV = os.getenv("AGENT_PROVIDER", "")
_HAS_ANTHROPIC = bool(os.getenv("ANTHROPIC_API_KEY"))
_HAS_AZURE = bool(os.getenv("AZURE_OPENAI_API_KEY"))

if _PROVIDER_ENV == "anthropic" or (_HAS_ANTHROPIC and not _PROVIDER_ENV):
    _PROVIDER = "anthropic"
elif _PROVIDER_ENV == "azure" or (_HAS_AZURE and not _PROVIDER_ENV):
    _PROVIDER = "azure"
elif _PROVIDER_ENV == "ollama":
    _PROVIDER = "ollama"
else:
    _PROVIDER = "anthropic"

_DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-6",
    "azure": os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
    "ollama": "gemma4:4b",
}
_MODEL = os.getenv("AGENT_MODEL", _DEFAULT_MODELS.get(_PROVIDER, "claude-opus-4-6"))

# ---------------------------------------------------------------------------
# Phase tool lists (web-safe: no local playback tools)
# ---------------------------------------------------------------------------
_GENRE_TOOLS = [list_genres, get_catalog]
_PLANNER_TOOLS = [
    get_catalog,
    propose_playlist,
    get_energy_arc,
    show_playlist,
    get_user_playlists,
    get_playlist_tracks,
    get_user_ratings,
    get_favorite_tracks,
]
_CRITIC_TOOLS = [
    show_playlist, analyze_transition, get_energy_arc,
    get_user_playlists, get_playlist_tracks, get_user_ratings, get_favorite_tracks,
]
_WEB_EDITOR_TOOLS = [
    show_playlist, analyze_transition, swap_track, move_track,
    suggest_bridge_track, insert_bridge_track, build_session,
    get_user_playlists, get_playlist_tracks, get_user_ratings, get_favorite_tracks,
]
_VALIDATOR_TOOLS = [validate_audio]


# ---------------------------------------------------------------------------
# Catalog state check — surfaced to the UI before any LLM call so an empty
# or missing catalog produces an actionable error instead of a vague
# "could not confirm genre" failure from the Genre Guard loop.
# ---------------------------------------------------------------------------

class CatalogUnavailable(Exception):
    """Raised when tracks.json is missing or has zero entries."""


def check_catalog(genre: str | None = None) -> None:
    """Raise CatalogUnavailable with a user-facing message if the catalog is unusable.

    When `genre` is given, also verify that the catalog contains at least one track
    for that genre (folder name match, case-insensitive).
    """
    catalog_path = _PROJECT_DIR / "tracks" / "tracks.json"
    if not catalog_path.exists():
        raise CatalogUnavailable(
            "No track catalog found. Add WAV files under tracks/<genre>/ and run "
            "`python main.py --build-catalog` to generate tracks.json."
        )
    try:
        import json
        with catalog_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise CatalogUnavailable(f"tracks.json is unreadable: {exc}") from exc

    entries = data.get("tracks") if isinstance(data, dict) else data
    if not entries:
        raise CatalogUnavailable(
            "Track catalog is empty. Add WAV files under tracks/<genre>/ and run "
            "`python main.py --build-catalog`."
        )

    if genre:
        target = genre.strip().lower()
        matches = [
            t for t in entries
            if (t.get("genre_folder") or t.get("genre") or "").strip().lower() == target
        ]
        if not matches:
            available = sorted({
                (t.get("genre_folder") or t.get("genre") or "").strip()
                for t in entries
                if (t.get("genre_folder") or t.get("genre"))
            })
            raise CatalogUnavailable(
                f"No tracks found for genre '{genre}'. Available genres: "
                f"{', '.join(available) if available else '(none)'}."
            )


# ---------------------------------------------------------------------------
# Catalog cache
#
# Hydrating GET /api/playlists/{id} requires turning a list of track ids into
# the matching Track dicts. Without caching, every request re-reads
# tracks/tracks.json (~534 KB) and re-builds the by-id index. The cache key
# is (mtime, size) of the file: if `python main.py --build-catalog` rewrites
# the catalog while the backend is up, the next call notices the changed
# stat tuple and rebuilds. Note: builders that mutate the file in place
# without changing its size and within the same mtime tick (rare on real
# filesystems, ~1s resolution on FAT/HFS) would not be detected; on Windows
# NTFS and ext4 the mtime nanosecond precision plus the size component make
# that practically impossible.
# ---------------------------------------------------------------------------

_CATALOG_CACHE: dict | None = None


def _read_catalog_from_disk() -> dict:
    """(Re)read tracks.json and build the cache payload.

    Returns a dict with the cache key plus precomputed lookup structures so
    every call after the first is O(1) for `get_track_by_id` and O(filter)
    for genre filtering.
    """
    import json

    catalog_path = _PROJECT_DIR / "tracks" / "tracks.json"
    try:
        stat = catalog_path.stat()
    except FileNotFoundError as exc:
        raise CatalogUnavailable(
            "No track catalog found. Add WAV files under tracks/<genre>/ and run "
            "`python main.py --build-catalog` to generate tracks.json."
        ) from exc

    with catalog_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("tracks") if isinstance(data, dict) else data
    if not entries:
        entries = []

    by_id: dict[str, dict] = {}
    for t in entries:
        tid = t.get("id")
        if tid:
            by_id[tid] = t

    genres = sorted({
        (t.get("genre_folder") or t.get("genre") or "").strip()
        for t in entries
        if (t.get("genre_folder") or t.get("genre"))
    })

    return {
        "key": (stat.st_mtime, stat.st_size),
        "all": entries,
        "by_id": by_id,
        "genres": genres,
    }


def _ensure_cache() -> dict:
    """Return the cached catalog payload, rebuilding on (mtime, size) change.

    Raises CatalogUnavailable when tracks.json is missing — kept consistent
    with check_catalog so callers can keep their existing error handling.
    """
    global _CATALOG_CACHE

    catalog_path = _PROJECT_DIR / "tracks" / "tracks.json"
    try:
        stat = catalog_path.stat()
    except FileNotFoundError as exc:
        _CATALOG_CACHE = None
        raise CatalogUnavailable(
            "No track catalog found. Add WAV files under tracks/<genre>/ and run "
            "`python main.py --build-catalog` to generate tracks.json."
        ) from exc

    cache_key = (stat.st_mtime, stat.st_size)
    if _CATALOG_CACHE is None or _CATALOG_CACHE.get("key") != cache_key:
        _CATALOG_CACHE = _read_catalog_from_disk()
    return _CATALOG_CACHE


def load_catalog(genre: str | None = None) -> tuple[list[dict], list[str]]:
    """Read tracks.json and return (filtered_tracks, all_available_genre_folders).

    Filters by genre_folder when `genre` is provided (case-insensitive). Raises
    CatalogUnavailable on missing/unreadable/empty catalog or unknown genre.

    Backed by an in-memory cache keyed on (mtime, size) of tracks.json so
    repeated calls (e.g. one per playlist GET) don't re-read and re-parse
    the file. Re-uses `_ensure_cache` for the file read so we don't pay the
    parse cost twice on every call (previously `check_catalog` re-read the
    file even when the cache was warm).
    """
    cache = _ensure_cache()
    entries: list[dict] = cache["all"]
    genres: list[str] = cache["genres"]

    if not entries:
        raise CatalogUnavailable(
            "Track catalog is empty. Add WAV files under tracks/<genre>/ and run "
            "`python main.py --build-catalog`."
        )

    if genre:
        target = genre.strip().lower()
        filtered = [
            t for t in entries
            if (t.get("genre_folder") or t.get("genre") or "").strip().lower() == target
        ]
        if not filtered:
            available = sorted({
                (t.get("genre_folder") or t.get("genre") or "").strip()
                for t in entries
                if (t.get("genre_folder") or t.get("genre"))
            })
            raise CatalogUnavailable(
                f"No tracks found for genre '{genre}'. Available genres: "
                f"{', '.join(available) if available else '(none)'}."
            )
        entries = filtered

    return entries, genres


def get_track_by_id(track_id: str) -> dict | None:
    """Return the catalog entry for `track_id`, or None if it isn't present.

    O(1) via the cached by-id index. Used by /api/playlists/{id} to hydrate
    track ids into full Track dicts without rebuilding the index per call.
    Returns None (rather than raising) when the catalog is unavailable so
    the playlist endpoint can fall back to its `missing=True` placeholder.
    """
    try:
        cache = _ensure_cache()
    except CatalogUnavailable:
        return None
    return cache["by_id"].get(track_id)


# ---------------------------------------------------------------------------
# User context — playlists + ratings keyed by user_id, cached per minute.
#
# v2.3.0 surface: phase_plan calls load_user_context() before invoking the
# Planner so the prompt can reference the user's favorites/dislikes/playlists
# as soft signal. The agent tools (get_user_playlists, get_favorite_tracks,
# ...) read directly from db when invoked — they don't go through this cache,
# but the planner's pre-load does.
#
# Cache shape: keyed on (user_id, time_bucket) with bucket = floor(t/60),
# mirroring the v2.2.1 _CATALOG_CACHE pattern. Worst-case staleness is ~60s,
# matching how often the rating UI is realistically interacted with.
# ---------------------------------------------------------------------------

_USER_CONTEXT_CACHE: dict[tuple[int, int], dict] = {}


def load_user_context(user_id: int) -> dict:
    """Load the per-user data the agent uses for soft-bias planning.

    Returns a dict shaped:
      {
        "playlists": [{id, name, track_count}, ...],
        "ratings":   {track_id: rating, ...},
        "favorite_ids": set[track_id],   # rating >= 4
        "dislike_ids":  set[track_id],   # rating <= 2
      }
    Always returns a valid dict (empty fields if user has no data). Cached
    per `(user_id, time_bucket=int(time.time() // 60))` so the cache rolls
    over once a minute without any explicit invalidation.
    """
    from . import db  # local import — keeps pipeline module's import surface tight.

    bucket = int(time.time() // 60)
    cache_key = (user_id, bucket)
    cached = _USER_CONTEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    playlists_raw = db.list_playlists_by_user(user_id)
    ratings = db.get_user_ratings(user_id)
    favorite_ids = {tid for tid, r in ratings.items() if r >= 4}
    dislike_ids = {tid for tid, r in ratings.items() if r <= 2}
    playlists = [
        {"id": p["id"], "name": p["name"], "track_count": p["track_count"]}
        for p in playlists_raw
    ]
    payload = {
        "playlists": playlists,
        "ratings": ratings,
        "favorite_ids": favorite_ids,
        "dislike_ids": dislike_ids,
    }
    # Trim stale buckets so the cache doesn't grow unboundedly across many
    # users / many minutes. Keep only entries from the current bucket.
    for k in list(_USER_CONTEXT_CACHE.keys()):
        if k[1] != bucket:
            _USER_CONTEXT_CACHE.pop(k, None)
    _USER_CONTEXT_CACHE[cache_key] = payload
    return payload


def _format_user_summary(user_ctx: dict, genre: str | None = None) -> str:
    """Format the user's playlists/ratings as a prompt block, or "" if empty.

    Caps: 10 favorites, 5 dislikes, 5 playlists. When `genre` is provided,
    favorites/dislikes that exist in the catalog for that genre are surfaced
    first so the planner sees the most relevant ids without using up tokens
    on unrelated picks.
    """
    favorite_ids: set[str] = user_ctx.get("favorite_ids") or set()
    dislike_ids: set[str] = user_ctx.get("dislike_ids") or set()
    playlists: list[dict] = user_ctx.get("playlists") or []

    if not favorite_ids and not dislike_ids and not playlists:
        return ""

    fav_max = 10
    dis_max = 5
    pls_max = 5

    in_genre_ids: set[str] = set()
    if genre:
        try:
            catalog_tracks, _ = load_catalog(genre)
            in_genre_ids = {t.get("id") for t in catalog_tracks if t.get("id")}
        except CatalogUnavailable:
            in_genre_ids = set()

    def _ordered(ids: set[str], cap: int) -> tuple[list[str], list[str]]:
        in_genre = sorted(i for i in ids if i in in_genre_ids)
        others = sorted(i for i in ids if i not in in_genre_ids)
        ordered = (in_genre + others)[:cap]
        return ordered, in_genre

    fav_show, fav_in_genre = _ordered(favorite_ids, fav_max)
    dis_show, dis_in_genre = _ordered(dislike_ids, dis_max)

    lines = ["USER PREFERENCES (current logged-in user):"]

    if favorite_ids:
        if genre:
            count_str = f"{len(favorite_ids)} tracks (within '{genre}': {len(fav_in_genre)})"
        else:
            count_str = f"{len(favorite_ids)} tracks"
        ids_str = ", ".join(fav_show) if fav_show else "(none in catalog)"
        lines.append(f"- Favorites (rating >= 4): {count_str}. Top {len(fav_show)}: {ids_str}")
    else:
        lines.append("- Favorites (rating >= 4): none")

    if dislike_ids:
        if genre:
            count_str = f"{len(dislike_ids)} tracks (within '{genre}': {len(dis_in_genre)})"
        else:
            count_str = f"{len(dislike_ids)} tracks"
        ids_str = ", ".join(dis_show) if dis_show else "(none in catalog)"
        lines.append(f"- Dislikes (rating <= 2): {count_str}. Top {len(dis_show)}: {ids_str}")
    else:
        lines.append("- Dislikes (rating <= 2): none")

    if playlists:
        pls_show = playlists[:pls_max]
        pls_str = ", ".join(f'"{p["name"]}" ({p["track_count"]} tracks)' for p in pls_show)
        more = f" (+{len(playlists) - len(pls_show)} more)" if len(playlists) > len(pls_show) else ""
        lines.append(f"- Saved playlists: {pls_str}{more}")
    else:
        lines.append("- Saved playlists: none")

    lines.append("")
    lines.append(
        "Use these as soft signal — favor user favorites within the requested "
        "genre when filling the playlist; avoid user dislikes unless required "
        "for harmonic continuity."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress hook — forwards subprocess stage updates from long-running tools
# (currently only build_session) back to the WebSocket as tool_progress events.
# The tool runs in a worker thread via asyncio.to_thread, so the callback must
# bounce events back onto the event loop thread before awaiting emit().
# ---------------------------------------------------------------------------

_PROGRESS_TOOLS = {"build_session"}


def _install_progress_hook(ctx: dict, tool_name: str, emit: Callable) -> None:
    if tool_name not in _PROGRESS_TOOLS:
        return
    loop = asyncio.get_running_loop()

    def _on_progress(event: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(
                emit({"type": "tool_progress", "name": tool_name, **event}),
                loop,
            )
        except Exception:
            pass  # never let UI plumbing break the tool

    ctx["_progress"] = _on_progress


# ---------------------------------------------------------------------------
# Async streaming agent runner
# ---------------------------------------------------------------------------

async def _run_anthropic_streaming(
    system: str,
    tool_fns: list[Callable],
    messages: list[dict],
    ctx: dict,
    emit: Callable,
    max_turns: int,
) -> str:
    import anthropic  # noqa: PLC0415

    client = anthropic.AsyncAnthropic()
    schemas = _build_anthropic_schemas(tool_fns)
    tool_index = {fn.__name__: fn for fn in tool_fns}
    final_text = ""

    for _ in range(max_turns):
        full_text = ""

        async with client.messages.stream(
            model=_MODEL,
            system=system,
            tools=schemas or [],
            messages=messages,
            max_tokens=4096,
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                await emit({"type": "text_delta", "content": text})
            final_msg = await stream.get_final_message()

        # Serialize content blocks for next-turn messages
        assistant_content = []
        for block in final_msg.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": assistant_content})
        final_text = full_text

        if final_msg.stop_reason != "tool_use":
            break

        tool_results = []
        for block in final_msg.content:
            if block.type == "tool_use":
                await emit({"type": "tool_call", "name": block.name, "input": block.input})
                _install_progress_hook(ctx, block.name, emit)
                try:
                    result = await asyncio.to_thread(
                        _run_tool, block.name, block.input, ctx, tool_index
                    )
                finally:
                    ctx.pop("_progress", None)
                await emit({"type": "tool_result", "name": block.name, "result": str(result)})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return final_text


def _build_async_azure_client():
    """Build an AsyncAzureOpenAI client from AZURE_OPENAI_* env vars."""
    from openai import AsyncAzureOpenAI  # noqa: PLC0415
    return AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )


async def _run_openai_streaming(
    system: str,
    tool_fns: list[Callable],
    messages: list[dict],
    ctx: dict,
    emit: Callable,
    max_turns: int,
    base_url: str | None = None,
) -> str:
    """Streaming runner for OpenAI-compatible APIs.

    When base_url is set, uses AsyncOpenAI (currently only Ollama).
    Otherwise constructs an AsyncAzureOpenAI client.
    """
    import json as _json  # noqa: PLC0415

    if base_url:
        from openai import AsyncOpenAI  # noqa: PLC0415
        client = AsyncOpenAI(base_url=base_url, api_key="ollama")
    else:
        client = _build_async_azure_client()
    schemas = _build_openai_schemas(tool_fns)
    tool_index = {fn.__name__: fn for fn in tool_fns}
    final_text = ""

    sys_messages = [{"role": "system", "content": system}] + messages

    for turn in range(max_turns):
        full_text = ""
        tool_calls_acc: dict[int, dict] = {}

        stream = await client.chat.completions.create(
            model=_MODEL,
            messages=sys_messages,
            tools=schemas or [],
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            if delta.content:
                full_text += delta.content
                await emit({"type": "text_delta", "content": delta.content})
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.function:
                        if tc.function.name:
                            tool_calls_acc[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

        if tool_calls_acc:
            tc_list = [
                {"id": v["id"], "type": "function",
                 "function": {"name": v["name"], "arguments": v["arguments"]}}
                for v in tool_calls_acc.values()
            ]
            sys_messages.append({"role": "assistant", "content": full_text or None, "tool_calls": tc_list})

            results = []
            for tc in tc_list:
                name = tc["function"]["name"]
                try:
                    inputs = _json.loads(tc["function"]["arguments"])
                except Exception:
                    inputs = {}
                await emit({"type": "tool_call", "name": name, "input": inputs})
                _install_progress_hook(ctx, name, emit)
                try:
                    result = await asyncio.to_thread(_run_tool, name, inputs, ctx, tool_index)
                finally:
                    ctx.pop("_progress", None)
                await emit({"type": "tool_result", "name": name, "result": str(result)})
                results.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
            sys_messages.extend(results)
        else:
            # v3.6.4 — textual-tool-call shim (mirror of the sync loop in
            # agent/run.py). gemma-4-e4b via LM Studio answers tool turns
            # with the literal text ``pick_next_track(...)`` and no
            # structured tool_calls; recover, execute, and keep looping so
            # the model can wrap up with real text. Note: the textualized
            # call already streamed to the UI as text_delta — cosmetic,
            # the frontend chat panel shows it as a code-ish line.
            shim = parse_textual_tool_call(full_text, tool_index)
            if shim is not None:
                name, inputs = shim
                print(
                    f"[llm-shim] textual tool call recovered: {name}({inputs})",
                    flush=True,
                )
                synthetic_id = f"shim-{turn}"
                sys_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": synthetic_id,
                        "type": "function",
                        "function": {"name": name, "arguments": _json.dumps(inputs)},
                    }],
                })
                await emit({"type": "tool_call", "name": name, "input": inputs})
                _install_progress_hook(ctx, name, emit)
                try:
                    result = await asyncio.to_thread(_run_tool, name, inputs, ctx, tool_index)
                finally:
                    ctx.pop("_progress", None)
                await emit({"type": "tool_result", "name": name, "result": str(result)})
                sys_messages.append({
                    "role": "tool",
                    "tool_call_id": synthetic_id,
                    "content": str(result),
                })
                continue
            sys_messages.append({"role": "assistant", "content": full_text})
            final_text = full_text
            break

    return final_text


async def run_agent_streaming(
    system: str,
    tool_fns: list[Callable],
    messages: list[dict],
    ctx: dict,
    emit: Callable,
    max_turns: int = 20,
) -> str:
    """Dispatch to the streaming runner for the configured provider."""
    if _PROVIDER == "anthropic":
        return await _run_anthropic_streaming(system, tool_fns, messages, ctx, emit, max_turns)
    if _PROVIDER == "ollama":
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return await _run_openai_streaming(system, tool_fns, messages, ctx, emit, max_turns, base_url=base)
    return await _run_openai_streaming(system, tool_fns, messages, ctx, emit, max_turns)


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

async def phase_genre_guard(
    message: str,
    history: list[dict],
    ctx: dict,
    emit: Callable,
) -> dict | None:
    """Run Genre Guard. Returns {genre, duration_min, mood} or None."""
    history.append({"role": "user", "content": message})
    # v3.7.3 — dynamic prompt (real catalog genres injected) + a
    # deterministic backstop: if the user literally named an available
    # genre and the model confirmed a different, unmentioned one, the
    # user wins. Small local models pattern-matched 'aural' requests
    # onto the prompt's lofi example (observed 2026-07-12).
    try:
        from agent.tools import _load_catalog_genres  # noqa: PLC0415
        genres = _load_catalog_genres()
    except Exception:  # noqa: BLE001 — no catalog → generic prompt, no backstop
        genres = []
    system = genre_guard_system(genres or None)
    response = await run_agent_streaming(system, _GENRE_TOOLS, history, ctx, emit)
    history.append({"role": "assistant", "content": response})
    parsed = _parse_confirmed_block(response)
    # Every user turn counts — the genre may have been named before the
    # final confirmation message.
    user_text = " ".join(
        str(m.get("content") or "") for m in history if m.get("role") == "user"
    )
    return enforce_mentioned_genre(user_text, parsed, genres)


async def _hydrate_user_context(ctx: dict) -> None:
    """Populate favorite_ids/dislike_ids/user_ratings/user_playlists in ctx
    if a user_id is present.

    Idempotent: safe to call multiple times per session — the second call
    short-circuits as soon as it sees `favorite_ids` already in ctx, so
    phase_plan / phase_critique / phase_editor can each call this without
    re-querying the DB. The underlying `load_user_context` is also cached
    at 60s TTL, so even a fresh-ctx critic turn coming in 30s after a plan
    re-uses the same payload.

    No-op when no `user_id` is in ctx (e.g. anonymous CLI sessions).
    """
    user_id = ctx.get("user_id")
    if user_id is None:
        return
    if "favorite_ids" in ctx:  # already hydrated
        return
    user_ctx = await asyncio.to_thread(load_user_context, user_id)
    ctx["favorite_ids"] = user_ctx["favorite_ids"]
    ctx["dislike_ids"] = user_ctx["dislike_ids"]
    ctx["user_ratings"] = user_ctx["ratings"]
    ctx["user_playlists"] = user_ctx["playlists"]


async def phase_plan(ctx: dict, emit: Callable, memory_summary: str = "") -> str:
    """Run Planner. Populates ctx['playlist'].

    When `ctx["user_id"]` is present, hydrate the context with the user's
    playlists/ratings (favorite_ids, dislike_ids, etc.) and inject a
    "USER PREFERENCES" block into the prompt so the Planner can soft-bias
    selection toward favorites and away from dislikes.
    """
    genre = ctx.get("genre", "")
    duration = ctx.get("duration_min", 60)
    mood = ctx.get("mood", "")
    environment = ctx.get("environment", "") or ""
    prompt = f"Build a {duration}-minute {genre} set. Mood: {mood}."
    # v2.5.0 — surface the environment string in the prompt so the Planner
    # honours the ENVIRONMENT SIGNAL block from ``_PLANNER_SYSTEM``. We omit
    # the line entirely when the value is empty / "unspecified" to avoid
    # sending noise the planner is told to ignore anyway.
    if environment and environment.strip().lower() != "unspecified":
        prompt += f"\nEnvironment: {environment}."
    if memory_summary:
        prompt += f"\n\nPast session notes:\n{memory_summary}"

    user_id = ctx.get("user_id")
    if user_id is not None:
        await _hydrate_user_context(ctx)
        # Re-fetch the cached payload to format the prompt block. The
        # `load_user_context` cache (60s TTL) makes this free.
        user_ctx = await asyncio.to_thread(load_user_context, user_id)
        user_summary = _format_user_summary(user_ctx, ctx.get("genre"))
        if user_summary:
            prompt += f"\n\n{user_summary}"

    messages = [{"role": "user", "content": prompt}]
    return await run_agent_streaming(_PLANNER_SYSTEM, _PLANNER_TOOLS, messages, ctx, emit)


async def phase_critique(
    ctx: dict,
    emit: Callable,
    memory_summary: str = "",
) -> tuple[str, list[str], list[dict]]:
    """Run Critic. Returns (verdict, problems, structured_problems).

    v2.3.2: hydrates user context (favorite_ids/dislike_ids/user_ratings)
    so the Critic's tool calls can reach the per-user signal AND so the
    deterministic dislike-flagging post-process can append problems for
    any low-rated tracks the LLM may have skipped.
    """
    await _hydrate_user_context(ctx)
    prompt = "A playlist has been proposed. Review it and deliver your verdict."
    if memory_summary:
        prompt += f"\n\nMemory context:\n{memory_summary}"
    messages = [{"role": "user", "content": prompt}]
    response = await run_agent_streaming(_CRITIC_SYSTEM, _CRITIC_TOOLS, messages, ctx, emit)
    verdict, problems, structured_problems = _parse_critic_response(
        response, ctx.get("playlist")
    )

    # Deterministic dislike pass: even if the LLM forgets the
    # USER PREFERENCES guidance, surface every track the user has rated
    # ★1 or ★2 as a structured_problem so the Editor can swap it.
    structured_problems = _append_dislike_problems(
        ctx.get("playlist") or [],
        ctx.get("dislike_ids") or set(),
        ctx.get("user_ratings") or {},
        structured_problems,
    )
    return verdict, problems, structured_problems


async def phase_editor(
    message: str,
    history: list[dict],
    ctx: dict,
    emit: Callable,
) -> str:
    """Run one Editor turn. Mutates ctx['playlist'] via tool calls.

    v2.3.2: hydrates user context so the Editor's tools (and the new
    USER PREFERENCES SIGNAL clause in `_EDITOR_SYSTEM`) can read
    favorite_ids / dislike_ids / user_ratings without re-querying SQLite.
    """
    await _hydrate_user_context(ctx)
    history.append({"role": "user", "content": message})
    response = await run_agent_streaming(_EDITOR_SYSTEM, _WEB_EDITOR_TOOLS, history, ctx, emit)
    history.append({"role": "assistant", "content": response})
    return response


def _append_dislike_problems(
    playlist: list[dict],
    dislike_ids: set,
    ratings: dict,
    structured_problems: list[dict],
) -> list[dict]:
    """Append a structured_problem for each playlist track the user dislikes.

    This is a deterministic pass that runs after the LLM critic — it
    guarantees the Editor sees every ★1/★2 track even if the LLM forgot
    the user-preferences guidance. Pure function for easy testing.
    """
    if not dislike_ids:
        return structured_problems
    out = list(structured_problems)
    for i, track in enumerate(playlist):
        tid = track.get("id")
        if tid in dislike_ids:
            rating = ratings.get(tid, 0)
            display = track.get("display_name", tid)
            out.append({
                "pos_from": i + 1,
                "pos_to": i + 1,
                "key_pair": "",
                "bpm_diff": 0,
                "text": f"User rated '{display}' as ★{rating} — consider swap",
            })
    return out


async def phase_validate(session_name: str, ctx: dict, emit: Callable) -> tuple[str, list[str]]:
    """Run Validator. Returns (status, issues)."""
    messages = [{"role": "user", "content": f"Session '{session_name}' was just built. Validate its audio quality."}]
    response = await run_agent_streaming(_VALIDATOR_SYSTEM, _VALIDATOR_TOOLS, messages, ctx, emit)
    return _parse_validator_response(response)


async def load_memory(genre: str, ctx: dict) -> str:
    """Load past session memory for the given genre (runs in thread — does I/O)."""
    return await asyncio.to_thread(read_memory, genre, context_variables=ctx)


# ---------------------------------------------------------------------------
# v2.6.0 — set-health + REST→async bridge
# ---------------------------------------------------------------------------

# Coefficient for set-health: each structured problem subtracts this many
# points. Calibrated so a perfect set scores 100, a typical critique with
# 3-4 issues lands ~75-80, and only catastrophic playlists drop below 60.
_SET_HEALTH_PROBLEM_PENALTY = 6


def compute_set_health(structured_problems: list[dict] | None) -> int:
    """Derive a 0–100 score from the critic's structured problem count.

    Called after `phase_critique` and after every editor mutation that
    might fix or introduce a problem.
    """
    n = len(structured_problems or [])
    return max(0, min(100, 100 - _SET_HEALTH_PROBLEM_PENALTY * n))


async def run_planning_from_brief(s, emit: Callable) -> None:
    """Drive genre → plan → critique after the Brief parser seeded ``ctx``.

    Called from ``POST /api/sessions { brief }`` as a background task. Mutates
    the Session in place (phase, structured_problems, set_health, etc.) and
    emits ``phase_start``/``phase_complete`` events the same way the WS
    dispatcher does — so the frontend's `/curate` page can subscribe via
    ``/ws/sessions/{id}`` and pick up the stream transparently.

    The legacy WS flow requires a manual ``checkpoint1`` approval between
    plan and critique. v2.6.0 collapses that into one continuous "Apollo is
    curating" step: the user reviews + acts on the result at ``/curate``,
    which implicitly approves by clicking Materialize.

    Falls back to the conversational ``phase_genre_guard`` whenever the
    cheap brief parser couldn't pin a genre OR returned a genre that isn't
    in the catalog. The user's reply on /curate via the existing WS
    handler will resume the chain (``genre_intent`` path).
    """
    if "user_id" not in s.context_variables:
        s.context_variables["user_id"] = s.user_id

    brief_text = s.context_variables.get("brief_text", "")

    # Catalog pre-flight — surfaces "no tracks at all" as a banner rather
    # than as a vague LLM response.
    try:
        await asyncio.to_thread(check_catalog)
    except CatalogUnavailable as exc:
        await emit({"type": "error", "message": str(exc)})
        s.phase = "init"
        return

    # ── Genre confirmation (only when parser couldn't pin a usable one) ─
    genre = s.context_variables.get("genre")
    needs_guard = not genre
    if genre:
        try:
            await asyncio.to_thread(check_catalog, genre)
        except CatalogUnavailable:
            # Parser hallucinated a genre that isn't in catalog. Drop it
            # and fall back to the guard with the brief text as input.
            s.context_variables.pop("genre", None)
            needs_guard = True

    if needs_guard:
        s.phase = "genre"
        history = s.messages.setdefault("genre", [])
        confirmed = await phase_genre_guard(
            brief_text or "I'd like to build a set.",
            history, s.context_variables, emit,
        )
        if not confirmed:
            # Guard is still asking. Stay in "genre" so the WS dispatcher
            # picks up the user's next reply and resumes from there.
            return
        s.context_variables.update(confirmed)
        await emit({"type": "phase_complete", "phase": "genre", "data": s.to_dict()})
        # Re-validate after the guard pinned a genre.
        try:
            await asyncio.to_thread(check_catalog, confirmed["genre"])
        except CatalogUnavailable as exc:
            await emit({"type": "error", "message": str(exc)})
            s.phase = "init"
            return

    # ── Planner ───────────────────────────────────────────────────
    s.phase = "planning"
    await emit({"type": "phase_start", "phase": "planning"})
    memory = await load_memory(s.context_variables.get("genre", ""), s.context_variables)
    await phase_plan(s.context_variables, emit, memory)
    await emit({"type": "phase_complete", "phase": "planning", "data": s.to_dict()})

    # ── Critic (auto-chained) ─────────────────────────────────────
    s.phase = "critique"
    await emit({"type": "phase_start", "phase": "critique"})
    verdict, problems, structured = await phase_critique(
        s.context_variables, emit, memory
    )
    s.critic_verdict = verdict
    s.critic_problems = problems
    s.structured_problems = structured
    s.set_health = compute_set_health(structured)
    s.phase = "checkpoint2"
    await emit({"type": "phase_complete", "phase": "critique", "data": s.to_dict()})


# ---------------------------------------------------------------------------
# v2.5.1 — Live phase. The planning pipeline ends at the rating step; the
# live phase is its own loop driven by ``agent.live_dj.run_live_session_async``
# and a ``LiveEngineBrowser`` that publishes events through the WS handler.
#
# Kept here (rather than inside ``app.py``) so the mock_pipeline can swap in
# a deterministic fake the same way it does for ``phase_plan`` etc., and so
# anyone reading the pipeline file sees every backend phase in one place.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# v2.5.2 perception buffer + audience-request batcher (live phase only)
# ---------------------------------------------------------------------------

# Synthesis thresholds. Tuned to match the v2.5.2 plan defaults:
#   - 6 dB shift between consecutive windows triggers environment_changed
#   - At most one synthetic event per 30 s
#   - Audience requests batch with a 5 s collection window
#   - At most one audience_request_batch per 30 s
PERCEPTION_BUFFER_LEN = 10
PERCEPTION_RMS_DELTA_DB = 6.0
PERCEPTION_VOICE_DROP = 0.5
ENVIRONMENT_CHANGED_RATELIMIT_SEC = 30.0
AUDIENCE_BATCH_WINDOW_SEC = 5.0
AUDIENCE_RATELIMIT_SEC = 30.0


def _perception_window_means(buffer: list[dict]) -> tuple[float, float | None]:
    """Return (rms_mean, voice_mean) for the ring buffer. Voice is None
    when no sample carries a numeric ``voice_likelihood``."""
    if not buffer:
        return (0.0, None)
    rms_vals = [float(s.get("rms_db", 0.0)) for s in buffer]
    rms_mean = sum(rms_vals) / len(rms_vals)
    voice_vals = [
        float(s["voice_likelihood"])
        for s in buffer
        if s.get("voice_likelihood") is not None
    ]
    voice_mean = sum(voice_vals) / len(voice_vals) if voice_vals else None
    return (rms_mean, voice_mean)


def _detect_environment_change(
    prev_means: tuple[float, float | None],
    new_means: tuple[float, float | None],
) -> dict | None:
    """Return a synthetic event payload when the window means shift past
    the v2.5.2 thresholds, otherwise None.

    A single delta crossing is enough — we look at RMS dB delta first
    (most reliable), then a voice-likelihood drop as a secondary trigger.
    """
    prev_rms, prev_voice = prev_means
    new_rms, new_voice = new_means
    rms_delta = new_rms - prev_rms
    if abs(rms_delta) >= PERCEPTION_RMS_DELTA_DB:
        return {
            "type": "environment_changed",
            "rms_db_delta": rms_delta,
            "rms_db_mean": new_rms,
            "voice_likelihood": new_voice,
        }
    if (
        prev_voice is not None
        and new_voice is not None
        and prev_voice - new_voice >= PERCEPTION_VOICE_DROP
    ):
        return {
            "type": "environment_changed",
            "rms_db_delta": rms_delta,
            "rms_db_mean": new_rms,
            "voice_likelihood": new_voice,
            "voice_likelihood_delta": new_voice - prev_voice,
        }
    return None


async def _live_relay(
    source_queue: asyncio.Queue,
    inner_queue: asyncio.Queue,
    ctx: dict,
    *,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """Bridge the WS-side queue into the agent loop, synthesising
    ``environment_changed`` and ``audience_request_batch`` events.

    All non-perception / non-audience items pass through verbatim so the
    agent loop keeps seeing engine events + control messages in order.
    """
    perception_buffer: list[dict] = ctx.setdefault("perception_buffer", [])
    last_env_emit_ts: float | None = None
    # Baseline window mean — captured once the buffer first reaches a
    # comparable size, then refreshed every time we emit an event so
    # subsequent deltas measure against the new "normal" rather than the
    # original silence floor. This is the per-sample equivalent of "two
    # consecutive 20-second windows": each new sample shifts the active
    # mean and we compare against the snapshot taken at the last reset.
    baseline_means: tuple[float, float | None] | None = None
    BASELINE_MIN_SAMPLES = 3

    pending_requests: list[dict] = []
    last_audience_emit_ts: float | None = None
    audience_flush_at: float | None = None

    async def flush_audience() -> None:
        nonlocal pending_requests, last_audience_emit_ts, audience_flush_at
        if not pending_requests:
            audience_flush_at = None
            return
        cur = now()
        n = len(pending_requests)
        if (
            last_audience_emit_ts is not None
            and (cur - last_audience_emit_ts) < AUDIENCE_RATELIMIT_SEC
        ):
            # Drop this batch — the agent is still in the cooldown for the
            # previous one. We log on the context for tests / debugging.
            print(
                f"[live_relay] DROPPED audience batch of {n} (rate-limited, "
                f"{cur - last_audience_emit_ts:.1f}s of {AUDIENCE_RATELIMIT_SEC}s cooldown)",
                flush=True,
            )
            ctx.setdefault("audience_dropped", []).extend(pending_requests)
            pending_requests = []
            audience_flush_at = None
            return
        print(
            f"[live_relay] FLUSH audience batch of {n} to agent",
            flush=True,
        )
        await inner_queue.put(
            {
                "type": "audience_request_batch",
                "requests": list(pending_requests),
            }
        )
        last_audience_emit_ts = cur
        pending_requests = []
        audience_flush_at = None

    while True:
        # Compute the next deadline — either the audience batch flush or
        # an indefinite wait. We use ``asyncio.wait_for`` with a short
        # timeout so flushes happen even when the source queue is idle.
        if audience_flush_at is not None:
            timeout = max(0.0, audience_flush_at - now())
        else:
            timeout = None

        try:
            if timeout is None:
                item = await source_queue.get()
            else:
                item = await asyncio.wait_for(source_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            await flush_audience()
            continue

        item_type = item.get("type") if isinstance(item, dict) else None

        if item_type == "perception_sample":
            perception_buffer.append(item)
            if len(perception_buffer) > PERCEPTION_BUFFER_LEN:
                # Drop oldest — keep last N samples for the window.
                del perception_buffer[: len(perception_buffer) - PERCEPTION_BUFFER_LEN]
            new_means = _perception_window_means(perception_buffer)
            if (
                baseline_means is None
                and len(perception_buffer) >= BASELINE_MIN_SAMPLES
            ):
                # First time the window has settled — anchor here.
                baseline_means = new_means
            elif baseline_means is not None:
                synthetic = _detect_environment_change(baseline_means, new_means)
                if synthetic:
                    cur = now()
                    if (
                        last_env_emit_ts is None
                        or (cur - last_env_emit_ts)
                        >= ENVIRONMENT_CHANGED_RATELIMIT_SEC
                    ):
                        await inner_queue.put(synthetic)
                        last_env_emit_ts = cur
                        # Reset the baseline so we measure the *next* shift
                        # against the new normal — otherwise we'd keep
                        # firing while the room stays loud.
                        baseline_means = new_means
            continue

        if item_type == "user_msg":
            # An audience request — buffer for the batch window so a burst
            # of asks generates a single LLM call. Empty / control commands
            # ("skip", "stay", "next", "quit") still fall through as
            # user_msg so the existing engine wiring keeps working — but
            # ALSO trigger a flush so the agent doesn't see a stale batch.
            text = (item.get("text") or "").strip()
            text_l = text.lower()
            CONTROL_TOKENS = {"skip", "next", "stay", "longer", "more", "quit"}
            if text_l in CONTROL_TOKENS or not text:
                await inner_queue.put(item)
                continue
            pending_requests.append(
                {
                    "text": text,
                    "timestamp_ms": item.get("timestamp_ms"),
                }
            )
            if audience_flush_at is None:
                audience_flush_at = now() + AUDIENCE_BATCH_WINDOW_SEC
            continue

        # Engine events / quit / anything else: pass through verbatim.
        await inner_queue.put(item)


async def phase_live(
    playlist: list[dict],
    ctx: dict,
    engine,
    emit: Callable,
    command_queue,
) -> None:
    """Run the live DJ session driven by ``run_live_session_async``.

    ``engine`` is a :class:`agent.live_engine.LiveEngineProtocol` — in the
    web path this is a :class:`LiveEngineBrowser` whose emitter forwards
    events to the WS handler.

    ``emit`` is the same async send-to-WS callable used by the planning
    phases. ``command_queue`` is an :class:`asyncio.Queue` that the WS
    handler fills with engine events + user commands + perception samples.

    v2.5.2: a relay coroutine sits between the WS-side queue and the agent
    loop, maintaining the perception buffer and batching audience requests
    so the LiveDJ loop sees synthesised ``environment_changed`` /
    ``audience_request_batch`` events instead of raw ticks.

    Returns when the playlist is exhausted (``session_ended`` event), the
    user sends a quit command, or the queue is closed by the WS handler
    on disconnect (the handler cancels this coroutine in that case).
    """
    from agent import live_dj  # noqa: PLC0415 — circular import guard

    # Hydrate the agent context with the v2.5.2 buffers + emitter so the
    # tools (get_perception_window, emit_chat) and the relay all share state.
    ctx.setdefault("perception_buffer", [])
    ctx["_event_emitter"] = emit

    inner_queue: asyncio.Queue = asyncio.Queue()
    relay_task = asyncio.create_task(
        _live_relay(command_queue, inner_queue, ctx)
    )

    # v2.6.0 — flip endless / improvisation mode from session context
    # before the engine starts so the very first APPROACHING_CF window
    # already respects the flag. The WS `set_endless_mode` command can
    # flip it again mid-set; both writes are GIL-atomic single-attribute
    # assignments — eventual consistency within a watchdog tick is fine.
    engine._endless_mode = bool(ctx.get("endless_mode", False))

    engine.play(playlist)
    try:
        await live_dj.run_live_session_async(
            playlist, ctx, engine, emit, inner_queue
        )
    finally:
        relay_task.cancel()
        try:
            await relay_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        ctx.pop("_event_emitter", None)
        engine.stop()


# ---------------------------------------------------------------------------
# Mock mode — AGENT_PROVIDER=mock swaps every phase with deterministic fakes
# so tests/E2E runs never touch Anthropic, OpenAI, librosa, or the filesystem.
# ---------------------------------------------------------------------------

if _PROVIDER_ENV == "mock":
    from . import mock_pipeline  # noqa: E402

    mock_pipeline.install(sys.modules[__name__])
