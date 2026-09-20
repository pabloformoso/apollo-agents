/**
 * §11 S8 — what the OBS tab reads.
 *
 * The pattern lives in the operator's browser. An OBS Browser Source is a
 * SEPARATE browser, so `BroadcastChannel` and `localStorage` cannot reach it —
 * the state has to pass through the server. That is what the run id from §11.3
 * seam 5 was minted for: the operator publishes under it, the viewer reads
 * under it, and neither needs to know about the other.
 *
 * Deliberately in memory. A run is a performance, not a record: it lasts an
 * evening, nothing is worth persisting, and a restart losing it costs a page
 * reload. If this ever needs to survive a restart or span more than one server
 * process, that is the moment it belongs behind the FastAPI backend rather
 * than here — and the client only knows `lib/algorave-run.ts`, so that move is
 * a one-file change.
 *
 * The viewer POLLS this. A WebSocket would be tighter, but polling has no
 * reconnect story to get wrong, and OBS reloading its source must never be
 * able to disturb the operator — the v3.6.2 lesson in `lib/viewer.ts`.
 *
 * **The run id is a QUERY PARAM, not a path segment, and it has to be.**
 * `next.config.ts` rewrites `/api/:path*` to the FastAPI backend, and a
 * `rewrites()` that returns an array is `afterFiles` — which Next checks
 * BEFORE dynamic routes but AFTER static ones. So `/api/algorave/mind` wins
 * (static segment) while `/api/algorave/run/[id]` would lose, and every call
 * silently became a proxy attempt to :4020 with `ECONNREFUSED`. Keeping this
 * segment static keeps it ours.
 */
import { NextResponse } from "next/server";

/** Mirrors `AppliedChange` in lib/algorave-run.ts — validated here because it arrives from the network. */
interface StoredChange {
  source: "human" | "mind";
  bar: number;
  reason: string;
  model: string | null;
  added: number;
  removed: number;
  lines: string[];
  ts: number;
}

export interface RunState {
  buffer: string;
  pen: "human" | "mind";
  barsNow: number;
  phraseBars: number;
  /** The PENDING proposal's reason — what the mind would play next. */
  reason: string;
  /** What already reached the room, oldest first: the reason for the code that IS playing. */
  history: StoredChange[];
  thinking: boolean;
  intent: string;
  model: string | null;
  updatedAt: number;
}

const HISTORY_MAX = 6;
const LINES_MAX = 24;
const TEXT_MAX = 400;

function text(v: unknown, max = TEXT_MAX): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function readChange(raw: unknown): StoredChange | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const lines = Array.isArray(o.lines)
    ? o.lines.filter((l): l is string => typeof l === "string").slice(0, LINES_MAX).map((l) => l.slice(0, 300))
    : [];
  return {
    source: o.source === "human" ? "human" : "mind",
    bar: typeof o.bar === "number" && o.bar >= 0 ? Math.floor(o.bar) : 0,
    reason: text(o.reason),
    model: typeof o.model === "string" ? o.model.slice(0, 120) : null,
    added: typeof o.added === "number" && o.added >= 0 ? o.added : lines.length,
    removed: typeof o.removed === "number" && o.removed >= 0 ? o.removed : 0,
    lines,
    ts: typeof o.ts === "number" ? o.ts : 0,
  };
}

/** Bounded so a long-lived server cannot accumulate abandoned runs. */
const MAX_RUNS = 32;
const runs = new Map<string, RunState>();

function remember(id: string, state: RunState) {
  runs.delete(id); // re-insert so Map iteration order is least-recent-first
  runs.set(id, state);
  while (runs.size > MAX_RUNS) {
    const oldest = runs.keys().next().value;
    if (oldest === undefined) break;
    runs.delete(oldest);
  }
}

function runIdFrom(request: Request): string | null {
  const id = new URL(request.url).searchParams.get("id");
  return id && id.length > 0 ? id : null;
}

export async function GET(request: Request) {
  const id = runIdFrom(request);
  if (!id) {
    return NextResponse.json({ error: "`id` is required" }, { status: 400 });
  }
  const state = runs.get(id);
  if (!state) {
    // Not an error: the viewer may well be open before the operator has
    // played a note. It says "waiting" rather than showing a failure.
    return NextResponse.json(
      { waiting: true },
      { status: 200, headers: { "cache-control": "no-store" } },
    );
  }
  return NextResponse.json(state, { headers: { "cache-control": "no-store" } });
}

export async function POST(request: Request) {
  const id = runIdFrom(request);
  if (!id) {
    return NextResponse.json({ error: "`id` is required" }, { status: 400 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "body was not JSON" }, { status: 400 });
  }
  const o = (body ?? {}) as Record<string, unknown>;
  if (typeof o.buffer !== "string") {
    return NextResponse.json(
      { error: "`buffer` must be a string" },
      { status: 400 },
    );
  }

  remember(id, {
    buffer: o.buffer,
    pen: o.pen === "mind" ? "mind" : "human",
    barsNow: typeof o.barsNow === "number" && o.barsNow >= 0 ? o.barsNow : 0,
    phraseBars: typeof o.phraseBars === "number" && o.phraseBars > 0 ? o.phraseBars : 8,
    reason: text(o.reason),
    history: Array.isArray(o.history)
      ? o.history.map(readChange).filter((c): c is StoredChange => c !== null).slice(-HISTORY_MAX)
      : [],
    thinking: o.thinking === true,
    intent: text(o.intent, 200),
    model: typeof o.model === "string" ? o.model.slice(0, 120) : null,
    updatedAt: Date.now(),
  });

  return NextResponse.json({ ok: true });
}
