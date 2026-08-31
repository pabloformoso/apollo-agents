/**
 * §11 S3 — serve @strudel/web's dist under a stable URL prefix.
 *
 * This is the Next equivalent of the one line that makes the playground work
 * (`scripts/algorave-spike/serve.mjs`):
 *
 *   ['/vendor/strudel/', join(ROOT, 'node_modules', '@strudel', 'web', 'dist')]
 *
 * It exists because Strudel's bundle resolves its own AudioWorklet asset with
 * `new URL("assets/clockworker-<hash>.js", import.meta.url)` — relative to the
 * MODULE's URL. The bundle and its `assets/` folder therefore have to be
 * neighbours on the server. Bundling the module breaks that (import.meta.url
 * becomes a hashed chunk path), the asset 404s, and every AudioWorkletNode
 * construction then throws "AudioWorklet does not have a valid
 * AudioWorkletGlobalScope" once per event, forever, while superdough still
 * logs "[superdough] ready". Observed 2026-08-31.
 *
 * Why a route handler and not a copy into `public/`: mapping straight from
 * node_modules is what serve.mjs does, it keeps the served bytes pinned to
 * package.json, and it needs no copy step, no build hook and nothing
 * vendored into git. (A `public/` copy would also work — an earlier round of
 * this spike wrongly concluded otherwise after measuring against a stale
 * server; see the `next-server` note in web/CLAUDE.md.)
 *
 * Deployment note: this reads from node_modules at runtime. Fine here — the
 * repo is bind-mounted into the container — but a `standalone` build would
 * need @strudel/web added to outputFileTracingIncludes.
 */
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { join, normalize, sep } from "node:path";
import { Readable } from "node:stream";

const DIST = join(process.cwd(), "node_modules", "@strudel", "web", "dist");

const MIME: Record<string, string> = {
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
};

export async function GET(
  _request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;

  // Resolve inside DIST and refuse anything that escapes it. The segments come
  // from the URL, so `..` is a question the router does not answer for us.
  const target = normalize(join(DIST, ...path));
  if (target !== DIST && !target.startsWith(DIST + sep)) {
    return new Response("not found", { status: 404 });
  }

  try {
    const info = await stat(target);
    if (!info.isFile()) return new Response("not found", { status: 404 });

    const ext = target.slice(target.lastIndexOf("."));
    const stream = Readable.toWeb(
      createReadStream(target),
    ) as unknown as ReadableStream;

    return new Response(stream, {
      headers: {
        "content-type": MIME[ext] ?? "application/octet-stream",
        "content-length": String(info.size),
        // Pinned to a package version and hashed asset names; safe to cache.
        "cache-control": "public, max-age=3600",
      },
    });
  } catch {
    return new Response("not found", { status: 404 });
  }
}
