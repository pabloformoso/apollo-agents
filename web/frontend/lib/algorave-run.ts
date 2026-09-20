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

/**
 * One change that reached the room, and why. The mind's applied answer or
 * the human's own edit, with the lines it added so the audience view can
 * light them up: the code that IS playing next to the reason it changed.
 *
 * This is what was missing for a viewer to see WHY: `Proposal` was cleared
 * on apply, the reasons ring was sent to the model and never rendered, and
 * the mirror carried the PENDING reason — empty at exactly the moment the
 * music changed.
 */
export interface AppliedChange {
  source: "mind" | "human";
  /** The bar it landed on. */
  bar: number;
  reason: string;
  /** Which model answered, or null for a human edit / an older mind. */
  model: string | null;
  added: number;
  removed: number;
  /** The added lines, trimmed — the viewer highlights these in the buffer. */
  lines: string[];
  ts: number;
}

/** How many changes the room remembers. Five reasons is a story; fifty is a log. */
export const HISTORY_MAX = 6;
const LINES_MAX = 24;

type DiffRowLike = { type: "same" | "add" | "del"; text: string };

/**
 * Append a change to the history, non-mutating, bounded. The counts and the
 * highlighted lines are derived from the diff HERE so every caller — the
 * auto-apply path, the hand-clicked Apply, the human edit — records the same
 * shape without three copies of the arithmetic.
 */
export function recordChange(
  history: AppliedChange[],
  change: {
    source: "mind" | "human";
    bar: number;
    reason: string;
    model: string | null;
    diff: DiffRowLike[];
  },
  now: number = Date.now(),
): AppliedChange[] {
  const added = change.diff.filter((r) => r.type === "add");
  const removed = change.diff.filter((r) => r.type === "del").length;
  const entry: AppliedChange = {
    source: change.source,
    bar: Math.max(0, Math.floor(change.bar)),
    reason: change.reason.trim(),
    model: change.model,
    added: added.length,
    removed,
    lines: added.map((r) => r.text.trim()).filter(Boolean).slice(0, LINES_MAX),
    ts: now,
  };
  return [...history, entry].slice(-HISTORY_MAX);
}

/** What the operator publishes and the viewer renders. */
export interface RunSnapshot {
  buffer: string;
  pen: "human" | "mind";
  barsNow: number;
  phraseBars: number;
  /** The PENDING proposal's reason — what the mind would play, not yet applied. */
  reason: string;
  /** What has already reached the room, oldest first. Empty on an older operator. */
  history: AppliedChange[];
  /** True while an ask is in flight, so the audience sees the mind listening. */
  thinking: boolean;
  /** What the mind was asked for. */
  intent: string;
  /** Which model answered last. */
  model: string | null;
}

/** The change the room is hearing right now, if any. */
export function lastApplied(history: AppliedChange[]): AppliedChange | null {
  return history.length > 0 ? history[history.length - 1] : null;
}

function readChange(raw: unknown): AppliedChange | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const lines = Array.isArray(o.lines)
    ? o.lines.filter((l): l is string => typeof l === "string").slice(0, LINES_MAX)
    : [];
  return {
    source: o.source === "human" ? "human" : "mind",
    bar: typeof o.bar === "number" && o.bar >= 0 ? o.bar : 0,
    reason: typeof o.reason === "string" ? o.reason : "",
    model: typeof o.model === "string" ? o.model : null,
    added: typeof o.added === "number" ? o.added : lines.length,
    removed: typeof o.removed === "number" ? o.removed : 0,
    lines,
    ts: typeof o.ts === "number" ? o.ts : 0,
  };
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
    history: Array.isArray(body.history)
      ? (body.history as unknown[])
          .map(readChange)
          .filter((c): c is AppliedChange => c !== null)
          .slice(-HISTORY_MAX)
      : [],
    thinking: body.thinking === true,
    intent: typeof body.intent === "string" ? body.intent : "",
    model: typeof body.model === "string" ? body.model : null,
  };
}
