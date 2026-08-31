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
 * Reads `?run=` WITHOUT minting one. The viewer must use this: minting would
 * give the OBS tab an id nobody publishes under, so it would wait forever on a
 * run that does not exist.
 */
export function readRunId(): string | null {
  if (typeof window === "undefined") return null;
  return new URL(window.location.href).searchParams.get(RUN_PARAM);
}

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

// ---------------------------------------------------------------------------
// §11 S8 — publishing a run so the OBS tab can mirror it
// ---------------------------------------------------------------------------

/** What the operator publishes and the viewer renders. */
export interface RunSnapshot {
  buffer: string;
  pen: "human" | "mind";
  barsNow: number;
  phraseBars: number;
  reason: string;
}

/**
 * The ONE place the run endpoint is named — the same rule `lib/mind.ts`
 * follows for the mind. If this ever moves behind the FastAPI backend, it is a
 * change here and nowhere else.
 */
const runEndpoint = (id: string) =>
  `/api/algorave/run?id=${encodeURIComponent(id)}`;

/**
 * Publish the current state. Failure is deliberately silent: the operator is
 * performing, and a mirror that cannot be reached must never interrupt what
 * the room is hearing.
 */
export async function publishRun(id: string, snapshot: RunSnapshot): Promise<void> {
  try {
    await fetch(runEndpoint(id), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(snapshot),
    });
  } catch {
    // Intentionally ignored — see above.
  }
}

/** Read a run. `null` means nobody has published under this id yet. */
export async function fetchRun(id: string): Promise<RunSnapshot | null> {
  const res = await fetch(runEndpoint(id), { cache: "no-store" });
  const body = await res.json();
  if (!res.ok || body?.waiting) return null;
  return {
    buffer: String(body.buffer ?? ""),
    pen: body.pen === "mind" ? "mind" : "human",
    barsNow: Number(body.barsNow ?? 0),
    phraseBars: Number(body.phraseBars ?? 8),
    reason: String(body.reason ?? ""),
  };
}
