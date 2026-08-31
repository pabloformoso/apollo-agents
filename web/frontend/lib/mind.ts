/**
 * §11 S5 — the browser's one way to reach the mind (§11.3 seam 1).
 *
 * Nothing else in the frontend may call the mind's path. That is the point of
 * the seam, and it is checkable: grep the frontend for the endpoint and this
 * file is the only hit. When the DJ lane wants a mind too, or the call moves
 * behind the FastAPI backend, it is a change here and nowhere else.
 *
 * The server half is `app/api/algorave/mind/route.ts`, which exists because an
 * HTTPS page cannot reach a plain-HTTP mind — see its header.
 */

/** What the page knows when it asks. Mirrors `parse_request` in the mind. */
export interface MindRequest {
  /** The buffer as it stands. Empty means "nothing is playing, open the set". */
  code: string;
  /** Required by the mind: without it there is no decision to make. */
  intent: string;
  genre?: string;
  key?: string;
  barsElapsed?: number;
  /** The last few `// reason:` lines, so the mind does not repeat itself. */
  recentReasons?: string[];
  /** True while the pen is alternating (§9.2). S6 sets this; S5 never does. */
  b2b?: boolean;
}

/** A successful answer. */
export interface MindProposal {
  code: string;
  reason: string;
  stats: Record<string, unknown>;
}

/**
 * A refusal, carried whole. The mind's statuses mean different things and the
 * UI must not flatten them: 400 the page sent something malformed, 502 the
 * mind could not produce valid Strudel (ask again), 503 the validator is not
 * installed (`npm install`, not a retry), 504 it did not answer in time.
 */
export class MindError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, message: string, detail: string) {
    super(message);
    this.name = "MindError";
    this.status = status;
    this.detail = detail;
  }

  /** True when asking again might work; false when something needs fixing. */
  get worthRetrying(): boolean {
    return this.status === 502 || this.status === 504;
  }
}

export const MIND_ENDPOINT = "/api/algorave/mind";

export async function askMind(req: MindRequest): Promise<MindProposal> {
  // Field names are the mind's, not ours: it validates them by name and a
  // rename here would be a 400 that reads like a mind failure.
  const body = JSON.stringify({
    code: req.code,
    intent: req.intent,
    ...(req.genre ? { genre: req.genre } : {}),
    ...(req.key ? { key: req.key } : {}),
    ...(req.barsElapsed !== undefined ? { bars_elapsed: req.barsElapsed } : {}),
    ...(req.recentReasons ? { recent_reasons: req.recentReasons } : {}),
    ...(req.b2b ? { b2b: true } : {}),
  });

  let res: Response;
  try {
    res = await fetch(MIND_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch (err) {
    // The proxy is same-origin, so this is the tab losing the network rather
    // than anything about the mind.
    throw new MindError(0, "could not reach the app", String(err));
  }

  const text = await res.text();
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new MindError(
      res.status,
      "the mind's answer was not JSON",
      text.slice(0, 300),
    );
  }

  const obj = (payload ?? {}) as Record<string, unknown>;

  if (!res.ok) {
    throw new MindError(
      res.status,
      typeof obj.error === "string" ? obj.error : `HTTP ${res.status}`,
      typeof obj.detail === "string" ? obj.detail : "",
    );
  }

  if (typeof obj.code !== "string" || obj.code.length === 0) {
    // A 200 with no code is a contract break, not a mutation. Saying so beats
    // wiping the buffer with an empty string.
    throw new MindError(
      200,
      "the mind answered without any code",
      text.slice(0, 300),
    );
  }

  return {
    code: obj.code,
    reason: typeof obj.reason === "string" ? obj.reason : "",
    stats:
      obj.stats && typeof obj.stats === "object"
        ? (obj.stats as Record<string, unknown>)
        : {},
  };
}

/**
 * The tie rule — **on a tie, the human wins** (#148).
 *
 * A proposal may only be applied without asking when the buffer is BYTE-
 * IDENTICAL to what the mind was shown. If the human typed while the mind was
 * thinking, their edit stands and the proposal drops to a manual diff: the
 * mind wrote an answer to a question that is no longer on screen, and
 * overwriting live edits is the one thing a duet partner must never do.
 *
 * Pure and exported so S6 can hand it to the scheduler unchanged — the manual
 * Apply button is never gated by it, only the automatic path is.
 */
export function autoApplyDecision(
  seenByMind: string,
  currentBuffer: string,
): { autoApply: boolean; why: "buffer_unchanged" | "held_buffer_dirty" } {
  return seenByMind === currentBuffer
    ? { autoApply: true, why: "buffer_unchanged" }
    : { autoApply: false, why: "held_buffer_dirty" };
}
