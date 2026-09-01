/**
 * The editor's half of the validator — one place that knows the endpoint, and
 * the reading of a verdict as something a performer can act on.
 *
 * Same seam rule as `lib/mind.ts`: nothing else names this path.
 */

export interface Verdict {
  valid: boolean;
  error: string | null;
  reason: string | null;
  stats: {
    events?: number;
    cycles_checked?: number;
    sounds?: string[];
    kick_four_on_floor?: boolean;
    out_of_key?: string[];
  };
}

const ENDPOINT = "/api/algorave/validate";

export async function validateBuffer(
  code: string,
  opts: { genre?: string; key?: string } = {},
): Promise<Verdict> {
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code, genre: opts.genre, key: opts.key }),
  });
  const body = (await res.json()) as Partial<Verdict> & { error?: string };
  return {
    valid: body.valid === true,
    error: typeof body.error === "string" ? body.error : null,
    reason: typeof body.reason === "string" ? body.reason : null,
    stats: body.stats ?? {},
  };
}

export type VerdictTone = "ok" | "warn" | "error" | "unknown";

export interface VerdictReading {
  tone: VerdictTone;
  /** One line, in the performer's terms. */
  headline: string;
  /** The details worth carrying: event count, sounds, key trouble. */
  facts: string[];
}

/**
 * Turns a verdict into something worth putting on screen mid-set.
 *
 * The distinction that matters: **invalid means it will not play**, while
 * out-of-key means it will play and clash. Flattening those into one colour
 * would tell a performer to stop when they only need to listen.
 */
export function readVerdict(v: Verdict | null): VerdictReading {
  if (!v) return { tone: "unknown", headline: "not checked yet", facts: [] };

  const facts: string[] = [];
  if (typeof v.stats.events === "number") facts.push(`${v.stats.events} events`);
  if (v.stats.sounds?.length) facts.push(v.stats.sounds.join(" "));
  if (v.stats.kick_four_on_floor) facts.push("kick 4/4");

  if (!v.valid) {
    return {
      tone: "error",
      headline: v.error ?? "the validator refused this",
      facts,
    };
  }

  const off = v.stats.out_of_key ?? [];
  if (off.length > 0) {
    return {
      // A warning, never an error: out-of-key is a musical choice the
      // validator does not refuse, and plenty of good ones are.
      tone: "warn",
      headline: `outside the key: ${off.join(" ")}`,
      facts,
    };
  }

  return { tone: "ok", headline: "valid", facts };
}
