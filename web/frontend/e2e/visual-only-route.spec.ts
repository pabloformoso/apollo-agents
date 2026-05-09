import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.3 — OBS-friendly /visual-only route.
 *
 * The fullscreen visual layer must mount with NO chrome from the regular
 * ``/live`` page (no header, no chat panel, no action buttons).  This
 * route is what an OBS browser source captures when v2.6 ships
 * broadcasting.
 */

test.describe("v2.5.3 — visual-only OBS route", () => {
  test("renders only the visual layer with no live stage chrome", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);

    // Walk to ckpt1 so the session has a playlist.
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // Navigate to the OBS-friendly route directly.
    await page.goto(`/session/${sid}/live/visual-only`);

    // The visual layer must mount.
    await expect(page.getByTestId("visual-only-root")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("visual-layer")).toBeVisible();
    await expect(page.getByTestId("visual-canvas")).toBeVisible();

    // The full LiveStage chrome must NOT appear: no live-stage container,
    // no skip / quit / chat input.
    await expect(page.getByTestId("live-stage")).toHaveCount(0);
    await expect(page.getByTestId("live-skip")).toHaveCount(0);
    await expect(page.getByTestId("live-quit")).toHaveCount(0);
    await expect(page.getByTestId("live-chat-input")).toHaveCount(0);
  });

  test("redirects unauthenticated users to /login", async ({ page }) => {
    await page.goto("/session/anything/live/visual-only");
    await page.waitForURL(/\/login/);
    expect(page.url()).toMatch(/\/login/);
  });
});
