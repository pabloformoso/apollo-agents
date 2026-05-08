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
}

export interface LiveCommandLogEntry {
  role: "user" | "assistant";
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
  log: LiveCommandLogEntry[];
  error: string | null;
  /** Active deck — exposed as a stable ref for the future `<VisualLayer>`. */
  audioRef: React.RefObject<HTMLAudioElement | null>;
  /** Send a control command to the backend agent. */
  sendCommand: (cmd: LiveCommand) => void;
  /** Send free-text user message to the agent. */
  sendUserMessage: (text: string) => void;
  /** Quit the live session — closes the WS, stops audio, releases mic etc. */
  quit: () => void;
}

export type LiveCommand =
  | { type: "skip" }
  | { type: "stay" }
  | { type: "more_energetic" }
  | { type: "wind_down" };

interface ServerEngineCommand {
  type: "engine_command";
  command: "load" | "skip" | "crossfade" | "queue_swap" | "stop";
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
    | "session_ended";
  track?: LiveTrackSummary;
  next_track?: LiveTrackSummary;
  from_track?: LiveTrackSummary;
  to_track?: LiveTrackSummary;
  seconds_remaining?: number;
}

interface ServerLiveMessage {
  type: "live_message";
  role: "user" | "assistant";
  content: string;
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

export function useLiveSession(sessionId: string | null): UseLiveSessionApi {
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
  const [nextTrack, setNextTrack] = useState<LiveTrackSummary | null>(null);
  const [playlist, setPlaylist] = useState<LiveTrackSummary[]>([]);
  const [secondsToCrossfade, setSecondsToCrossfade] = useState(0);
  const [playlistRemaining, setPlaylistRemaining] = useState(0);
  const [log, setLog] = useState<LiveCommandLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

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
    return ctx;
  }, []);

  const ensureDeck = useCallback(
    (which: "a" | "b") => {
      const refObj = which === "a" ? deckARef : deckBRef;
      if (refObj.current) return refObj.current;
      if (typeof window === "undefined") return null;
      const el = new Audio();
      el.preload = "auto";
      el.crossOrigin = "anonymous";
      refObj.current = el;

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
    [ensureAudioContext],
  );

  const loadIntoActiveDeck = useCallback(
    async (track: LiveTrackSummary) => {
      const which = activeDeckRef.current;
      const el = ensureDeck(which);
      if (!el) return;
      audioRef.current = el;
      el.src = streamUrl(track.id);
      try {
        await el.play();
      } catch {
        // Autoplay may be blocked until a user gesture — UI shows a "click
        // anywhere to start" hint via state.
      }
      currentTrackIdRef.current = track.id;
    },
    [ensureDeck],
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
      } catch {
        /* user-gesture gating — UI surfaces via state */
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
        if (es.next_track) setNextTrack(es.next_track);
        setSecondsToCrossfade(es.seconds_to_crossfade);
        setPlaylistRemaining(es.playlist_remaining);
        break;
      }
      case "track_started": {
        if (evt.track) {
          setCurrentTrack(evt.track);
          currentTrackIdRef.current = evt.track.id;
          setState("playing");
        }
        break;
      }
      case "approaching_crossfade": {
        if (evt.next_track) setNextTrack(evt.next_track);
        if (typeof evt.seconds_remaining === "number") {
          setSecondsToCrossfade(evt.seconds_remaining);
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
        }
        break;
      case "track_ended":
        // No state change here — track_started for the new track follows.
        break;
      case "session_ended":
        setState("ended");
        setNextTrack(null);
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

    const ws = new WebSocket(
      `${WS_BASE}/ws/live/${sessionId}?token=${token}`,
    );
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
    // ``onServerEvent`` / ``onConnected`` etc. are useEffectEvent wrappers —
    // by the rules of React they MUST NOT appear in the dep array.
  }, [sessionId, stopAllDecks]);

  // ── Throttled playback_pos ping to the backend ─────────────────────────
  // Set up an interval (NOT a setState inside effect — only event handler
  // logic). Cleanup pair = canonical v2.4 pattern.
  useEffect(() => {
    if (!sessionId) return;
    const id = window.setInterval(() => {
      // Defensive: in tests / hot reload the global ``WebSocket`` constructor
      // may have been unstubbed before the interval fires. Skip the tick
      // rather than blow up on ``WebSocket.OPEN``.
      if (typeof WebSocket === "undefined") return;
      const ws = wsRef.current;
      const tid = currentTrackIdRef.current;
      const which = activeDeckRef.current;
      const el = which === "a" ? deckARef.current : deckBRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !tid || !el) return;
      const currentTime = el.currentTime || 0;
      try {
        ws.send(
          JSON.stringify({
            type: "playback_pos",
            track_id: tid,
            currentTime,
          }),
        );
      } catch {
        /* ignore — next tick will retry */
      }
    }, PLAYBACK_POS_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [sessionId]);

  // ── Public command callbacks ────────────────────────────────────────────
  const sendCommand = useCallback(
    (cmd: LiveCommand) => {
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
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const trimmed = text.trim();
      if (!trimmed) return;
      appendLog({ role: "user", text: trimmed, ts: Date.now() });
      ws.send(JSON.stringify({ type: "user_msg", text: trimmed }));
    },
    [appendLog],
  );

  const quit = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "quit" }));
      } catch {
        /* ignore */
      }
    }
    stopAllDecks();
  }, [stopAllDecks]);

  return useMemo<UseLiveSessionApi>(
    () => ({
      state,
      connected,
      currentTrack,
      nextTrack,
      secondsToCrossfade,
      playlistRemaining,
      playlist,
      log,
      error,
      audioRef,
      sendCommand,
      sendUserMessage,
      quit,
    }),
    [
      state,
      connected,
      currentTrack,
      nextTrack,
      secondsToCrossfade,
      playlistRemaining,
      playlist,
      log,
      error,
      sendCommand,
      sendUserMessage,
      quit,
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
