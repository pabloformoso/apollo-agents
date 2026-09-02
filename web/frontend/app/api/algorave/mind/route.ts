/**
 * §11 S5 — the mind, reached through the server.
 *
 * The page does NOT call `scripts/algorave_playground.py` directly, and this
 * is not a preference:
 *
 *   - **Mixed content.** The page must be a secure context or Strudel gets no
 *     AudioWorklet at all (S3). An HTTPS page cannot `fetch` an `http://` mind
 *     on :4032 — the browser blocks it outright. Same-origin through here, and
 *     the plain-HTTP hop happens server-side where no such rule applies.
 *   - **CORS stops existing.** `algorave_playground.py` compares origins
 *     byte-exact against `SPIKE_ORIGINS` plus `--allow-origin`, so every new
 *     surface used to mean another flag on a process someone has to remember
 *     to restart (§11.5 risk 2). No browser origin reaches the mind now, so
 *     there is nothing to keep in sync. **The plan's task to widen
 *     `--allow-origin` is obsolete rather than done.**
 *   - **The address is server-side config** (R3), not a value the bundle
 *     carries and every client re-learns.
 *
 * This is the server half of §11.3 seam 1. The browser half is `lib/mind.ts`.
 * Between them there is exactly one place that knows where the mind lives, so
 * pointing it at a different host — or later at the FastAPI backend, when the
 * DJ lane wants a mind too — is a one-file change.
 */
import { NextResponse } from "next/server";

/**
 * The mind binds to the tailnet interface, not loopback (#144's HOST bind),
 * which is why this default is an IP and not `127.0.0.1`.
 */
const MIND_URL =
  process.env.ALGORAVE_MIND_URL ?? "http://100.68.5.104:4032/mind";

/**
 * The same server's model list. Derived from `MIND_URL` rather than configured
 * separately, so there is still exactly ONE address to change (seam 1) and the
 * two can never point at different minds.
 */
const MODELS_URL = MIND_URL.replace(/\/mind\/?$/, "/models");

/** The list is a cheap local call; a slow one means the mind is gone. */
const MODELS_TIMEOUT_MS = 5_000;

/**
 * Longer than the mind server's own `--timeout` (120 s), so a slow model is
 * the MIND's error and never ours. This abort exists for the hung socket —
 * a killed process, a dropped link — which without it leaves the request
 * pending forever and the page mute. The playground learned this the hard
 * way in its first real practice (#148).
 */
const TIMEOUT_MS = 130_000;

/**
 * Which models this mind will answer for. The page renders one option each and
 * may send any of them back as `model`; the SERVER owns the list, so a browser
 * cannot name a backend the operator did not declare.
 *
 * A failure here is reported, not smoothed over — but it is not fatal either:
 * the page hides the selector and keeps using the mind's default, because
 * being unable to CHOOSE a model must never mean being unable to play.
 */
export async function GET() {
  try {
    const res = await fetch(MODELS_URL, {
      signal: AbortSignal.timeout(MODELS_TIMEOUT_MS),
      cache: "no-store",
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "content-type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: "could not reach the mind to ask which models it serves",
        detail: String(err),
      },
      { status: 502 },
    );
  }
}

export async function POST(request: Request) {
  let body: string;
  try {
    body = await request.text();
  } catch {
    return NextResponse.json(
      { error: "could not read the request body", detail: "" },
      { status: 400 },
    );
  }

  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(MIND_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      signal: abort.signal,
    });

    // Pass the mind's own status and body through untouched. Its refusals are
    // deliberate and distinct — 400 malformed, 502 could not produce valid
    // Strudel, 503 validator unavailable — and paraphrasing them here would
    // fork the wording from the one place that knows what went wrong.
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  } catch (err) {
    const aborted = err instanceof Error && err.name === "AbortError";
    return NextResponse.json(
      {
        error: aborted
          ? "the mind did not answer in time — keep playing what you have"
          : "the mind is unreachable — keep playing what you have",
        detail: aborted
          ? `no response within ${TIMEOUT_MS / 1000}s from ${MIND_URL}`
          : `${MIND_URL}: ${String(err)}`,
      },
      // 504 vs 502: one says the mind is slow, the other that it is not there.
      // The page shows both, and which one it was decides what you go and fix.
      { status: aborted ? 504 : 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}
