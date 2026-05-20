# syntax=docker/dockerfile:1.7
#
# Frontend image — Next.js 16 dev server on :4010.
#
# The dev server proxies /api/* to ``$APOLLO_API_URL`` (set by compose to
# http://backend:4020 inside the compose network). HMR works via the
# host bind-mount, with node_modules + .next isolated to anonymous
# volumes so the host's Windows-built node_modules can't shadow the
# Linux ones baked into the image.

FROM node:20-slim AS base

# git for any github-hosted npm deps; ca-certificates for npm over HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

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
