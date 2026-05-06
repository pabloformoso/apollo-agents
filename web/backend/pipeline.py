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
_HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))

if _PROVIDER_ENV == "anthropic" or (_HAS_ANTHROPIC and not _PROVIDER_ENV):
    _PROVIDER = "anthropic"
elif _PROVIDER_ENV == "openai" or (_HAS_OPENAI and not _PROVIDER_ENV):
    _PROVIDER = "openai"
elif _PROVIDER_ENV == "ollama":
    _PROVIDER = "ollama"
else:
    _PROVIDER = "anthropic"

_DEFAULT_MODELS = {"anthropic": "claude-opus-4-6", "openai": "gpt-4o", "ollama": "gemma4:4b"}
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


async def _run_openai_streaming(
    system: str,
    tool_fns: list[Callable],
    messages: list[dict],
    ctx: dict,
    emit: Callable,
    max_turns: int,
    base_url: str | None = None,
) -> str:
    import json as _json  # noqa: PLC0415
    from openai import AsyncOpenAI  # noqa: PLC0415

    client = AsyncOpenAI(base_url=base_url) if base_url else AsyncOpenAI()
    schemas = _build_openai_schemas(tool_fns)
    tool_index = {fn.__name__: fn for fn in tool_fns}
    final_text = ""

    sys_messages = [{"role": "system", "content": system}] + messages

    for _ in range(max_turns):
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
    response = await run_agent_streaming(_GENRE_GUARD_SYSTEM, _GENRE_TOOLS, history, ctx, emit)
    history.append({"role": "assistant", "content": response})
    return _parse_confirmed_block(response)


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
    prompt = f"Build a {duration}-minute {genre} set. Mood: {mood}."
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
# Mock mode — AGENT_PROVIDER=mock swaps every phase with deterministic fakes
# so tests/E2E runs never touch Anthropic, OpenAI, librosa, or the filesystem.
# ---------------------------------------------------------------------------

if _PROVIDER_ENV == "mock":
    from . import mock_pipeline  # noqa: E402

    mock_pipeline.install(sys.modules[__name__])
