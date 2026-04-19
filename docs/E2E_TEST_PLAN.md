# End-to-End Test Plan — ApolloAgents v2.0 Web UI

**Status:** draft — to execute once Playwright MCP is live (restart Claude Code after the `.mcp.json` landed in 133dfb8).

**Scope:** browser-driven smoke tests that walk the full 7-phase pipeline, verify no UI blockers between phases, and catch the class of regression we just hit (e.g. user couldn't proceed after Critique because the `phase_complete` payload didn't advance `session.phase` to `checkpoint2`).

**What this complements:** 50 backend + 8 frontend unit/integration tests already in CI. Those pin the parts. This plan pins the **transitions between parts** from the user's seat.

---

## Test harness

- **Runner:** `@playwright/test` inside `web/frontend/e2e/`, invoked via `npm run e2e`.
- **Browser driver during authoring:** Playwright MCP (interactive — for debugging failing scripts).
- **Backend mode:** the FastAPI server runs with `AGENT_PROVIDER=mock` (new — see §5) so LLM calls never hit Anthropic/OpenAI. Each pipeline phase uses the same deterministic fakes we already use in `tests/web/conftest.py::mock_pipeline`, wired via an env-flagged dispatcher in `pipeline.py`.
- **DB:** backend points at a tempfile SQLite (`APOLLO_DB_PATH` env var, new — drop-in substitute for `DB_PATH`).
- **Dev servers:** Playwright's `globalSetup` spawns `uvicorn backend.app:app --port 8801` and `next dev --port 3001` on non-production ports; teardown kills both.
- **Test user:** each spec registers a fresh `e2e-${uuid}` account on startup to avoid cross-test pollution.

---

## Flow under test (maps to README §Pipeline phases)

```
Login → Dashboard → New Session
  1. Janus         (Genre Guard)
  2. Muse          (Planner)        ← auto-runs after genre confirm
  3. Checkpoint 1  (user approves)
  4. Momus         (Critic)         ← auto-runs after approve
  5. Checkpoint 2  (user approves)
  6. Editor REPL   (swap/move/build)
  7. Themis        (Validator)      ← auto-runs after build
  8. Rating & Finish
```

Every arrow above is a candidate blocker. Each test asserts the arrow resolves within a bounded time and the UI exposes the right input for the next phase.

---

## Test matrix

### A. Auth & session lifecycle (pre-pipeline)

| # | Spec | What it asserts |
|---|---|---|
| A1 | `auth.spec.ts` | Register → auto-redirect to `/dashboard`. `Authorization` bearer persists on reload. |
| A2 | `auth.spec.ts` | Logout clears localStorage and redirects to `/login`. |
| A3 | `dashboard.spec.ts` | Create session → navigates to `/session/{id}`, phase shows `Genre`. |
| A4 | `dashboard.spec.ts` | List shows just-created session; delete removes it without a reload. |

### B. Pipeline transitions — the heart of this plan

Each step (B1–B7) has **two assertions**: a *state* assertion (the `phase` badge in the top bar matches) and a *no-blocker* assertion (the right input control is rendered and not disabled).

| # | Step | Trigger | State assertion | No-blocker assertion |
|---|---|---|---|---|
| B1 | Genre confirmed | Type `"60-minute cyberpunk set, dark and intense"` → **Send** | Phase bar highlights `Planning` | **none** — phase auto-advances |
| B2 | Planner done | (auto, follows B1) | Phase bar highlights `Ckpt1`; playlist panel has ≥1 row | `Approve / Run Critic` button is enabled |
| B3 | Checkpoint 1 approve | Click **Run Critic** | Phase bar highlights `Critique` | Input shows `Agent working...` (disabled by design) |
| B4 | **Critic done** | (auto, follows B3) | Phase bar highlights `Ckpt2`; Critic panel shows verdict badge | `Continue to Editor` button is enabled **← this is the bug that kicked off the plan; guard it here** |
| B5 | Checkpoint 2 approve | Click **Continue to Editor** | Phase bar highlights `Editing` | Editor input visible AND focused AND not disabled |
| B6 | Editor command | Type `"build e2e-smoke"` → **Run** | Phase bar advances through `Validating` | `Agent working...` during validate, then rating UI |
| B7 | Validator done | (auto, follows B6) | Phase bar highlights `Rating`; validator status chip visible | 1–5 rating buttons enabled; notes field editable |
| B8 | Rate & finish | Click `5`, submit | Phase bar highlights `Complete`; green "Session complete" banner | No input controls remain; navigation back to dashboard works |

### C. Non-happy paths

| # | Spec | What it asserts |
|---|---|---|
| C1 | `errors.spec.ts` | Garbage genre prompt → backend emits `error` event → banner `"Could not confirm genre"` shown; input remains enabled for retry. |
| C2 | `errors.spec.ts` | Kill backend mid-Planner → WebSocket `error` event → banner shown; user can create a new session from dashboard. |
| C3 | `reload.spec.ts` | Mid-pipeline browser reload → session state restored from `/api/sessions/{id}` (phase, playlist, critic verdict all intact). |
| C4 | `multiuser.spec.ts` | User A's session id cannot be opened by User B (HTTP 404 + UI redirect to dashboard). |

### D. UI regressions we already fixed — pin them

| # | Spec | What it asserts |
|---|---|---|
| D1 | `regression.spec.ts` | During a session, network tab records **exactly 1** `GET /api/sessions/{id}` call — guards the infinite-poll regression we fixed in 6ec6e11. |
| D2 | `regression.spec.ts` | WebSocket connects exactly once (no "closed before established" churn). |
| D3 | `regression.spec.ts` | Playlist with duplicate `track.id` across positions renders without React `Encountered two children with the same key` warning. Assertion: `page.on('console')` collects warnings; spec fails on any `key` warning. |
| D4 | `regression.spec.ts` | Register → login → `/api/auth/me` returns the user (pins the passlib/bcrypt 500 that started the test push). |

---

## Implementation details

### Backend mock mode (§5 requirement)

Add to `web/backend/pipeline.py`:

```python
_MOCK_MODE = os.getenv("AGENT_PROVIDER") == "mock"

if _MOCK_MODE:
    # Swap phase_* functions for the same deterministic fakes used by
    # tests/web/conftest.py::mock_pipeline
    from tests.web.conftest import _install_mock_pipeline
    _install_mock_pipeline()
```

(Or, cleaner: extract the fake functions to `web/backend/mock_pipeline.py` and import from both places. Avoids tests-as-runtime-dep.)

### Playwright config (`web/frontend/playwright.config.ts`)

```ts
export default defineConfig({
  testDir: "./e2e",
  webServer: [
    { command: "cd ../.. && AGENT_PROVIDER=mock APOLLO_DB_PATH=/tmp/apollo-e2e.db uv run uvicorn backend.app:app --port 8801 --app-dir web", port: 8801 },
    { command: "NEXT_PUBLIC_API_BASE=http://localhost:8801 npm run dev -- --port 3001", port: 3001 },
  ],
  use: { baseURL: "http://localhost:3001", trace: "on-first-retry" },
});
```

(Requires one small change to `lib/api.ts` + `lib/ws.ts` — read `NEXT_PUBLIC_API_BASE` and `NEXT_PUBLIC_WS_BASE` instead of the hard-coded `localhost:8800` / `/api`.)

### CI wiring

Append to `.github/workflows/ci.yml` `frontend` job:

```yaml
- name: Install Playwright browsers
  working-directory: web/frontend
  run: npx playwright install --with-deps chromium

- name: E2E
  working-directory: web/frontend
  run: npm run e2e
```

Add `@playwright/test` as a devDependency. Runtime budget: chromium-only, ~30s for the full suite (B1–B8 is the only sequential path; everything else parallelizes).

---

## Execution order

1. Extract the mock pipeline fakes from `tests/web/conftest.py` into `web/backend/mock_pipeline.py` and wire `AGENT_PROVIDER=mock` to install them at startup
2. Add `APOLLO_DB_PATH` env override to `web/backend/db.py`
3. Replace hard-coded `8800` / `/api` in `lib/api.ts` and `lib/ws.ts` with env-driven bases
4. Install `@playwright/test`, add `playwright.config.ts`, scaffold `e2e/*.spec.ts`
5. Author the B-series first (they're the critical path); confirm B4 passes against the Critique-blocker fix we just shipped
6. Add A, C, D
7. Wire CI

Expected total new code: ~400 LOC Playwright specs + ~50 LOC backend env plumbing. Runtime ~30s added to CI.

---

## Verification

- `cd web/frontend && npm run e2e` — all ~18 specs green against the mock backend
- `npm run e2e -- --project=chromium --grep "Critique"` — B3 + B4 run in <5s and catch the exact blocker the user reported
- CI log on next push shows the Playwright job with all browsers installed and specs green
- Manual: with Playwright MCP live, drive B1→B8 interactively to confirm the fixture-free path matches what real Anthropic calls produce (smoke — not a CI requirement)
