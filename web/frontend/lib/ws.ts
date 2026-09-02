"use client";
import { useEffect, useRef, useCallback, useEffectEvent } from "react";
import { getToken } from "./auth";
import type { ServerEvent } from "./types";
// Next does not proxy WebSockets, so the browser dials the backend directly.
// Where that is lives in ONE place — see lib/ws-base.ts.
import { wsBase } from "./ws-base";


export function useSessionWS(
  sessionId: string | null,
  onEvent: (event: ServerEvent) => void,
) {
  const wsRef = useRef<WebSocket | null>(null);

  // `useEffectEvent` (React 19) lets us read the latest `onEvent` from inside
  // the WebSocket effect without making the effect re-run when the parent
  // re-renders with a new callback identity. This replaces the prior pattern
  // of mutating an `onEventRef.current` during render, which violated
  // `react-hooks/refs`.
  const handleEvent = useEffectEvent((event: ServerEvent) => {
    onEvent(event);
  });

  useEffect(() => {
    if (!sessionId) return;
    const token = getToken();
    if (!token) return;

    const ws = new WebSocket(`${wsBase()}/ws/sessions/${sessionId}?token=${token}`);
    wsRef.current = ws;
    let opened = false;
    let cancelled = false;

    ws.onopen = () => {
      opened = true;
      if (cancelled) ws.close();
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as ServerEvent;
        handleEvent(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      // Suppress handshake-time errors (StrictMode double-mount, backend
      // reload wiping the in-memory session store). Only surface errors
      // after a successful open.
      if (opened && !cancelled) {
        handleEvent({ type: "error", message: "WebSocket error" });
      }
    };

    return () => {
      cancelled = true;
      wsRef.current = null;
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      } else if (ws.readyState === WebSocket.CONNECTING) {
        // Defer close until the handshake completes; closing mid-handshake
        // triggers the "closed before connection is established" warning.
        ws.addEventListener("open", () => ws.close(), { once: true });
      }
    };
    // `handleEvent` is intentionally excluded from the dep array because it's
    // a `useEffectEvent` — the React docs require it to NOT appear in deps
    // (the function identity changes every render but always reads the latest
    // `onEvent`, which is the whole point).
  }, [sessionId]);

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { send };
}
