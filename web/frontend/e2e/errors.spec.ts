import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";

/**
 * C — error paths through the Genre Guard.
 *
 * v2.6.0: dashboard "Start a session" now routes via /brief (which only
 * stashes the prompt locally), so the planning agent isn't reachable
 * from the dashboard CTA alone. To exercise the genre-guard error paths
 * we create the session via the API and visit /session/{id} directly,
 * where the legacy phase-machine UI still hosts the GenreInputBox that
 * drives the agent.
 */
test.describe("C — error paths", () => {
  test("C1: unresolved genre → error banner shown; input re-enabled for retry", async ({
    page,
    request,
  }) => {
    const user = await signedInOnDashboard(page, request);
    const apiBase =
      process.env.APOLLO_E2E_API ?? "http://localhost:8801";
    const res = await request.post(`${apiBase}/api/sessions`, {
      headers: { Authorization: `Bearer ${user.token}` },
    });
    const { id } = await res.json();
    await page.goto(`/session/${id}`);

    const input = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await input.fill("xyzzy garbage");
    await page.getByRole("button", { name: /^send/i }).click();

    await expect(page.locator("text=/Could not confirm genre/i")).toBeVisible();
    // Input should be usable again for a retry (phase went back to init/genre)
    await expect(
      page.getByPlaceholder(/60-minute cyberpunk set/i),
    ).toBeEnabled();
  });

  /**
   * C2 — phase failure mid-Planner. The mock pipeline raises a RuntimeError
   * when the prompt contains "crash" (sentinel surfaced via mood='crash').
   * The WS handler catches it, emits a graceful `error` event, and the user
   * can navigate back to the dashboard and start a fresh session.
   */
  test("C2: planner crash → error banner; user can recover", async ({
    page,
    request,
  }) => {
    const user = await signedInOnDashboard(page, request);
    const apiBase =
      process.env.APOLLO_E2E_API ?? "http://localhost:8801";
    const r1 = await request.post(`${apiBase}/api/sessions`, {
      headers: { Authorization: `Bearer ${user.token}` },
    });
    const { id: id1 } = await r1.json();
    await page.goto(`/session/${id1}`);

    await page
      .getByPlaceholder(/60-minute cyberpunk set/i)
      .fill("60-minute techno set, please crash the planner");
    await page.getByRole("button", { name: /^send/i }).click();

    await expect(
      page.locator("text=/RuntimeError|simulated planner crash/i"),
    ).toBeVisible();

    // Recovery: back to library and start fresh.
    await page.goto("/dashboard");
    await page.waitForURL(/\/dashboard$/);
    const r2 = await request.post(`${apiBase}/api/sessions`, {
      headers: { Authorization: `Bearer ${user.token}` },
    });
    const { id: id2 } = await r2.json();
    await page.goto(`/session/${id2}`);
    await expect(
      page.getByPlaceholder(/60-minute cyberpunk set/i),
    ).toBeEnabled();
  });
});
