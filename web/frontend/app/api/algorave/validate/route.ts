/**
 * The validator, as the editor sees it.
 *
 * **The same gate the mind is held to, applied to the human.** Rather than
 * inventing a note checker for the editor, this runs
 * `scripts/algorave-spike/validate.mjs` — the process that decides whether the
 * mind's output may play at all. Both players are then judged by one rule, and
 * a disagreement between what the editor says and what the mind is allowed to
 * write becomes impossible rather than merely unlikely.
 *
 * It answers in ~100 ms cold, which is what makes this viable on a debounce
 * while typing.
 *
 * **Security posture, stated rather than assumed.** The validator EVALUATES
 * the code in a Node subprocess. Its screen (`import`, `require`, `fetch`,
 * `eval`, `process` rejected before evaluation) is a denylist, not a sandbox.
 * That is the posture this project already had — the mind's output has always
 * gone through the same process — and this route does not weaken it, but it
 * does widen who supplies the input from "an LLM we prompt" to "whoever has the
 * page open". Acceptable because the surface is a single-operator tool on a
 * private tailnet; NOT acceptable if `/algorave` is ever exposed publicly.
 * Revisit this before that happens.
 */
import { spawn } from "node:child_process";
import { join } from "node:path";
import { NextResponse } from "next/server";

const SPIKE_DIR =
  process.env.ALGORAVE_SPIKE_DIR ??
  join(process.cwd(), "..", "..", "scripts", "algorave-spike");

/** Longer than the validator ever needs, short enough not to pile up. */
const TIMEOUT_MS = 5_000;

/**
 * Assembled rather than written literally, and that is a bundler workaround
 * with a real cause: Turbopack inspects `spawn(...)` arguments and treats a
 * literal `.mjs` as a module it must resolve and bundle, which fails the build
 * with "Can't resolve ('validate.mjs' | <dynamic>)". The script is a sibling
 * PROCESS, not an import. Keeping the extension out of the literal is what
 * stops the bundler from claiming it.
 */
const VALIDATOR = ["validate", "mjs"].join(".");

interface Verdict {
  valid: boolean;
  error: string | null;
  reason: string | null;
  stats?: {
    events?: number;
    cycles_checked?: number;
    sounds?: string[];
    kick_four_on_floor?: boolean;
    out_of_key?: string[];
  };
}

function runValidator(code: string, genre?: string, key?: string): Promise<Verdict> {
  return new Promise((resolve) => {
    const args = [VALIDATOR];
    if (genre) args.push("--genre", genre);
    if (key) args.push("--key", key);

    const child = spawn("node", args, { cwd: SPIKE_DIR });
    let out = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), TIMEOUT_MS);

    child.stdout.on("data", (c) => (out += c));
    // stderr carries the validator's own warnings ("cannot use window") and is
    // deliberately dropped: it is noise about running a browser engine in Node.
    child.stderr.resume();

    child.on("error", (err) =>
      resolve({ valid: false, error: `validator unavailable: ${String(err)}`, reason: null }),
    );
    child.on("close", () => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(out) as Verdict);
      } catch {
        resolve({
          valid: false,
          error: out.trim() ? `validator said: ${out.slice(0, 200)}` : "validator produced no verdict",
          reason: null,
        });
      }
    });

    child.stdin.end(code);
  });
}

export async function POST(request: Request) {
  let body: { code?: unknown; genre?: unknown; key?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "body was not JSON" }, { status: 400 });
  }
  if (typeof body.code !== "string") {
    return NextResponse.json({ error: "`code` must be a string" }, { status: 400 });
  }
  // An empty buffer is not an error; it is a buffer nobody has written yet.
  if (body.code.trim().length === 0) {
    return NextResponse.json({ valid: true, error: null, reason: null, stats: {} });
  }

  const verdict = await runValidator(
    body.code,
    typeof body.genre === "string" && body.genre ? body.genre : undefined,
    typeof body.key === "string" && body.key ? body.key : undefined,
  );
  return NextResponse.json(verdict, { headers: { "cache-control": "no-store" } });
}
