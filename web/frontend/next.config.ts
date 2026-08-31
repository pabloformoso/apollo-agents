import type { NextConfig } from "next";

// §11 S3 — one `Pattern` class, or silence.
//
// `@strudel/web`'s `dist/index.mjs` is a self-contained prebuilt bundle: core,
// mini, tonal and webaudio are compiled INTO it and it imports nothing at
// runtime. But the package still DECLARES those sub-packages as dependencies,
// so npm installs them alongside, each with its own separate build. Importing
// `@strudel/core` directly therefore hands you a DIFFERENT `Pattern` class
// than the one living inside the bundle — patterns built by one are not
// recognised by the other, and the failure is silent: no error, no audio.
//
// `patterns/playground.html` solves this with an import map pointing every
// `@strudel/*` specifier at the single file. This is the bundler equivalent.
// The package has no `exports` field, only `main` (CJS) and `module` (ESM),
// so the alias also pins which of the two builds is used instead of leaving
// it to bundler heuristics.
//
// `/algorave-spike` asserts the invariant at runtime. Do not remove one
// without the other.
const STRUDEL_BUNDLE = "@strudel/web/dist/index.mjs";

const nextConfig: NextConfig = {
  // E2E runs set NEXT_DIST_DIR=.next-e2e so the mock-mode dev server's lockfile
  // lives in a separate build dir and does not collide with the engineer's
  // running `npm run dev` session (Next 16 refuses two dev servers per project).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Next 16 blocks cross-origin requests to dev resources by default. Without
  // 127.0.0.1 here, opening http://127.0.0.1:4010 leaves the page un-hydrated
  // (HMR WS + RSC payload both rejected) — symptoms: root /  doesn't redirect,
  // controlled inputs don't update state, submit buttons stay disabled.
  allowedDevOrigins: ["127.0.0.1"],
  turbopack: {
    resolveAlias: {
      "@strudel/web": STRUDEL_BUNDLE,
      "@strudel/core": STRUDEL_BUNDLE,
      "@strudel/mini": STRUDEL_BUNDLE,
      "@strudel/tonal": STRUDEL_BUNDLE,
      "@strudel/webaudio": STRUDEL_BUNDLE,
      "@strudel/transpiler": STRUDEL_BUNDLE,
    },
  },
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
