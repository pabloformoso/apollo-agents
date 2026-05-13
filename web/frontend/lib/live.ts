"use client";
/**
 * useLiveSession — bridge between the browser audio elements and the
 * v2.5.1 ``/ws/live/{id}`` backend WebSocket.
 *
 * The backend's ``LiveEngineBrowser`` maintains the playlist state machine
 * but never reads or writes audio — it relies on the browser to drive
 * playback. This hook owns:
 *
 *   - Two ``HTMLAudioElement`` "decks" (deck A / deck B). The active deck
 *     plays the current track; the inactive deck is loaded with the next
 *     track ahead of time so a crossfade is just a gain ramp.
 *   - A single ``AudioContext`` with two ``GainNode``s wired to it so the
 *     crossfade is sample-accurate without having to swap audio elements
 *     mid-blend.
 *   - State derived from server engine events (``track_started`` /
 *     ``approaching_crossfade`` / ``crossfade_*`` / ``track_ended`` /
 *     ``session_ended``) plus the running countdown to the next crossfade
 *     based on the active deck's ``currentTime``.
 *   - A throttled ``playback_pos`` ping back to the server every ~250 ms
 *     so the engine knows where the browser is in the track. The interval
 *     is set up in a ``useEffect`` cleanup pair (canonical v2.4 pattern —
 *     no setState inside the effect, no ref writes during render).
 *
 * The active deck's ``audioRef`` is exposed as a stable ref so the
 * v2.5.3 ``<VisualLayer>`` can subscribe to the same audio element without
 * prop drilling through a tower of providers.
 */

import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { getToken } from "./auth";
import { streamUrl } from "./api";

export type LiveEngineState = "idle" | "playing" | "crossfading" | "ended";

export interface LiveTrackSummary {
  id: string;
  display_name: string;
  bpm?: number | null;
  camelot_key?: string | null;
  duration_sec?: number | null;
  /** Optional precomputed beatgrid — populated when the catalog has it.
   * Consumed by the v2.5.3 ``<VisualLayer>`` for sample-accurate beat sync.
   * Tracks without a beatgrid fall back to AnalyserNode onset detection. */
  beatgrid?: { bpm: number; first_beat_sec: number } | null;
}

export interface LiveCommandLogEntry {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

export interface DjChatEntry {
  text: string;
  ts: number;
}

export interface UseLiveSessionApi {
  state: LiveEngineState;
  connected: boolean;
  currentTrack: LiveTrackSummary | null;
  nextTrack: LiveTrackSummary | null;
  secondsToCrossfade: number;
  playlistRemaining: number;
  playlist: LiveTrackSummary[];
  /** 1-based position of the current track in the playlist (0 if unknown). */
  currentPosition: number;
  /** Elapsed seconds within the active deck's current track (throttled ~250ms). */
  currentTrackTime: number;
  /** Duration of the active deck's current track (best-effort, may be 0). */
  currentTrackDuration: number;
  log: LiveCommandLogEntry[];
  /**
   * Append-only feed of ``dj_chat`` messages emitted by the agent via the
   * v2.5.2 ``emit_chat`` tool. The UI surfaces these in the LiveStage
   * "DJ chat" panel so the audience sees rejection / acknowledgement text.
   */
  djChat: DjChatEntry[];
  error: string | null;
  /** True when the browser blocked autoplay; the UI must surface a click-to-start. */
  autoplayBlocked: boolean;
  /** Active deck — exposed as a stable ref for the future `<VisualLayer>`. */
  audioRef: React.RefObject<HTMLAudioElement | null>;
  /** Send a control command to the backend agent. */
  sendCommand: (cmd: LiveCommand) => void;
  /** Send free-text user message to the agent. */
  sendUserMessage: (text: string) => void;
  /**
   * Low-level publish escape hatch used by v2.5.2 mic perception. Sends the
   * message verbatim — the WS handler dispatches by ``type``. Avoid in
   * application code; prefer ``sendCommand`` / ``sendUserMessage``.
   */
  sendRaw: (message: Record<string, unknown>) => void;
  /** Resume playback after autoplay was blocked — must be called from a user gesture. */
  resumePlayback: () => void;
  /** Quit the live session — closes the WS, stops audio, releases mic etc. */
  quit: () => void;
  // v2.6.0 — endless / improvisation mode (YouTube-streaming use case).
  /** Server-confirmed endless-mode flag. Mirrors session.context_variables.endless_mode. */
  endlessMode: boolean;
  /** True between PLAYLIST_RUNNING_LOW and the next track_started — UI surfaces a banner. */
  playlistRunningLow: boolean;
  /** Toggle endless mode. Sends a WS command; the server echoes the new state. */
  setEndlessMode: (enabled: boolean) => void;
  // v2.7 — YouTube Live Chat ingest status, surfaced as a pill in the /live header.
  /** Compact view-model the UI binds to. ``state === "off"`` means no events arrived yet
   *  (either the operator hasn't linked YT or the backend isn't configured); the UI uses
   *  that to suppress the pill on plain `/live` sessions. */
  youtube: {
    state: "off" | "connected" | "no_broadcast" | "quota_exceeded" | "disconnected" | "error";
    broadcastTitle?: string;
    reason?: string;
  };
}

export type LiveCommand =
  | { type: "skip" }
  | { type: "stay" }
  | { type: "more_energetic" }
  | { type: "wind_down" };

interface ServerEngineCommand {
  type: "engine_command";
  command:
    | "load"
    | "skip"
    | "crossfade"
    | "queue_swap"
    | "stop"
    /** v2.5.0.1 — release the active deck so the next ``load`` starts cleanly. */
    | "stop_deck";
  track?: LiveTrackSummary;
  to_track?: LiveTrackSummary;
  from_track?: LiveTrackSummary;
  position?: number;
  crossfade_sec?: number;
}

interface ServerLiveStateMessage {
  type: "live_state";
  data: {
    session_id: string;
    playlist: LiveTrackSummary[];
    engine_state: {
      state: LiveEngineState;
      position_sec: number;
      current_track: LiveTrackSummary | null;
      next_track: LiveTrackSummary | null;
      seconds_to_crossfade: number;
      playlist_remaining: number;
    };
  };
}

interface ServerEngineEvent {
  type:
    | "track_started"
    | "approaching_crossfade"
    | "crossfade_triggered"
    | "crossfade_finished"
    | "track_ended"
    | "session_ended"
    | "playlist_running_low"
    | "endless_warning";
  track?: LiveTrackSummary;
  next_track?: LiveTrackSummary;
  from_track?: LiveTrackSummary;
  to_track?: LiveTrackSummary;
  seconds_remaining?: number;
  /**
   * v2.5.2 — authoritative crossfade-trigger position (seconds within the
   * track). Carried by ``track_started`` and ``approaching_crossfade`` so
   * the frontend can derive a live-ticking countdown from the deck's
   * ``currentTime`` instead of freezing on the single-emit
   * ``seconds_remaining`` value. ``null`` / undefined when the engine
   * hasn't computed a target yet (e.g. last track, or duration unknown).
   */
  cf_point_sec?: number | null;
  /** v2.6.0 endless-mode warning payload (cap reached, no candidates). */
  reason?: string;
  message?: string;
}

interface ServerEndlessModeMessage {
  type: "endless_mode";
  enabled: boolean;
}

// v2.7 — YouTube Live Chat status updates emitted by the backend. The
// state machine is intentionally small: the frontend only renders a
// pill colour + tooltip, so a flat string is enough.
interface ServerYouTubeStatusMessage {
  type: "youtube_status";
  state:
    | "connected"          // poller running, broadcast attached
    | "no_broadcast"       // creds OK but no active YT live event
    | "quota_exceeded"     // backend is backing off; no action needed
    | "disconnected"       // token revoked / broadcast ended
    | "error";
  broadcast?: { id: string; title: string };
  reason?: string;
}

interface ServerLiveMessage {
  type: "live_message";
  role: "user" | "assistant";
  content: string;
}

interface ServerDjChat {
  type: "dj_chat";
  text: string;
}

interface ServerError {
  type: "error";
  message: string;
}

type ServerEvent =
  | ServerLiveStateMessage
  | ServerEngineEvent
  | ServerEngineCommand
  | ServerLiveMessage
  | ServerDjChat
  | ServerEndlessModeMessage
  | ServerYouTubeStatusMessage
  | ServerError;

const COMMAND_TEXT: Record<LiveCommand["type"], string> = {
  skip: "skip",
  stay: "stay",
  more_energetic: "more energetic",
  wind_down: "wind down",
};

function deriveWsBase(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_BASE;
  if (explicit) return explicit;
  const apiBase = process.env.NEXT_PUBLIC_API_BASE;
  if (apiBase) return apiBase.replace(/^http/, "ws");
  return "ws://localhost:4020";
}

const WS_BASE = deriveWsBase();
const PLAYBACK_POS_INTERVAL_MS = 250;

/**
 * v2.7.2 — options object accepted by ``useLiveSession``.
 *
 * ``viewer: true`` switches the hook into a read-only consumer of the
 * session's engine event bus (used by the OBS Browser Source embed
 * route). Viewer mode:
 *  - connects to ``/api/sessions/{id}/live/viewer`` instead of the
 *    primary ``/live/stream`` endpoint,
 *  - suppresses all outbound messages (``playback_pos``, ``user_msg``,
 *    ``perception``, ``set_endless_mode``, ``quit``) — the backend
 *    handler ignores anything a viewer sends anyway, but we save the
 *    network round-trips,
 *  - still plays audio locally so OBS captures it from the Browser
 *    Source, and still derives state from incoming events so the
 *    visualizer renders correctly.
 */
export interface UseLiveSessionOptions {
  viewer?: boolean;
}

export function useLiveSession(
  sessionId: string | null,
  options: UseLiveSessionOptions = {},
): UseLiveSessionApi {
  const viewerMode = options.viewer === true;
  // ``viewerMode`` is fixed for the lifetime of the hook (an embed
  // page never flips to operator), but stable closures (ensureDeck,
  // setEndlessModeWS, …) are created once and need a ref to see it.
  const viewerModeRef = useRef(viewerMode);
  viewerModeRef.current = viewerMode;
  // ── Refs (audio + WS plumbing) ──────────────────────────────────────────
  const wsRef = useRef<WebSocket | null>(null);
  const deckARef = useRef<HTMLAudioElement | null>(null);
  const deckBRef = useRef<HTMLAudioElement | null>(null);
  const activeDeckRef = useRef<"a" | "b">("a");
  const audioCtxRef = useRef<AudioContext | null>(null);
  const gainARef = useRef<GainNode | null>(null);
  const gainBRef = useRef<GainNode | null>(null);
  // Stable handle the visualizer can subscribe to. Always points at the
  // currently active deck, swapping atomically on crossfade.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentTrackIdRef = useRef<string | null>(null);

  // ── State (derived from engine events) ──────────────────────────────────
  const [state, setState] = useState<LiveEngineState>("idle");
  const [connected, setConnected] = useState(false);
  const [currentTrack, setCurrentTrack] = useState<LiveTrackSummary | null>(null);
  const [explicitNextTrack, setExplicitNextTrack] = useState<LiveTrackSummary | null>(null);
  const [playlist, setPlaylist] = useState<LiveTrackSummary[]>([]);
  const [playlistRemaining, setPlaylistRemaining] = useState(0);
  const [log, setLog] = useState<LiveCommandLogEntry[]>([]);
  const [djChat, setDjChat] = useState<DjChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const [currentTrackTime, setCurrentTrackTime] = useState(0);
  const [currentTrackDuration, setCurrentTrackDuration] = useState(0);
  // v2.5.2 — authoritative crossfade-trigger time within the active deck's
  // track, populated by ``track_started`` / ``approaching_crossfade`` events
  // (the engine sends ``cf_point_sec``). The displayed countdown is
  // derived from this minus the live ``currentTrackTime`` so it ticks down
  // every 250 ms instead of freezing on a single emit. Falls back to a
  // legacy seconds_remaining value when the server hasn't sent
  // ``cf_point_sec`` yet (older backend).
  const [cfTargetSec, setCfTargetSec] = useState<number | null>(null);
  const [legacySecsToCf, setLegacySecsToCf] = useState<number | null>(null);
  // v2.6.0 endless mode mirror state. Defaults to false; server confirms
  // on every `set_endless_mode` write via an `endless_mode` echo event.
  const [endlessMode, setEndlessMode] = useState(false);
  // True from PLAYLIST_RUNNING_LOW until the next track_started — drives
  // the "picking continuation track…" banner on /live.
  const [playlistRunningLow, setPlaylistRunningLow] = useState(false);
  // v2.7 — YouTube Live Chat status pill state. Defaults to "off" so
  // we don't render the pill at all on plain `/live` sessions where YT
  // isn't configured server-side.
  const [youtube, setYoutube] = useState<{
    state: "off" | "connected" | "no_broadcast" | "quota_exceeded" | "disconnected" | "error";
    broadcastTitle?: string;
    reason?: string;
  }>({ state: "off" });

  // v2.7.0 — HTTP probe so the pill renders immediately on /live mount
  // without waiting for a WS event. The live WS only emits
  // ``youtube_status`` for sessions that successfully open the live
  // channel, which can race with the page's first paint. Probing
  // ``/api/youtube/status`` directly gives a deterministic initial
  // state: 404 → feature disabled server-side (leave state "off");
  // 200 + connected:false → "disconnected" (pill renders, clicking
  // starts OAuth); 200 + connected:true → "connected".
  // Server-emitted WS events still win — they're the source of truth
  // for live broadcast attachment — but this seeds the initial render.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;
    void import("./api").then(({ getYouTubeStatus }) => {
      getYouTubeStatus()
        .then((status) => {
          if (cancelled) return;
          if ("connected" in status && status.connected) {
            setYoutube({
              state: "connected",
              broadcastTitle: status.channel_title,
            });
          } else if ("connected" in status && !status.connected) {
            setYoutube({ state: "disconnected" });
          }
        })
        .catch(() => {
          // Network / 404 — leave as "off" so the pill stays hidden.
        });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Derive next track from the playlist + current track position. This is
  // robust to event-ordering races where ``track_started`` fires before any
  // ``approaching_crossfade`` (so the explicit next_track payload is null).
  // Falls back to the explicit value carried by ``approaching_crossfade`` /
  // ``live_state`` when the current track isn't found in the playlist (e.g.
  // before ``live_state`` lands).
  const currentPosition = useMemo(() => {
    if (!currentTrack || playlist.length === 0) return 0;
    const idx = playlist.findIndex((t) => t.id === currentTrack.id);
    return idx >= 0 ? idx + 1 : 0;
  }, [currentTrack, playlist]);
  const nextTrack = useMemo<LiveTrackSummary | null>(() => {
    if (!currentTrack || playlist.length === 0) return explicitNextTrack;
    const idx = playlist.findIndex((t) => t.id === currentTrack.id);
    if (idx < 0) return explicitNextTrack;
    return idx + 1 < playlist.length ? playlist[idx + 1] : null;
  }, [currentTrack, playlist, explicitNextTrack]);

  // v2.5.2 — live-ticking countdown.
  //
  // Bug A1 (v2.5.1): the backend's ``approaching_crossfade`` event fires
  // exactly once when crossing the warn threshold, so the previous code
  // (which set ``secondsToCrossfade`` from the event payload alone) was
  // frozen at whatever value arrived first — typically 30 s, sometimes 0
  // when the threshold raced with the trigger. The fix derives the
  // displayed countdown from ``cfTargetSec - currentTrackTime`` so it
  // ticks down every 250 ms (matching the playback_pos interval).
  //
  // Fallback chain:
  //   1. Authoritative: ``cfTargetSec - currentTrackTime``.
  //   2. Legacy server snapshot (``seconds_to_crossfade`` from
  //      ``live_state`` or ``seconds_remaining`` from
  //      ``approaching_crossfade``) when an older backend doesn't yet
  //      send ``cf_point_sec``.
  //   3. Zero (no crossfade scheduled — last track or duration unknown).
  const secondsToCrossfade = useMemo<number>(() => {
    if (cfTargetSec !== null && cfTargetSec > 0) {
      return Math.max(0, cfTargetSec - currentTrackTime);
    }
    if (legacySecsToCf !== null) return Math.max(0, legacySecsToCf);
    return 0;
  }, [cfTargetSec, currentTrackTime, legacySecsToCf]);

  const appendLog = useCallback((entry: LiveCommandLogEntry) => {
    setLog((l) => [...l, entry]);
  }, []);

  // ── Audio plumbing helpers (declared first so the useEffectEvent
  //    wrappers below can reference them in module-source order — the v7
  //    react-hooks/immutability rule rejects forward references). ─────────

  const ensureAudioContext = useCallback(() => {
    if (audioCtxRef.current) return audioCtxRef.current;
    if (typeof window === "undefined") return null;
    const Ctor =
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext ?? window.AudioContext;
    if (!Ctor) return null;
    const ctx = new Ctor();
    audioCtxRef.current = ctx;
    // Diagnostic — Chromium suspends the AudioContext silently when the
    // tab is backgrounded/idle. The HTMLAudioElement keeps advancing
    // currentTime (so the playback_pos pings + crossfade timer keep
    // ticking) but the gain nodes stop passing samples to the speakers
    // — exactly the "music gone, everything else fine" symptom. Log the
    // state changes and try to auto-resume so the user gets sound back
    // without having to refresh. Guarded for jsdom test envs whose
    // AudioContext mock omits ``addEventListener``.
    if (typeof ctx.addEventListener === "function") {
      ctx.addEventListener("statechange", () => {
        appendLog({
          role: "assistant",
          text: `[audioctx] state=${ctx.state}`,
          ts: Date.now(),
        });
        if (ctx.state === "suspended") {
          try {
            const p = ctx.resume();
            if (p && typeof p.then === "function") {
              p.then(
                () => {
                  appendLog({
                    role: "assistant",
                    text: "[audioctx] auto-resume ok",
                    ts: Date.now(),
                  });
                },
                (err) => {
                  appendLog({
                    role: "assistant",
                    text: `[audioctx] auto-resume failed: ${
                      (err as { name?: string })?.name ?? "Error"
                    }`,
                    ts: Date.now(),
                  });
                },
              );
            }
          } catch {
            /* ignore — best effort */
          }
        }
      });
    }
    return ctx;
  }, [appendLog]);

  const ensureDeck = useCallback(
    (which: "a" | "b") => {
      const refObj = which === "a" ? deckARef : deckBRef;
      if (refObj.current) return refObj.current;
      if (typeof window === "undefined") return null;
      const el = new Audio();
      el.preload = "auto";
      el.crossOrigin = "anonymous";
      refObj.current = el;

      // v2.5.0.1 — natural end-of-track notification.
      //
      // When `<audio>` finishes its buffer it fires ``ended``, pauses, and
      // freezes ``currentTime``. The 250 ms ``playback_pos`` interval keeps
      // pinging the same value to the backend, which never crosses the
      // crossfade threshold — so the engine never advances. The fix is to
      // forward ``ended`` as a synthetic ``track_ended`` WS message; the
      // backend's ``LiveEngineBrowser.report_track_ended`` then advances
      // the cursor and emits ``track_started`` for the next track.
      //
      // Only the *active* deck's ``ended`` matters. The inactive deck
      // also fires ``ended`` mid-set if a previous src plays past the
      // crossfade — guarding on ``activeDeckRef.current`` keeps the
      // synthetic event tied to the track the user is hearing.
      el.addEventListener("ended", () => {
        if (activeDeckRef.current !== which) return;
        // Viewers don't drive the engine — the primary's ``track_ended``
        // already advances the cursor and the viewer will receive the
        // resulting ``engine_command load`` like any other event.
        if (viewerModeRef.current) return;
        const ws = wsRef.current;
        const tid = currentTrackIdRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN || !tid) return;
        try {
          ws.send(JSON.stringify({ type: "track_ended", track_id: tid }));
        } catch {
          /* ignore — backend has the endgame safeguard as a fallback */
        }
      });

      // Diagnostic listeners — surface buffer / pause / error / mute /
      // device events into the LiveStage log so silent stalls (HTTP
      // stream socket dropping mid-track, OS audio output disconnecting,
      // tab muted via Chrome's tab-mute icon) are visible. Only the
      // *active* deck's events are logged to keep the panel readable.
      const DIAG_EVENTS = [
        "stalled",
        "waiting",
        "suspend",
        "pause",
        "playing",
        "error",
        "volumechange",
        "ratechange",
        "emptied",
      ] as const;
      for (const evt of DIAG_EVENTS) {
        el.addEventListener(evt, () => {
          if (activeDeckRef.current !== which) return;
          const ct = Number.isFinite(el.currentTime) ? el.currentTime : 0;
          const ns = el.networkState;
          const rs = el.readyState;
          const buffered =
            el.buffered && el.buffered.length > 0
              ? el.buffered.end(el.buffered.length - 1)
              : 0;
          const errCode = el.error ? el.error.code : null;
          const extras: string[] = [];
          if (evt === "volumechange") {
            extras.push(`vol=${el.volume}`, `muted=${el.muted}`);
          } else if (evt === "ratechange") {
            extras.push(`rate=${el.playbackRate}`);
          }
          appendLog({
            role: "assistant",
            text:
              `[deck ${which}] ${evt} @ ${ct.toFixed(1)}s ` +
              `(net=${ns} ready=${rs} buf=${buffered.toFixed(1)}s` +
              (errCode !== null ? ` errCode=${errCode}` : "") +
              (extras.length ? ` ${extras.join(" ")}` : "") +
              ")",
            ts: Date.now(),
          });
        });
      }

      const ctx = ensureAudioContext();
      if (ctx) {
        try {
          const source = ctx.createMediaElementSource(el);
          const gain = ctx.createGain();
          gain.gain.value = which === "a" ? 1 : 0;
          source.connect(gain).connect(ctx.destination);
          if (which === "a") gainARef.current = gain;
          else gainBRef.current = gain;
        } catch {
          // Some test environments don't implement Web Audio fully —
          // playback still works through the <audio> element directly.
        }
      }
      return el;
    },
    [ensureAudioContext, appendLog],
  );

  const loadIntoActiveDeck = useCallback(
    async (track: LiveTrackSummary) => {
      const which = activeDeckRef.current;
      const el = ensureDeck(which);
      if (!el) return;
      audioRef.current = el;
      el.src = streamUrl(track.id);
      // v2.5.0.1 — defensive gain restore. After a crossfade the
      // previously-inactive deck's gain was ramped down to 0; if a
      // ``load`` (rather than another ``crossfade``) is the next event
      // (e.g. the engine advanced via ``track_ended``), the new track
      // would play silently. Reset both Web Audio gain (when wired) and
      // the element-level volume so playback is audible regardless of
      // path.
      const ctx = ensureAudioContext();
      const gain = which === "a" ? gainARef.current : gainBRef.current;
      if (ctx && gain) {
        try {
          gain.gain.cancelScheduledValues(ctx.currentTime);
          gain.gain.setValueAtTime(1, ctx.currentTime);
        } catch {
          /* ignore */
        }
      }
      el.volume = 1;
      try {
        await el.play();
        setAutoplayBlocked(false);
      } catch (err) {
        // Distinguish "browser blocked autoplay" (NotAllowedError — UI must
        // surface a click-to-start overlay) from "media failed to load"
        // (NotSupportedError / TypeError — no overlay would help, the src
        // is broken). Anything we can't classify is treated as autoplay
        // gating because that's the user-recoverable case.
        const name = (err as { name?: string })?.name ?? "";
        if (name === "NotAllowedError" || name === "" || name === "AbortError") {
          console.warn("[live] autoplay blocked on load:", err);
          setAutoplayBlocked(true);
        } else {
          console.warn("[live] play() failed on load (non-recoverable):", err);
        }
      }
      currentTrackIdRef.current = track.id;
    },
    [ensureDeck, ensureAudioContext],
  );

  const hardCutToTrack = useCallback(
    async (track: LiveTrackSummary) => {
      // For a hard cut we can simply load the new src into the active
      // deck — there's no blend to preserve.
      await loadIntoActiveDeck(track);
    },
    [loadIntoActiveDeck],
  );

  const crossfadeToNext = useCallback(
    async (track: LiveTrackSummary, crossfadeSec: number) => {
      // Load the incoming track on the inactive deck, ramp the gains.
      const fromWhich = activeDeckRef.current;
      const toWhich = fromWhich === "a" ? "b" : "a";
      const ctx = ensureAudioContext();
      const fromEl = ensureDeck(fromWhich);
      const toEl = ensureDeck(toWhich);
      if (!fromEl || !toEl) return;
      toEl.src = streamUrl(track.id);
      try {
        await toEl.play();
        setAutoplayBlocked(false);
      } catch (err) {
        const name = (err as { name?: string })?.name ?? "";
        if (name === "NotAllowedError" || name === "" || name === "AbortError") {
          console.warn("[live] autoplay blocked on crossfade:", err);
          setAutoplayBlocked(true);
        } else {
          console.warn("[live] play() failed on crossfade (non-recoverable):", err);
        }
      }

      const gainFrom =
        fromWhich === "a" ? gainARef.current : gainBRef.current;
      const gainTo = toWhich === "a" ? gainARef.current : gainBRef.current;
      if (ctx && gainFrom && gainTo) {
        const now = ctx.currentTime;
        gainFrom.gain.cancelScheduledValues(now);
        gainTo.gain.cancelScheduledValues(now);
        gainFrom.gain.setValueAtTime(gainFrom.gain.value, now);
        gainTo.gain.setValueAtTime(gainTo.gain.value, now);
        gainFrom.gain.linearRampToValueAtTime(0, now + crossfadeSec);
        gainTo.gain.linearRampToValueAtTime(1, now + crossfadeSec);
      } else {
        // No Web Audio: fall back to volume ramp on the audio elements.
        toEl.volume = 1;
        fromEl.volume = 0;
      }

      activeDeckRef.current = toWhich;
      audioRef.current = toEl;
      currentTrackIdRef.current = track.id;
    },
    [ensureAudioContext, ensureDeck],
  );

  const stopAllDecks = useCallback(() => {
    for (const ref of [deckARef, deckBRef]) {
      const el = ref.current;
      if (el) {
        try {
          el.pause();
          el.removeAttribute("src");
          el.load();
        } catch {
          /* ignore */
        }
      }
    }
    audioRef.current = null;
    currentTrackIdRef.current = null;
  }, []);

  // ── useEffectEvent wrappers ─────────────────────────────────────────────
  // These read the latest `setState` / helper closures every render but
  // their identity stays stable from the WS effect's perspective, so the
  // effect doesn't re-run on each parent render.

  const handleEngineCommand = useEffectEvent((evt: ServerEngineCommand) => {
    const { command } = evt;
    if (command === "load" && evt.track) {
      void loadIntoActiveDeck(evt.track);
    } else if (command === "skip" && evt.track) {
      void hardCutToTrack(evt.track);
    } else if (command === "crossfade" && evt.to_track) {
      void crossfadeToNext(evt.to_track, evt.crossfade_sec ?? 12);
    } else if (command === "stop_deck") {
      // v2.5.0.1 — release just the active deck (not both) so the next
      // ``load`` plays into a fresh element and the previous track's
      // ``ended`` fallback can't re-fire.
      const which = activeDeckRef.current;
      const el = which === "a" ? deckARef.current : deckBRef.current;
      if (el) {
        try {
          el.pause();
          el.removeAttribute("src");
          el.load();
        } catch {
          /* ignore */
        }
      }
    } else if (command === "stop") {
      stopAllDecks();
    }
    // ``queue_swap`` is purely UI metadata in v2.5.1 — the next
    // ``track_started`` will pick up the new track when the engine gets
    // there. No deck action needed now.
  });

  const onServerEvent = useEffectEvent((evt: ServerEvent) => {
    switch (evt.type) {
      case "live_state": {
        setPlaylist(evt.data.playlist || []);
        const es = evt.data.engine_state;
        setState(es.state);
        if (es.current_track) setCurrentTrack(es.current_track);
        if (es.next_track) setExplicitNextTrack(es.next_track);
        // Initial hint — until a ``track_started`` (or
        // ``approaching_crossfade``) lands with ``cf_point_sec``, we use
        // the engine's snapshot value. Once the engine sends an
        // authoritative cf target, the live-ticking derivation takes over.
        setLegacySecsToCf(es.seconds_to_crossfade);
        setPlaylistRemaining(es.playlist_remaining);
        break;
      }
      case "track_started": {
        if (evt.track) {
          setCurrentTrack(evt.track);
          currentTrackIdRef.current = evt.track.id;
          setState("playing");
          setCurrentTrackTime(0);
          setCurrentTrackDuration(0);
          // v2.5.2 — engine emits the authoritative crossfade-trigger
          // time so the countdown can tick live from the deck's
          // ``currentTime``. ``cf_point_sec`` may be null when the engine
          // is on the final track (no successor — no crossfade).
          if (typeof evt.cf_point_sec === "number") {
            setCfTargetSec(evt.cf_point_sec);
          } else {
            setCfTargetSec(null);
          }
          // Reset legacy fallback so a stale seconds_remaining from the
          // previous track doesn't bleed into the new one's countdown.
          setLegacySecsToCf(null);
          // v2.6.0 — clear the endless-mode "running low" banner once
          // we're on the new (appended) track. Engine will re-fire
          // playlist_running_low when this one approaches its own CF.
          setPlaylistRunningLow(false);
        }
        break;
      }
      case "approaching_crossfade": {
        if (evt.next_track) setExplicitNextTrack(evt.next_track);
        if (typeof evt.cf_point_sec === "number") {
          setCfTargetSec(evt.cf_point_sec);
        }
        if (typeof evt.seconds_remaining === "number") {
          setLegacySecsToCf(evt.seconds_remaining);
        }
        break;
      }
      case "crossfade_triggered":
        setState("crossfading");
        break;
      case "crossfade_finished":
        setState("playing");
        if (evt.to_track) {
          setCurrentTrack(evt.to_track);
          currentTrackIdRef.current = evt.to_track.id;
          setCurrentTrackTime(0);
          setCurrentTrackDuration(0);
          // ``track_started`` (which carries the new ``cf_point_sec``)
          // follows this event, so just clear the previous target.
          setCfTargetSec(null);
          setLegacySecsToCf(null);
        }
        break;
      case "track_ended":
        // No state change here — track_started for the new track follows.
        break;
      case "playlist_running_low":
        // v2.6.0 endless mode — surfaces the banner while the agent /
        // engine decides on a continuation track. Cleared on the next
        // track_started above (where setPlaylistRunningLow(false) is
        // wired into the existing handler).
        setPlaylistRunningLow(true);
        break;
      case "endless_warning":
        // Non-fatal; the engine has either hit the append cap or run
        // out of in-genre candidates. Surface to the agent via toast
        // semantics — the page wraps this into its UI banner.
        setError(evt.message || "Endless mode: no more candidates.");
        break;
      case "endless_mode":
        // Server-confirmed echo from set_endless_mode. We mirror the
        // boolean exactly so the toggle pill never gets out of sync
        // with the actual engine state.
        setEndlessMode(evt.enabled);
        if (!evt.enabled) setPlaylistRunningLow(false);
        break;
      case "youtube_status":
        // v2.7 — YouTube Live Chat poller state. The server emits one
        // of these on connect (after broadcast discovery) and again on
        // quota_exceeded / disconnected / error. We mirror straight
        // into local state so the pill renders without a refresh.
        setYoutube({
          state: evt.state,
          broadcastTitle: evt.broadcast?.title,
          reason: evt.reason,
        });
        break;
      case "session_ended":
        setState("ended");
        setExplicitNextTrack(null);
        setCfTargetSec(null);
        setLegacySecsToCf(null);
        // Stop audio elements and let the user navigate away.
        for (const ref of [deckARef, deckBRef]) {
          const el = ref.current;
          if (el) {
            try {
              el.pause();
              el.removeAttribute("src");
              el.load();
            } catch {
              /* ignore */
            }
          }
        }
        break;
      case "engine_command":
        handleEngineCommand(evt);
        break;
      case "live_message":
        appendLog({ role: evt.role, text: evt.content, ts: Date.now() });
        break;
      case "dj_chat":
        setDjChat((prev) => [
          ...prev,
          { text: evt.text || "", ts: Date.now() },
        ]);
        break;
      case "error":
        setError(evt.message || "Live session error");
        break;
      default:
        break;
    }
  });

  const onConnected = useEffectEvent(() => {
    setConnected(true);
    setError(null);
    publishLiveActive(true);
  });
  const onClosed = useEffectEvent(() => {
    setConnected(false);
    publishLiveActive(false);
  });
  const onErrorCallback = useEffectEvent((msg: string) => {
    setError(msg);
  });

  // ── WebSocket lifecycle ─────────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId) return;
    const token = getToken();
    if (!token) return;

    // v2.6.0 canonical path for the primary; v2.7.2 read-only viewer
    // path for OBS Browser Source / embed. The backend keeps
    // ``/ws/live/{id}`` as a deprecated alias for the primary; once
    // every page hits the new endpoint that alias can come out.
    const wsPath = viewerMode
      ? `/api/sessions/${sessionId}/live/viewer`
      : `/api/sessions/${sessionId}/live/stream`;
    const ws = new WebSocket(`${WS_BASE}${wsPath}?token=${token}`);
    wsRef.current = ws;
    let opened = false;
    let cancelled = false;

    ws.onopen = () => {
      opened = true;
      if (cancelled) {
        ws.close();
        return;
      }
      onConnected();
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as ServerEvent;
        onServerEvent(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      if (opened && !cancelled) onErrorCallback("WebSocket error");
    };

    ws.onclose = () => {
      onClosed();
    };

    return () => {
      cancelled = true;
      wsRef.current = null;
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      } else if (ws.readyState === WebSocket.CONNECTING) {
        ws.addEventListener("open", () => ws.close(), { once: true });
      }
      // Intentionally NOT closing the AudioContext or stopping the decks
      // here. Next.js Fast Refresh re-runs this effect every time the
      // hook source is edited, and the previous destructive cleanup
      // tore down audio mid-session — the user heard the music cut and
      // the track restart from 0. The audio cleanup now lives in a
      // dedicated unmount-only effect below; the browser GCs the
      // ``<audio>`` elements + ``AudioContext`` when the page truly
      // unloads.
    };
    // ``onServerEvent`` / ``onConnected`` etc. are useEffectEvent wrappers —
    // by the rules of React they MUST NOT appear in the dep array.
  }, [sessionId]);

  // True-unmount audio cleanup. ``[]`` deps means the cleanup runs only
  // when the hook is unmounted (component truly disposed), not on every
  // WS effect re-run. Strict Mode in dev still mount/unmount/mounts on
  // first render, but at that point no audio is playing so the close()
  // is harmless. Mid-session HMR no longer kills the audio.
  useEffect(() => {
    return () => {
      stopAllDecks();
      if (audioCtxRef.current) {
        try {
          audioCtxRef.current.close();
        } catch {
          /* ignore */
        }
        audioCtxRef.current = null;
      }
    };
  }, [stopAllDecks]);

  // ── Throttled playback_pos ping to the backend + UI time tick ─────────
  // Set up an interval that both pings the backend with the current playback
  // position AND drives the UI progress bar via ``currentTrackTime`` /
  // ``currentTrackDuration``. setState lives in this event-handler-style
  // callback — fully compatible with react-hooks v7 (the rule disallows
  // setState in the *body* of an effect, not inside a setInterval handler).
  // Cleanup pair = canonical v2.4 pattern.
  const tickPlaybackPos = useEffectEvent(() => {
    if (typeof WebSocket === "undefined") return;
    const ws = wsRef.current;
    const tid = currentTrackIdRef.current;
    const which = activeDeckRef.current;
    const el = which === "a" ? deckARef.current : deckBRef.current;
    if (!el) return;
    const ct = Number.isFinite(el.currentTime) ? el.currentTime : 0;
    const dur = Number.isFinite(el.duration) ? el.duration : 0;
    setCurrentTrackTime((prev) => (Math.abs(prev - ct) > 0.05 ? ct : prev));
    setCurrentTrackDuration((prev) => (Math.abs(prev - dur) > 0.05 ? dur : prev));
    if (!ws || ws.readyState !== WebSocket.OPEN || !tid) return;
    // Viewers must NOT send playback_pos — the primary owns the
    // engine's crossfade timer. If two clients both pinged, the
    // engine would race their timings and trigger doubles.
    if (viewerModeRef.current) return;
    try {
      ws.send(
        JSON.stringify({
          type: "playback_pos",
          track_id: tid,
          currentTime: ct,
        }),
      );
    } catch {
      /* ignore — next tick will retry */
    }
  });

  useEffect(() => {
    if (!sessionId) return;
    const id = window.setInterval(() => tickPlaybackPos(), PLAYBACK_POS_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [sessionId]);

  // Resume the AudioContext when the tab becomes visible again, and log
  // every "outside the DOM" event we can hook into so silent stops are
  // attributable. Covered:
  //   - visibilitychange (tab in/out of focus)
  //   - Page Lifecycle freeze/resume (Chrome may freeze backgrounded tabs)
  //   - mediaDevices.devicechange (Bluetooth/USB audio disconnect)
  // ``ctx.resume()`` requires no user gesture once the context has been
  // unlocked at least once — and the LiveStage flow always unlocks via
  // the autoplay overlay or the initial play() call.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const tryResume = (reason: string) => {
      const ctx = audioCtxRef.current;
      if (!ctx) return;
      // Aggressive recovery — call resume() unconditionally (not only on
      // ``suspended``). Chrome has a class of bugs where the renderer
      // goes silent while ``state === "running"`` after visibility
      // toggles or media-server interruptions; resume() is a no-op when
      // already running but kicks the renderer back to life when stuck.
      try {
        const p = ctx.resume();
        if (p && typeof p.then === "function") {
          p.then(
            () =>
              appendLog({
                role: "assistant",
                text: `[audioctx] kicked on ${reason} (state=${ctx.state})`,
                ts: Date.now(),
              }),
            (err) =>
              appendLog({
                role: "assistant",
                text: `[audioctx] kick on ${reason} failed: ${
                  (err as { name?: string })?.name ?? "Error"
                }`,
                ts: Date.now(),
              }),
          );
        }
      } catch {
        /* ignore — best effort */
      }
      // Also kick the active deck — if play() returns silently it's a
      // no-op, but if the element was paused without firing ``pause``
      // (rare Chrome corner case) it'll resume audibly.
      const which = activeDeckRef.current;
      const el = which === "a" ? deckARef.current : deckBRef.current;
      if (el && el.paused) {
        try {
          const p = el.play();
          if (p && typeof p.then === "function") {
            p.catch(() => {
              /* ignore — autoplay overlay handles user-gesture cases */
            });
          }
        } catch {
          /* ignore */
        }
      }
    };
    const onVisible = () => {
      appendLog({
        role: "assistant",
        text: `[lifecycle] visibilitychange → ${document.visibilityState}`,
        ts: Date.now(),
      });
      if (document.visibilityState === "visible") tryResume("visibilitychange");
    };
    const onFreeze = () => {
      appendLog({
        role: "assistant",
        text: "[lifecycle] page frozen (Chrome tab freezing)",
        ts: Date.now(),
      });
    };
    const onResume = () => {
      appendLog({
        role: "assistant",
        text: "[lifecycle] page resumed from freeze",
        ts: Date.now(),
      });
      tryResume("page resume");
    };
    document.addEventListener("visibilitychange", onVisible);
    document.addEventListener("freeze", onFreeze);
    document.addEventListener("resume", onResume);

    let unsubDevice: (() => void) | null = null;
    const md = navigator?.mediaDevices;
    if (md && typeof md.addEventListener === "function") {
      const onDeviceChange = () => {
        appendLog({
          role: "assistant",
          text: "[mediaDevices] devicechange (audio output may have switched)",
          ts: Date.now(),
        });
      };
      md.addEventListener("devicechange", onDeviceChange);
      unsubDevice = () => md.removeEventListener("devicechange", onDeviceChange);
    }

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      document.removeEventListener("freeze", onFreeze);
      document.removeEventListener("resume", onResume);
      if (unsubDevice) unsubDevice();
    };
  }, [appendLog]);

  // Heartbeat — every 2 s, take a snapshot of (audioctx.state, gainA,
  // gainB, active deck paused/muted/volume/networkState/readyState).
  // Only log when something differs from the last snapshot, so the panel
  // stays readable but any silent state flip surfaces.
  //
  // Critically, also detect "STUCK": ``ctx === running`` and
  // ``el.paused === false`` but ``currentTime`` hasn't advanced for
  // ≥4 s. That's the Chrome silent-renderer bug — every flag looks
  // healthy but no samples reach the speakers. When detected we log a
  // STUCK marker and auto-kick (``ctx.resume()`` + ``el.play()``), which
  // resuscitates the renderer in practice.
  useEffect(() => {
    if (!sessionId) return;
    if (typeof window === "undefined") return;
    let last = "";
    let lastCt = -1;
    let lastCtChangeMs = Date.now();
    let kickedStuck = false;
    let reloadedStuck = false;
    const id = window.setInterval(() => {
      const ctx = audioCtxRef.current;
      const gA = gainARef.current;
      const gB = gainBRef.current;
      const which = activeDeckRef.current;
      const el = which === "a" ? deckARef.current : deckBRef.current;
      if (!el && !ctx) return;
      const ct = el && Number.isFinite(el.currentTime) ? el.currentTime : 0;
      const snapshot =
        `ctx=${ctx?.state ?? "?"} ` +
        `gA=${gA ? gA.gain.value.toFixed(2) : "?"} ` +
        `gB=${gB ? gB.gain.value.toFixed(2) : "?"} ` +
        `active=${which} ` +
        `paused=${el?.paused ?? "?"} ` +
        `muted=${el?.muted ?? "?"} ` +
        `vol=${el?.volume ?? "?"} ` +
        `net=${el?.networkState ?? "?"} ` +
        `ready=${el?.readyState ?? "?"}`;
      if (snapshot !== last) {
        last = snapshot;
        appendLog({
          role: "assistant",
          text: `[heartbeat] ${snapshot}`,
          ts: Date.now(),
        });
      }

      // currentTime advancement check
      if (Math.abs(ct - lastCt) > 0.05) {
        lastCt = ct;
        lastCtChangeMs = Date.now();
        kickedStuck = false;
        reloadedStuck = false;
        return;
      }
      const stuckMs = Date.now() - lastCtChangeMs;
      const looksHealthy =
        ctx?.state === "running" &&
        el !== null &&
        el !== undefined &&
        !el.paused &&
        !el.muted &&
        (el.readyState ?? 0) >= 2;
      // Tier 1 — 4 s stuck: gentle kick. Helps when the renderer is in a
      // running-but-silent state (Chrome bug after visibility toggles).
      if (stuckMs >= 4000 && looksHealthy && !kickedStuck) {
        kickedStuck = true;
        appendLog({
          role: "assistant",
          text:
            `[heartbeat] STUCK ct=${ct.toFixed(1)}s for ${(stuckMs / 1000).toFixed(1)}s ` +
            `— auto-kicking ctx.resume() + el.play()`,
          ts: Date.now(),
        });
        try {
          const rp = ctx?.resume();
          if (rp && typeof rp.then === "function") rp.catch(() => {});
        } catch {
          /* ignore */
        }
        try {
          const pp = el?.play();
          if (pp && typeof pp.then === "function") pp.catch(() => {});
        } catch {
          /* ignore */
        }
      }
      // Tier 2 — 8 s stuck and tier-1 didn't unstick it. The Tier-1 kick
      // doesn't help when the audio is waiting for HTTP data that never
      // arrives (server stream socket dropped mid-Range). Force the
      // ``<audio>`` to re-fetch by calling ``load()`` and reseeking to
      // where it stalled. The ``loadeddata`` listener restores the
      // playhead and resumes — net=2/ready=2 should flip back to
      // net=1/ready=4 once the new connection delivers the rest.
      if (
        stuckMs >= 8000 &&
        looksHealthy &&
        kickedStuck &&
        !reloadedStuck &&
        el
      ) {
        reloadedStuck = true;
        const stalledAt = ct;
        const src = el.src;
        appendLog({
          role: "assistant",
          text:
            `[heartbeat] STILL STUCK after ${(stuckMs / 1000).toFixed(1)}s ` +
            `— forcing src reload from ${stalledAt.toFixed(1)}s`,
          ts: Date.now(),
        });
        const onLoaded = () => {
          el.removeEventListener("loadeddata", onLoaded);
          try {
            el.currentTime = stalledAt;
          } catch {
            /* ignore — element may not allow seek yet */
          }
          try {
            const p = el.play();
            if (p && typeof p.then === "function") p.catch(() => {});
          } catch {
            /* ignore */
          }
          appendLog({
            role: "assistant",
            text: `[heartbeat] reload ok — resumed @ ${stalledAt.toFixed(1)}s`,
            ts: Date.now(),
          });
        };
        try {
          el.addEventListener("loadeddata", onLoaded, { once: true });
          // Re-assigning src forces a fresh HTTP request. Same URL so
          // backend ``stream_track`` serves the same file from byte 0;
          // we seek to ``stalledAt`` once the metadata is back.
          el.src = src;
          el.load();
        } catch {
          /* ignore — next heartbeat will retry */
        }
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [sessionId, appendLog]);

  // ── Public command callbacks ────────────────────────────────────────────
  const sendCommand = useCallback(
    (cmd: LiveCommand) => {
      // Viewers are read-only — silently no-op.
      if (viewerModeRef.current) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const text = COMMAND_TEXT[cmd.type];
      appendLog({ role: "user", text, ts: Date.now() });
      ws.send(JSON.stringify({ type: "user_msg", text }));
    },
    [appendLog],
  );

  const sendUserMessage = useCallback(
    (text: string) => {
      if (viewerModeRef.current) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const trimmed = text.trim();
      if (!trimmed) return;
      appendLog({ role: "user", text: trimmed, ts: Date.now() });
      ws.send(JSON.stringify({ type: "user_msg", text: trimmed }));
    },
    [appendLog],
  );

  const sendRaw = useCallback((message: Record<string, unknown>) => {
    if (viewerModeRef.current) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify(message));
    } catch {
      /* ignore — caller will retry on the next sample */
    }
  }, []);

  const resumePlayback = useCallback(() => {
    // Ensure the AudioContext exists AND is resumed inside the gesture —
    // without this, a click during state==='idle' (no deck loaded yet)
    // wouldn't unlock anything, and the engine's later play() would
    // still trip Chrome's autoplay policy. Creating + resuming during
    // the user gesture marks the document as user-activated for the
    // rest of the session.
    const ctx = ensureAudioContext();
    if (ctx && typeof ctx.resume === "function") {
      try {
        const maybe = ctx.resume();
        if (maybe && typeof (maybe as Promise<void>).catch === "function") {
          (maybe as Promise<void>).catch(() => {
            /* ignore — best effort */
          });
        }
      } catch {
        /* ignore — context may already be running */
      }
    }
    const which = activeDeckRef.current;
    const el = which === "a" ? deckARef.current : deckBRef.current;
    if (!el) {
      // Cold start — engine hasn't sent a `load` command yet. The
      // gesture unlocked the context; the next loadIntoActiveDeck call
      // will be able to play() without bouncing off the autoplay
      // policy. Clear the blocked flag so the UI overlay dismisses.
      setAutoplayBlocked(false);
      return;
    }
    try {
      const p = el.play();
      if (p && typeof p.then === "function") {
        p.then(
          () => setAutoplayBlocked(false),
          (err) => {
             
            console.warn("[live] resumePlayback rejected:", err);
            setAutoplayBlocked(true);
          },
        );
      } else {
        setAutoplayBlocked(false);
      }
    } catch (err) {
       
      console.warn("[live] resumePlayback threw:", err);
      setAutoplayBlocked(true);
    }
  }, [ensureAudioContext]);

  const quit = useCallback(() => {
    const ws = wsRef.current;
    // Viewers can't ``quit`` the session — they just close their WS
    // and the bus continues without them. Still stop the local decks
    // so an embed page that called quit() actually goes quiet.
    if (!viewerModeRef.current && ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "quit" }));
      } catch {
        /* ignore */
      }
    }
    stopAllDecks();
  }, [stopAllDecks]);

  // v2.6.0 — toggle endless mode. Wire-fires only; the engine's reply
  // (`endless_mode` event) is the source of truth, mirrored into
  // `endlessMode` state by the switch handler above. This keeps the
  // pill from desyncing if the WS write succeeds but the server fails
  // to update the engine for any reason.
  const setEndlessModeWS = useCallback((enabled: boolean) => {
    if (viewerModeRef.current) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(
        JSON.stringify({ type: "set_endless_mode", enabled: !!enabled }),
      );
    } catch {
      /* ignore — WS error already handled elsewhere */
    }
  }, []);

  return useMemo<UseLiveSessionApi>(
    () => ({
      state,
      connected,
      currentTrack,
      nextTrack,
      secondsToCrossfade,
      playlistRemaining,
      playlist,
      currentPosition,
      currentTrackTime,
      currentTrackDuration,
      log,
      djChat,
      error,
      autoplayBlocked,
      audioRef,
      sendCommand,
      sendUserMessage,
      sendRaw,
      resumePlayback,
      quit,
      endlessMode,
      playlistRunningLow,
      setEndlessMode: setEndlessModeWS,
      youtube,
    }),
    [
      state,
      connected,
      currentTrack,
      nextTrack,
      secondsToCrossfade,
      playlistRemaining,
      playlist,
      currentPosition,
      currentTrackTime,
      currentTrackDuration,
      log,
      djChat,
      error,
      autoplayBlocked,
      sendCommand,
      sendUserMessage,
      sendRaw,
      resumePlayback,
      quit,
      endlessMode,
      playlistRunningLow,
      setEndlessModeWS,
      youtube,
    ],
  );
}

// ---------------------------------------------------------------------------
// Cross-component "live session active?" event bus.
//
// The PlayerProvider doesn't know about the live session. Rather than
// extending it with a new flag we use a window event so any component
// (`<MiniPlayer>` first, more later) can subscribe without prop drilling.
// ---------------------------------------------------------------------------

const LIVE_ACTIVE_EVENT = "apollo:live-active";

function publishLiveActive(active: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent(LIVE_ACTIVE_EVENT, { detail: { active } }),
    );
  } catch {
    /* ignore */
  }
}

/** Subscribe a sibling component to the "live session active" flag. */
export function useIsLiveActive(): boolean {
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onChange = (ev: Event) => {
      const ce = ev as CustomEvent<{ active: boolean }>;
      // setState here runs inside an event handler (canonical v2.4 — not
      // a setState-in-effect violation).
      setActive(!!ce.detail?.active);
    };
    window.addEventListener(LIVE_ACTIVE_EVENT, onChange);
    return () => window.removeEventListener(LIVE_ACTIVE_EVENT, onChange);
  }, []);
  return active;
}
