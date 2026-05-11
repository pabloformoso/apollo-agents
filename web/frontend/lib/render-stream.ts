"use client";
/**
 * Apollo v2.6.0 — Render SSE subscription helper.
 *
 * The render endpoint at `GET /api/sessions/:id/render/stream` is a
 * long-lived SSE source (~minutes for a 30 min set). EventSource is
 * GET-only and can't set auth headers from the browser, so the JWT
 * goes in the query string just like the audio stream pattern in
 * `lib/api.ts::streamUrl`.
 *
 * This helper wraps the native EventSource with:
 *   - Exponential-backoff reconnect (1, 2, 4, 8, 16 s capped at 30s,
 *     max 5 attempts before surfacing a terminal `onError`).
 *   - Named-event handling (`done`, `error`) — the server emits these
 *     to signal completion / fail.
 *   - Clean shutdown via the returned `close()` so the page's effect
 *     cleanup can stop the connection without leaking.
 */
import { getToken } from "./auth";

export type RenderFrame = {
  stage: string | null;
  pct: number;
  etaSeconds: number | null;
  message?: string;
};

export type RenderAssets = Record<string, string>;

export type RenderChapter = {
  tMs: number;
  title: string;
  camelot: string | null;
};

export type RenderHandlers = {
  onFrame: (frame: RenderFrame) => void;
  onDone: (payload: { assets: RenderAssets; chapters: RenderChapter[] }) => void;
  onError: (message: string, terminal: boolean) => void;
};

const BASE = `${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api`;
const MAX_RETRIES = 5;
const BACKOFF_CAP_MS = 30_000;

export function subscribeRender(
  sessionId: string,
  handlers: RenderHandlers,
): { close: () => void } {
  let source: EventSource | null = null;
  let attempts = 0;
  let closed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (closed) return;
    const token = getToken() ?? "";
    const url = `${BASE}/sessions/${sessionId}/render/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    source = es;

    es.onmessage = (e) => {
      try {
        handlers.onFrame(JSON.parse(e.data) as RenderFrame);
        attempts = 0; // good frame resets the backoff counter
      } catch {
        // ignore malformed frames
      }
    };

    es.addEventListener("done", (e) => {
      try {
        handlers.onDone(JSON.parse((e as MessageEvent).data));
      } catch {
        handlers.onDone({ assets: {}, chapters: [] });
      }
      closed = true;
      es.close();
    });

    es.addEventListener("error", (e) => {
      // Native EventSource fires `error` both for transport failures
      // (which we want to retry) and for server-emitted `event: error`
      // frames (which we want to surface and stop retrying). The named
      // server event carries data; transport failures don't.
      const data = (e as MessageEvent).data;
      if (typeof data === "string" && data.length > 0) {
        try {
          const payload = JSON.parse(data) as { message?: string };
          handlers.onError(payload.message ?? "Render failed", true);
        } catch {
          handlers.onError(data || "Render failed", true);
        }
        closed = true;
        es.close();
        return;
      }
      // Transport-level error — reconnect with backoff.
      es.close();
      source = null;
      if (closed) return;
      attempts += 1;
      if (attempts > MAX_RETRIES) {
        handlers.onError("Lost connection to render stream.", true);
        closed = true;
        return;
      }
      const delay = Math.min(BACKOFF_CAP_MS, 1_000 * 2 ** (attempts - 1));
      handlers.onError(`Reconnecting (attempt ${attempts}/${MAX_RETRIES})…`, false);
      reconnectTimer = setTimeout(connect, delay);
    });
  };

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (source) {
        source.close();
        source = null;
      }
    },
  };
}

/** Compose a download URL with the token in the query string. The
 *  browser navigates to this URL via `<a download>` or
 *  `window.location.href` — the auth header workaround is the same as
 *  `lib/api.ts::streamUrl`. */
export function renderAssetUrl(sessionId: string, kind: string): string {
  const token = getToken() ?? "";
  return `${BASE}/sessions/${sessionId}/download/${kind}?token=${encodeURIComponent(token)}`;
}
