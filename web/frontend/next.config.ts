import path from "node:path";
import type { NextConfig } from "next";

// §11 S3 — Strudel is NOT bundled. See web/CLAUDE.md.
//
// It is copied to public/vendor/strudel/ by scripts/vendor-strudel.mjs and
// loaded at runtime by URL, because its AudioWorklet asset is resolved with
// `new URL("assets/...", import.meta.url)` and therefore has to sit next to
// the module on the server. Bundling it breaks audio silently.
//
// An eslint no-restricted-imports rule stops a static `@strudel/*` import
// from quietly reintroducing a bundled second copy.

const nextConfig: NextConfig = {
  // §11 S6 — the pen module lives in scripts/algorave-spike and is imported
  // by BOTH the spike's page and this app (§11.3 seam 2: one copy, never two).
  // Turbopack's root defaults to this directory, so it has to be widened to
  // the repo for that import to resolve.
  turbopack: { root: path.join(__dirname, "..", "..") },
  // E2E runs set NEXT_DIST_DIR=.next-e2e so the mock-mode dev server's lockfile
  // lives in a separate build dir and does not collide with the engineer's
  // running `npm run dev` session (Next 16 refuses two dev servers per project).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Next 16 blocks cross-origin requests to dev resources by default. Without
  // 127.0.0.1 here, opening http://127.0.0.1:4010 leaves the page un-hydrated
  // (HMR WS + RSC payload both rejected) — symptoms: root /  doesn't redirect,
  // controlled inputs don't update state, submit buttons stay disabled.
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.APOLLO_API_URL ?? "http://localhost:4020"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
