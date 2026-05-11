import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";

/**
 * A3–A4 — dashboard create/list flow.
 *
 * v2.6.0: the dashboard CTA ("Start a session") routes through the Brief
 * screen instead of straight to the legacy /session/[id] phase machine.
 * The first test asserts that flow; the legacy "session card delete from
 * dashboard" affordance was retired by the redesign (cards no longer
 * carry a delete affordance — sessions can be removed from the
 * /session/[id] page or by API). A4 is skipped pending a v2.6.0 design
 * for session deletion within the new Library view.
 */
test.describe("A — dashboard", () => {
  test("A3: Start a session opens the Brief screen with hero copy", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);
    await page
      .getByRole("button", { name: /(new session|start a session)/i })
      .click();
    await page.waitForURL(/\/brief(\?session=[^&]+)?$/);
    // Brief screen renders the italic display hero + prompt textarea.
    await expect(
      page.getByRole("heading", { name: /one sentence/i }),
    ).toBeVisible();
    await expect(
      page.getByPlaceholder(/lofi ambient set/i),
    ).toBeVisible();
  });

  test.skip("A4: dashboard list / delete (legacy — redesign no longer surfaces a card delete affordance)", async () => {
    // Pending v2.6.0 design for session removal within the new Library
    // grid. Sessions can still be deleted via the legacy /session/[id]
    // page or the API; the dashboard card no longer offers it inline.
  });
});
