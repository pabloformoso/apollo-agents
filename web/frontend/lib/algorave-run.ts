/**
 * §11 S4 — the identity of an algorave run (§11.3 seam 5).
 *
 * `/live` is addressed as `/api/sessions/{id}/…`; a rave run had no id at all.
 * Giving it one NOW — even before anything server-side consumes it — is what
 * keeps the fusion of §11.1 a composition of two instruments inside one
 * session rather than a data migration later.
 *
 * The id is generated in the browser and carried in `?run=`, so a reload, a
 * second tab and (in S8) the read-only OBS view all name the same run. Nothing
 * on the server knows about it yet, and that is fine: the point is that the
 * surface already addresses itself by id, so S5's mind calls and any later
 * server-side session can adopt it without changing how the page is reached.
 */

/**
 * `crypto.randomUUID` is unavailable outside a secure context — the same
 * constraint that costs us AudioWorklet over plain HTTP (see lib/strudel.ts).
 * A run id is not a security token, so a readable fallback is fine; what it
 * must not do is throw on the origin we actually develop against.
 */
export function newRunId(): string {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID().slice(0, 8);
  }
  return Math.random().toString(36).slice(2, 10);
}

export const RUN_PARAM = "run";

/**
 * Reads `?run=` or mints one, without adding a history entry — arriving at the
 * page is one navigation, not two.
 */
export function resolveRunId(): string {
  if (typeof window === "undefined") return "pending";
  const url = new URL(window.location.href);
  const existing = url.searchParams.get(RUN_PARAM);
  if (existing) return existing;
  const id = newRunId();
  url.searchParams.set(RUN_PARAM, id);
  window.history.replaceState(null, "", url.toString());
  return id;
}
