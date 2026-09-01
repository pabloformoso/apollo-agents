# syntax=docker/dockerfile:1.7
#
# Frontend image — Next.js 16 dev server on :4010.
#
# The dev server proxies /api/* to ``$APOLLO_API_URL`` (set by compose to
# http://backend:4020 inside the compose network). HMR works via the
# host bind-mount, with node_modules + .next isolated to anonymous
# volumes so the host's node_modules can't shadow the Linux ones baked
# into the image.
#
# **The container mirrors the REPO's layout, not just the frontend's, and
# that is load-bearing.** The frontend reaches two levels up for things
# that live outside web/frontend: tsconfig aliases ``@algorave/pen`` to
# ``../../scripts/algorave-spike/patterns/pen.js`` (the ONE copy of the pen
# module, §11.3 seam 2), ``turbopack.root`` is ``__dirname/../..``, and the
# palette + validate routes spawn/read out of ``cwd/../../scripts/
# algorave-spike``. With the frontend at /app those all resolve to ``/``,
# where nothing exists — and in ``next dev`` ONE unresolvable import is a
# global compilation error, so every route 500s, the DJ lane included.
# Keeping the workdir at <repo>/web/frontend makes every one of those paths
# resolve exactly as it does on the host. Do not flatten it back.

# Node 22, not 20, and the reason is the validator rather than Next.
# ``scripts/algorave-spike/validate.mjs`` imports ``registerHooks`` from
# ``node:module`` — added in Node 22 — and the live-validation route spawns
# it as a subprocess out of this image. On node:20 that spawn dies with
# "does not provide an export named 'registerHooks'", the route answers
# "validator produced no verdict", and the editor silently stops checking
# what the performer types. CI already pins this: the spike's job is
# "Algorave spike (Node 22)".
FROM node:22-slim AS base

# git for any github-hosted npm deps; ca-certificates for npm over HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/web/frontend

# Install deps in a cacheable layer keyed on package.json + lockfile only.
COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

# Copy the rest of the frontend tree. At runtime the bind mount replaces
# this, but the COPY keeps the image self-contained for ``docker run``
# without a mount (e.g. CI ``npm test`` jobs).
COPY web/frontend/ ./

EXPOSE 4010

# Next 16 binds to 127.0.0.1 by default which isn't reachable from
# outside the container — ``-H 0.0.0.0`` is the equivalent of
# ``--host`` on uvicorn.
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
