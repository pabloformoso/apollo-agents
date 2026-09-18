# Contributing to Apollo

Thanks for helping shape Apollo, an AI Music Entertainment System. The project has several connected surfaces, so a contribution is easiest to review when it explains the musical or product behavior it changes.

## Before you start

Read the [README](README.md) for the product model and [ROADMAP](ROADMAP.md) for the current direction. For repository-specific operational rules, read [`CLAUDE.md`](CLAUDE.md) and the nested notes next to the area you will change.

If you are planning a substantial feature, open an issue first. A short proposal should say:

- who the feature is for;
- which Apollo surface it belongs to;
- what a user can do after it exists;
- how we will know it works.

Small fixes, documentation improvements, and focused UI polish can go straight to a pull request.

## Local setup

```bash
git clone https://github.com/pabloformoso/apollo-agents.git
cd apollo-agents
uv sync
npm --prefix web/frontend ci
cp .env.example .env
```

The web app needs two processes during development:

```bash
# terminal 1
uv run uvicorn backend.app:app --reload --port 4021 --app-dir web

# terminal 2
APOLLO_API_URL=http://localhost:4021 NEXT_PUBLIC_WS_BASE=ws://localhost:4021 npm --prefix web/frontend run dev -- --port 4011
```

Development uses ports `4011` and `4021`; `4010` and `4020` are reserved for the running stack. Keep development data separate from production, and never update the production checkout or restart its services during a live broadcast.

## Where to work

| Area | Location | Start here |
| --- | --- | --- |
| Core mix pipeline | `main.py`, `agent/` | `agent/CLAUDE.md` |
| Web backend | `web/backend/` | `web/CLAUDE.md` |
| Web frontend | `web/frontend/` | `web/CLAUDE.md` and the Ember components |
| Algorave | `web/frontend/app/algorave/`, `scripts/algorave-spike/` | `scripts/CLAUDE.md` |
| Observability | `packages/py-obs/` | `packages/py-obs/README.md` |
| Product and design docs | `README.md`, `docs/` | the relevant plan before changing behavior |

Keep product behavior in the surface that owns it. For example, a change to the shared pen belongs in the pen module; a visual label belongs in the frontend; a provider-specific setting belongs at the provider boundary.

## Checks

Run the checks that cover the files you changed:

```bash
# Python (include the optional YouTube dependencies for the full suite)
uv run --group youtube pytest tests/

# Frontend unit tests and production build
npm --prefix web/frontend run test
npm --prefix web/frontend run build

# Frontend end-to-end tests, when the change affects a browser flow
npm --prefix web/frontend run e2e

# Algorave registry, validator, and pen
npm --prefix scripts/algorave-spike ci
npm --prefix scripts/algorave-spike run test
```

A build warning that predates your change should be called out in the pull request. A new type error, failing test, or route that cannot build needs to be fixed before review.

Do not add tests that only repeat an implementation detail. Add coverage for a user-visible behavior, a boundary between services, or a regression that could realistically return.

## Frontend contributions

Apollo's shared UI lives in `web/frontend/components/ember/`. Reuse the Shell, primitives, colors, type, and spacing vocabulary before adding a new visual language. When a new route is a stage of an existing journey, make that relationship clear in the navigation and copy.

For UI changes:

- check desktop and narrow viewports;
- keep controls reachable without relying on hover;
- give asynchronous states a visible loading, empty, and error state;
- use the existing auth and API helpers;
- include a screenshot or a short flow description when it helps review.

## Agents and tools

Agent tools use the repository convention:

```python
def tool_name(param: type, context_variables: dict) -> str:
    ...
```

Keep roles narrow, tool lists bounded, and outputs structured enough for the next collaborator to inspect. A new agent should have a clear reason to exist instead of becoming another name for orchestration logic.

## Pull requests

Use a focused branch and keep a pull request about one coherent outcome. The title should describe the resulting behavior, for example `feat(web): make the catalog queue visible` or `docs: explain the AI Music Entertainment System model`.

A useful pull request description includes:

1. the user problem;
2. the resulting behavior;
3. the checks you ran;
4. any known limitation or follow-up.

Keep commits small enough to review, do not commit `.env`, generated audio, local databases, screenshots, or credentials, and update the relevant documentation when a command, route, or product behavior changes.

Maintainers squash-merge pull requests to `main`. A pull request should be green before merge and should not require a production restart as part of review.

## Questions and proposals

Open an issue for bugs, product questions, and focused proposals. Include the route or command involved, the expected behavior, the actual behavior, and the smallest reproduction you can provide.
