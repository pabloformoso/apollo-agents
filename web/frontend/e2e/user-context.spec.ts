import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.3.0 — user context infrastructure smoke test.
 *
 * Goal: confirm the pipeline path that hydrates `context_variables` with the
 * logged-in user's id/playlists/ratings does not crash when the user has
 * actually rated some tracks before kicking off a session.
 *
 * Limitation: under `AGENT_PROVIDER=mock` (used by CI), `phase_plan` is
 * replaced by `mock_pipeline.fake_plan` which produces a hard-coded playlist
 * and does NOT exercise the real prompt path that injects "USER PREFERENCES".
 * The prompt-shape assertions live in `tests/web/test_phase_plan_user_context.py`
 * (mocked unit tests against the real `phase_plan`). Here we simply verify
 * that the WS handler's `s.context_variables["user_id"] = s.user_id`
 * injection doesn't break the genre → planning → ckpt1 path when the user
 * has already-rated tracks.
 */
const API_BASE = process.env.APOLLO_E2E_API ?? "http://localhost:8801";

test.describe("v2.3.0 — user context", () => {
  test("rate tracks → start session → planner phase reached without crash", async ({
    page,
    request,
  }) => {
    const user = await signedInOnDashboard(page, request);
    const e2eUser = user;

    // ── Rate three mock-catalog tracks via the REST API. The catalog is
    // populated by `mock_pipeline._build_mock_catalog`, so these IDs are
    // stable across CI runs.
    const ratedIds = ["mock-lofi-silence", "mock-lofi-alpha", "mock-lofi-bravo"];
    for (const id of ratedIds) {
      const res = await request.put(
        `${API_BASE}/api/tracks/${encodeURIComponent(id)}/rating`,
        {
          headers: { Authorization: `Bearer ${user.token}` },
          data: { rating: 5 },
        },
      );
      expect(res.ok(), `rating PUT failed for ${id}`).toBeTruthy();
    }

    // ── Sanity-check the ratings are persisted before we start the session.
    const ratingsRes = await request.get(`${API_BASE}/api/catalog`, {
      headers: { Authorization: `Bearer ${user.token}` },
    });
    expect(ratingsRes.ok()).toBeTruthy();
    const body = (await ratingsRes.json()) as {
      tracks: Array<{ id: string; user_rating?: number | null }>;
    };
    const rated = body.tracks.filter((t) => (t.user_rating ?? 0) >= 4);
    expect(rated.length).toBeGreaterThanOrEqual(3);

    // ── Start a new session and confirm the genre. The backend will inject
    // `user_id` into `context_variables` on the first WS message, then call
    // `phase_plan`. With `AGENT_PROVIDER=mock` this resolves to `fake_plan`,
    // which produces a hard-coded playlist; the assertion is that the path
    // does not crash when ctx contains a real user_id whose user has rated
    // tracks (and that the session reaches ckpt1).
    await gotoNewSession(page, request, e2eUser);

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await expect(genreInput).toBeEnabled();
    await genreInput.fill("60-minute lofi-ambient set, chill vibes");
    await page.getByRole("button", { name: /^send$/i }).click();

    // ── Planner auto-runs after genre confirmation; we land on ckpt1 if the
    // user-context hydration path is healthy.
    await expectPhase(page, "ckpt1");
    await expect(page.getByRole("button", { name: /run the critic/i })).toBeEnabled();
  });
});
