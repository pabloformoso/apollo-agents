/**
 * Where the browser's WebSockets go — ONE definition, read at connect time.
 *
 * **The bug this exists to kill.** Both `lib/ws.ts` and `lib/live.ts` carried
 * their own copy of this, each falling back to `ws://localhost:4020`. That
 * string is baked into the CLIENT bundle, so it means "the machine with the tab
 * open" — which is only the server when you happen to be sitting at it. Opened
 * from anywhere else (the tailnet IP, a phone, an OBS box) every session
 * WebSocket dialled the viewer's own laptop and failed, while the HTTP half
 * kept working because `/api/*` is same-origin through the Next rewrite. The
 * page then sits there saying "no brief yet" forever: nothing errored, the
 * updates simply never arrive.
 *
 * **So the default is derived from the page's own origin.** The host that
 * served the page is the one host we KNOW reaches this deployment, whatever it
 * is called today — localhost, a tailnet IP, or the nginx name that does not
 * exist yet. Only the port is assumed, and 4020 is what compose publishes.
 *
 * **It must be called at CONNECT time, never at module scope.** `location` does
 * not exist on the server, and a module-level constant would be evaluated
 * during SSR — throwing, or worse, freezing whatever the server thought. This
 * is the same class of bug that `ssr: false` retired on /algorave; here the
 * page is server-rendered, so laziness is the fix.
 *
 * The protocol follows the page too: an HTTPS page must use `wss:` or the
 * browser blocks it as mixed content. Note that this only STARTS working once
 * something terminates TLS in front of the backend — until then an HTTPS page
 * needs `NEXT_PUBLIC_WS_BASE` pointed at whatever does.
 */

/** The port compose publishes the backend on. */
const DEFAULT_WS_PORT = "4020";

export function wsBase(): string {
  // Explicit wins, always: the E2E suite pins this to its mock server, and a
  // deployment where the backend is not on <page host>:4020 needs it.
  const explicit = process.env.NEXT_PUBLIC_WS_BASE;
  if (explicit) return explicit;

  const apiBase = process.env.NEXT_PUBLIC_API_BASE;
  if (apiBase) return apiBase.replace(/^http/, "ws");

  if (typeof window !== "undefined" && window.location) {
    const secure = window.location.protocol === "https:";
    const port = process.env.NEXT_PUBLIC_WS_PORT || DEFAULT_WS_PORT;
    return `${secure ? "wss:" : "ws:"}//${window.location.hostname}:${port}`;
  }

  // Server-side only — no browser is going to dial this. Kept so the function
  // is total rather than throwing during a render that never opens a socket.
  return `ws://localhost:${DEFAULT_WS_PORT}`;
}
