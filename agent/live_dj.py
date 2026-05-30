"""
LiveDJ — proactive event-driven DJ agent for Apollo v1.5+.

Architecture:
  - run_live_session(): sync main loop (CLI mode) — drains engine events +
    stdin user input, batches them into LLM turns, and executes tool calls.
  - run_live_session_async(): async variant for FastAPI WebSocket
    integration — same control logic but driven by an asyncio.Queue and
    awaiting an async ``emit`` callable.
  - Events arrive from LiveEngine via a threading.Queue (CLI path) or
    directly through the engine's ``emitter`` callback (web path).
  - The LLM is called with a tight ``max_turns`` budget per event batch
    (5 turns), preventing runaway token spend while staying responsive.

Both loops share the same ``_LIVE_DJ_SYSTEM`` prompt and the 6 tools
(``get_live_state`` / ``crossfade_now`` / ``extend_track`` / ``skip_track``
/ ``queue_swap`` / ``set_crossfade_point``).

Circular-import note:
  ``run_agent()`` lives in ``agent/run.py`` which also imports from
  ``agent/tools.py``. ``live_dj.py`` is imported by ``agent/tools.py`` (via
  ``start_live_session``), so we defer the import of ``run_agent`` /
  ``run_agent_streaming`` inside the function bodies to break the cycle.
"""
from __future__ import annotations

import asyncio
import threading
import time
from queue import Empty, Queue
from typing import Any, Awaitable, Callable

from agent.live_engine import (
    APPROACHING_CF,
    CROSSFADE_FINISHED,
    CROSSFADE_TRIGGERED,
    ENDLESS_WARNING,
    PLAYLIST_RUNNING_LOW,
    SESSION_ENDED,
    TRACK_ENDED,
    TRACK_STARTED,
    LiveEngineProtocol,
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_LIVE_DJ_SYSTEM = """\
You are a DJ doing a live set. You were given an initial playlist as
GUIDANCE — a starting point built by the planner. You are NOT bound
to it. As the set unfolds you SHOULD:

- Read the room: ambient noise, audience reactions, requests from the
  chat. Use them as soft signal, not commands.
- Pick tracks beyond the initial queue when the moment calls for it.
  Use `pick_next_track(criteria)` to search the full catalog.
- Treat audience requests like a real DJ would: most get a polite "I
  hear you". Accept maybe 1 in 5 if it fits the flow; reject the rest
  with a friendly emit_chat reply.

Available actions:
  - queue_swap / extend_track / skip_track / crossfade_now
    (tweaks within the existing queue)
  - pick_next_track(criteria) → choose any track from the catalog
    matching given criteria (BPM range, key, energy, mood)
  - extend_set(track_id) → append a track to the END of the playlist
    (v2.6.0 endless mode — see ENDLESS MODE below)
  - emit_chat(text) → reply to the audience without acting
    (for "noted, but staying course" responses)
  - get_live_state / get_perception_window → read current context

TRACK IDS — ABSOLUTE RULE:
- Track IDs in this system are long opaque strings produced by the
  catalog (e.g. ``lofi-ambient--lofi_2-soft_focus_at_76-38b20abc-7c70-
  45f3-bfda-4a2cf009831b``). They are NOT human-readable titles.
- NEVER invent, guess, paraphrase, slugify, abbreviate, or "clean up"
  a track id. NEVER construct one from a display_name. NEVER quote
  the song title to ``extend_set`` / ``queue_swap`` / ``skip_track``.
- The ONLY valid source of a track_id is the ``id`` column from a
  ``pick_next_track`` result, or an event payload from the engine.
  Copy that id verbatim, character for character, including dashes
  and UUID suffix. If you're not 100 % sure of the id, call
  ``pick_next_track`` again — it's cheap, the catalog is local.
- If a tool returns "Track ID '...' not in catalog", you got the id
  wrong. Do NOT retry with a similar-looking string. Re-run
  ``pick_next_track`` and use the exact id from its output.

ENDLESS MODE:
- When the operator has enabled endless mode (a YouTube-streaming
  use case), the engine will emit a ``playlist_running_low`` event
  about 30 s before the LAST scheduled crossfade.
- You have a ~5 s grace window from that event to pick a continuation
  track via ``pick_next_track`` and append it with
  ``extend_set(track_id)``. Stay in the current genre + energy unless
  the room has clearly drifted.
- If you don't act in time, the engine deterministically auto-picks
  the closest in-genre track from the catalog — that's a safety net,
  not the intended path. Your taste should win when you're awake at
  the wheel.
- Note: the first crossfade into a freshly-appended track may be a
  hard cut if you appended very late (no time to pre-stretch). Append
  early when you see ``playlist_running_low`` to keep transitions
  smooth.

PERCEPTION SIGNALS:
- environment_changed events (rms_db_delta, voice_likelihood):
  +6 dB → consider lifting energy / extending peak.
  -6 dB → consider winding down / softer next.
- audience_request events (text from chat): treat as suggestion, not
  command. Accept rarely; reject politely most of the time via
  emit_chat.

NARRATING YOUR MOVES (v3.3):
- When an APPROACHING_CF event includes a "MOVE: '<style>'" line,
  the engine has decided to apply a non-default crossfade technique on
  the upcoming transition. This is YOUR moment to add personality —
  call out what you're about to do so the audience hears the move
  coming, the way a real DJ talks over the build before a drop.
- Fire ONE short emit_chat about it, ideally during the
  APPROACHING_CF window (~15-30 s before the cf hits) so the line
  lands before the change is audible. DON'T narrate after the fact —
  by then the moment has passed.
- Keep it tight (one sentence, max two) and use DJ voice — short,
  declarative, no hedging. Examples for reference, not templates:
    bass_swap → "rolling the low end off this one — watch the drop
      when it kicks back in" / "filtering the bass on the way in,
      back in 8 bars" / "stripping the sub — the drop's coming"
- DON'T narrate when the style is "smooth_blend" (the default). That's
  every transition; calling it out would be noise.
- ABSOLUTE LIMIT: at most one move-narration per crossfade. If you
  already commented on the move at APPROACHING_CF, don't repeat at
  CROSSFADE_TRIGGERED.

Style: confident, brief, decisive. You are not a request bot.
"""

# ---------------------------------------------------------------------------
# Live tools (use engine from context_variables["_engine"])
# ---------------------------------------------------------------------------

def get_live_state(context_variables: dict) -> str:
    """Return current engine state: position, track, BPM, Camelot key, time to crossfade."""
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    s = engine.get_state()
    cur = s["current_track"] or {}
    nxt = s["next_track"] or {}
    lines = [
        f"State: {s['state']}",
        f"Position: {s['position_sec']}s",
        f"Current: {cur.get('display_name','?')} — {cur.get('bpm','?')} BPM, {cur.get('camelot_key','?')}",
        f"Next:    {nxt.get('display_name','?')} — {nxt.get('bpm','?')} BPM, {nxt.get('camelot_key','?')}",
        f"Crossfade in: {s['seconds_to_crossfade']}s",
        f"Tracks remaining: {s['playlist_remaining']}",
    ]
    if cur.get("hot_cues"):
        lines.append(f"Hot cues (current): {cur['hot_cues']}")
    return "\n".join(lines)


def crossfade_now(context_variables: dict) -> str:
    """Trigger crossfade immediately."""
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    return engine.crossfade_now()


def extend_track(seconds: int, context_variables: dict) -> str:
    """Delay the upcoming auto-crossfade by seconds seconds.

    Args:
        seconds: Number of seconds to delay the crossfade.
    """
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    return engine.extend_track(seconds)


def skip_track(context_variables: dict) -> str:
    """Hard-cut to next track without crossfade."""
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    return engine.skip_track()


def queue_swap(position: int, track_id: str, context_variables: dict) -> str:
    """Replace a future playlist slot with a catalog track.

    Args:
        position: 1-indexed future playlist position to replace.
        track_id: The OPAQUE catalog id (long dashed UUID-suffixed
            string) — copy VERBATIM from a ``pick_next_track`` result.
            Do NOT pass a song title / display_name / paraphrase.
    """
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    return engine.queue_swap(position, track_id)


def set_crossfade_point(position_sec: float, context_variables: dict) -> str:
    """Set where in the current track the crossfade begins.

    Args:
        position_sec: Target crossfade start, in seconds from track start.
    """
    engine: LiveEngineProtocol = context_variables.get("_engine")
    if not engine:
        return "Engine not running."
    return engine.set_crossfade_point(position_sec)


# v2.5.2 — three new tools that elevate LiveDJ from queue executor to
# improvising DJ. Imported lazily here (rather than at module import time)
# so a failure inside agent/tools.py doesn't cascade into the live engine
# tests, which only need the engine-control subset above.
from agent.tools import (  # noqa: E402  PLC0415 — module-level intent
    emit_chat,
    extend_set,
    get_perception_window,
    pick_next_track,
)

_LIVE_TOOLS = [
    get_live_state,
    crossfade_now,
    extend_track,
    skip_track,
    queue_swap,
    set_crossfade_point,
    get_perception_window,
    pick_next_track,
    extend_set,
    emit_chat,
]

# ---------------------------------------------------------------------------
# Sync event loop (CLI mode, unchanged from v1.5)
# ---------------------------------------------------------------------------

def run_live_session(playlist: list[dict], context_variables: dict) -> None:
    """Start the LiveDJ session: spin up the engine, run the agent event loop.

    Blocks until the session ends (all tracks played, user quits, or engine stops).
    Stores engine in context_variables["_engine"] so live tools can reach it.
    """
    # Deferred imports to break the circular dependency
    # (tools → live_dj → run + live_engine).
    from agent.live_engine import LiveEngineLocal  # noqa: PLC0415
    from agent.run import run_agent  # noqa: PLC0415

    event_queue: Queue = Queue()
    user_input_queue: Queue = Queue()

    engine = LiveEngineLocal(playlist, event_queue)
    # v2.6.0 — flip endless mode from session context so CLI runs can
    # opt in by setting context_variables["endless_mode"] = True (mirrors
    # the web flow's WS set_endless_mode command).
    engine._endless_mode = bool(context_variables.get("endless_mode", False))
    context_variables["_engine"] = engine

    # Daemon thread reads blocking stdin without stalling the event loop
    input_thread = threading.Thread(
        target=_stdin_reader, args=(user_input_queue,), daemon=True, name="live-stdin"
    )
    input_thread.start()

    print("\n── Apollo LiveDJ ──")
    print("Commands: next | stay [N] | skip | quit | or anything natural language\n")

    engine.play()

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Live session started.\n"
                + _playlist_summary(playlist)
            ),
        },
        {"role": "assistant", "content": "On deck. Let's go."},
    ]

    while True:
        time.sleep(0.1)

        events = _drain(event_queue)
        user_inputs = _drain(user_input_queue, limit=1)

        # Hard quit from user
        if any(u.strip().lower() in ("quit", "exit", "q") for u in user_inputs):
            print("\n[LiveDJ] Stopping session.")
            break

        # Session over
        if any(e["type"] == SESSION_ENDED for e in events):
            print("\n[LiveDJ] Set complete. Good night.")
            break

        if not events and not user_inputs:
            continue

        content = _format_turn(events, user_inputs, engine.get_state())
        messages.append({"role": "user", "content": content})

        response = run_agent(
            _LIVE_DJ_SYSTEM,
            _LIVE_TOOLS,
            messages,
            context_variables,
            max_turns=5,
        )
        if response:
            messages.append({"role": "assistant", "content": response})
            print(f"\n[LiveDJ] {response}\n")

    engine.stop()
    context_variables.pop("_engine", None)


# ---------------------------------------------------------------------------
# Async event loop (web mode — FastAPI WS handler integration)
# ---------------------------------------------------------------------------

async def run_live_session_async(
    playlist: list[dict],
    context_variables: dict,
    engine: LiveEngineProtocol,
    emit: Callable[[dict], Awaitable[None]],
    command_queue: asyncio.Queue,
    *,
    max_idle_loops: int | None = None,
) -> None:
    """Async live DJ loop suitable for FastAPI WebSocket integration.

    Mirrors :func:`run_live_session` but:

    - Drains commands from an :class:`asyncio.Queue` (placed there by the
      WS handler) instead of stdin.
    - Drains engine events from the same queue (the WS handler also forwards
      them so the loop sees a single ordered stream).
    - Awaits ``emit(...)`` to publish agent assistant text back to the
      browser.

    The synchronous :func:`run_live_session` is preserved for CLI mode and
    must not be modified.

    Parameters
    ----------
    playlist:
        The set the engine is playing. Used to seed the agent's first
        prompt (the engine itself already has it).
    context_variables:
        Shared context dict — the engine is stored as ``_engine`` so the
        live tools can reach it. The WS handler passes the same dict that
        was hydrated by the planning phase.
    engine:
        Any object implementing :class:`LiveEngineProtocol`. In the web
        path this is a :class:`LiveEngineBrowser`. The caller is
        responsible for ``engine.play(playlist)`` and ``engine.stop()`` —
        this loop does not own the engine lifecycle.
    emit:
        Async callable used to send agent responses back to the browser.
        The engine's own events are emitted via the engine's emitter,
        not through this function.
    command_queue:
        Stream of dicts. Each dict is either an engine event
        (``{"type": "track_started", ...}`` etc.) — forwarded by the WS
        handler from the engine's emitter — or a user command
        (``{"type": "user_msg", "text": "..."}`` /
        ``{"type": "quit"}``). The loop ends on ``quit`` or
        ``session_ended``.
    max_idle_loops:
        Test-only escape hatch. When given, the loop exits after this
        many empty drains. Production callers leave this ``None`` so the
        loop runs until ``session_ended`` or ``quit``.
    """
    # Deferred import — pipeline imports run.py which imports tools.py which
    # imports live_dj.py, so we have to break the cycle here as well.
    from web.backend.pipeline import run_agent_streaming  # noqa: PLC0415

    context_variables["_engine"] = engine

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Live session started.\n" + _playlist_summary(playlist)
            ),
        },
        {"role": "assistant", "content": "On deck. Let's go."},
    ]

    idle_loops = 0
    try:
        while True:
            events: list[dict] = []
            user_inputs: list[str] = []
            quit_requested = False

            # Block briefly waiting for the first item, then drain any others
            # that already piled up so a burst of pings produces one agent
            # turn instead of one turn per ping.
            try:
                first = await asyncio.wait_for(command_queue.get(), timeout=0.2)
                _classify(first, events, user_inputs)
                if first.get("type") == "quit":
                    quit_requested = True
            except asyncio.TimeoutError:
                pass

            while not command_queue.empty():
                try:
                    item = command_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                _classify(item, events, user_inputs)
                if item.get("type") == "quit":
                    quit_requested = True

            if quit_requested:
                break

            if any(e.get("type") == SESSION_ENDED for e in events):
                # Surface the closing event so the WS handler can cleanup.
                break

            if not events and not user_inputs:
                idle_loops += 1
                if max_idle_loops is not None and idle_loops >= max_idle_loops:
                    break
                continue
            idle_loops = 0

            content = _format_turn(events, user_inputs, engine.get_state())
            messages.append({"role": "user", "content": content})

            # Diagnostic — surfaces in backend.log so we can see WHEN the
            # agent loop actually invokes the LLM and what comes back.
            # Trims the content preview to keep the log readable.
            # ``.encode('ascii', 'replace')`` defangs the Windows-cp1252
            # console: LLM output regularly contains arrows / em-dashes
            # that aren't in cp1252 and otherwise raise UnicodeEncodeError
            # mid-loop, crashing phase_live entirely.
            def _ascii(s: str) -> str:
                return (s or "").encode("ascii", "replace").decode("ascii")
            evt_types = [e.get("type") for e in events]
            print(
                f"[live_dj] turn: events={evt_types} user_inputs={len(user_inputs)} "
                f"content_preview={_ascii(content[:120])!r}",
                flush=True,
            )

            # Forward to LLM. The streaming runner publishes its own
            # text_delta / tool_call / tool_result events via emit, so we
            # only need to add a final assistant chat marker.
            try:
                response = await run_agent_streaming(
                    _LIVE_DJ_SYSTEM,
                    _LIVE_TOOLS,
                    messages,
                    context_variables,
                    emit,
                    max_turns=5,
                )
            except Exception as exc:  # noqa: BLE001 — surface to UI
                print(
                    f"[live_dj] run_agent_streaming RAISED: "
                    f"{type(exc).__name__}: {_ascii(str(exc))}",
                    flush=True,
                )
                await emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                response = ""

            print(
                f"[live_dj] turn done: response_len={len(response) if response else 0} "
                f"preview={_ascii(response[:120] if response else '')!r}",
                flush=True,
            )

            if response:
                messages.append({"role": "assistant", "content": response})
                await emit({"type": "live_message", "role": "assistant", "content": response})
    finally:
        context_variables.pop("_engine", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(item: dict, events: list[dict], user_inputs: list[str]) -> None:
    """Sort a queue item into either the engine-events bucket or the
    user-inputs bucket. The async loop fans both into one
    :func:`_format_turn` call so the LLM sees a unified context.

    v2.5.2 adds two synthetic event types — ``environment_changed``
    (from the perception buffer) and ``audience_request_batch`` (from
    the batched chat). Both are treated like engine events: they appear
    in the formatted turn and trigger an LLM call.
    """
    item_type = item.get("type")
    if item_type == "user_msg":
        text = (item.get("text") or "").strip()
        if text:
            user_inputs.append(text)
    elif item_type in {
        TRACK_STARTED,
        APPROACHING_CF,
        CROSSFADE_TRIGGERED,
        CROSSFADE_FINISHED,
        TRACK_ENDED,
        SESSION_ENDED,
        PLAYLIST_RUNNING_LOW,
        ENDLESS_WARNING,
        "environment_changed",
        "audience_request_batch",
    }:
        events.append(item)
    # Anything else (e.g. ``engine_command`` UI hints) is browser-only and
    # the agent doesn't need to see it.


def _stdin_reader(q: Queue) -> None:
    """Blocking stdin reader — runs in a daemon thread."""
    while True:
        try:
            line = input("You: ").strip()
            if line:
                q.put(line)
        except (EOFError, KeyboardInterrupt):
            break


def _drain(q: Queue, limit: int = 64) -> list[Any]:
    """Non-blocking drain of a Queue, up to `limit` items."""
    items = []
    for _ in range(limit):
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items


def _format_turn(
    events: list[dict], user_inputs: list[str], state: dict
) -> str:
    """Build the user-role message for one agent turn from events + input."""
    parts: list[str] = []

    if events:
        parts.append("=== Engine events ===")
        for ev in events:
            parts.append(_format_event(ev))

    if user_inputs:
        parts.append("=== Listener ===")
        for u in user_inputs:
            parts.append(f"  > {u}")

    parts.append("=== Current state ===")
    cur = state.get("current_track") or {}
    parts.append(
        f"  {cur.get('display_name','?')} | "
        f"{cur.get('bpm','?')} BPM | {cur.get('camelot_key','?')} | "
        f"{state.get('position_sec','?')}s | "
        f"CF in {state.get('seconds_to_crossfade','?')}s | "
        f"{state.get('playlist_remaining','?')} tracks left"
    )
    return "\n".join(parts)


def _format_event(ev: dict) -> str:
    t = ev["type"]
    if t == TRACK_STARTED:
        tr = ev.get("track") or {}
        return f"  TRACK_STARTED: '{tr.get('display_name','?')}' ({tr.get('bpm','?')} BPM, {tr.get('camelot_key','?')})"
    if t == APPROACHING_CF:
        tr = ev.get("track") or {}
        nx = ev.get("next_track") or {}
        sec = ev.get("seconds_remaining", "?")
        # v3.3 — surface the chosen crossfade move so the LLM can
        # narrate non-smooth moves to the audience BEFORE they hit.
        # smooth_blend is the default / boring case; calling it out
        # every time would pollute the chat. Only flag the "moves".
        pl = ev.get("phase_lock") or {}
        style = pl.get("transition_style")
        style_hint = ""
        if style and style != "smooth_blend":
            extras = []
            if style == "bass_swap":
                bs = pl.get("bass_swap") or {}
                drop_at = bs.get("drop_at_incoming_sec")
                if drop_at is not None:
                    extras.append(f"drop @ {float(drop_at):.1f}s in")
            style_hint = (
                f"  → MOVE: '{style}'"
                + (f" ({', '.join(extras)})" if extras else "")
                + "  ← consider narrating this in chat before the cf"
            )
        return (
            f"  APPROACHING_CF in {sec}s: "
            f"'{tr.get('display_name','?')}' → '{nx.get('display_name','?')}' "
            f"({tr.get('bpm','?')}→{nx.get('bpm','?')} BPM, "
            f"{tr.get('camelot_key','?')}→{nx.get('camelot_key','?')})"
            + (("\n" + style_hint) if style_hint else "")
        )
    if t == CROSSFADE_TRIGGERED:
        fr = ev.get("from_track") or {}
        to = ev.get("to_track") or {}
        return f"  CROSSFADE_TRIGGERED: '{fr.get('display_name','?')}' → '{to.get('display_name','?')}'"
    if t == CROSSFADE_FINISHED:
        fr = ev.get("from_track") or {}
        to = ev.get("to_track") or {}
        return f"  CROSSFADE_FINISHED: now on '{to.get('display_name','?')}' (was '{fr.get('display_name','?')}')"
    if t == TRACK_ENDED:
        tr = ev.get("track") or {}
        return f"  TRACK_ENDED: '{tr.get('display_name','?')}'"
    if t == SESSION_ENDED:
        return "  SESSION_ENDED"
    if t == PLAYLIST_RUNNING_LOW:
        tr = ev.get("track") or {}
        sec = ev.get("seconds_remaining", "?")
        return (
            f"  PLAYLIST_RUNNING_LOW in {sec}s on "
            f"'{tr.get('display_name','?')}' — pick a continuation track and "
            "call extend_set(track_id) within 5 s or the engine will auto-pick."
        )
    if t == ENDLESS_WARNING:
        return f"  ENDLESS_WARNING: {ev.get('reason','?')} — {ev.get('message','')}"
    if t == "environment_changed":
        delta = ev.get("rms_db_delta")
        mean = ev.get("rms_db_mean")
        voice = ev.get("voice_likelihood")
        parts = ["  ENVIRONMENT_CHANGED:"]
        if delta is not None:
            parts.append(f" rms_db_delta={float(delta):+.1f}")
        if mean is not None:
            parts.append(f" rms_db_mean={float(mean):.1f}")
        if voice is not None:
            parts.append(f" voice_likelihood={float(voice):.2f}")
        return "".join(parts)
    if t == "audience_request_batch":
        reqs = ev.get("requests") or []
        lines = [f"  AUDIENCE_REQUEST_BATCH ({len(reqs)} requests):"]
        for r in reqs:
            lines.append(f"    > {r.get('text','')}")
        return "\n".join(lines)
    return f"  {t}: {ev}"


def _playlist_summary(playlist: list[dict]) -> str:
    lines = [f"Playlist ({len(playlist)} tracks):"]
    for i, t in enumerate(playlist, 1):
        lines.append(
            f"  {i}. {t.get('display_name','?')} — {t.get('bpm','?')} BPM, {t.get('camelot_key','?')}"
        )
    return "\n".join(lines)
