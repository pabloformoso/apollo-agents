import type { NextConfig } from "next";

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
