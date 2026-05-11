import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.3 — Visual layer beat-sync E2E.
 *
 * Walks the planning UI to ckpt1 (so the live WS has a playlist), opens
 * the live page, then exercises the three visual effects.  The mock
 * backend's ``fake_phase_live`` already drives a ``track_started`` so
 * the canvas has something to react to.
 *
 * Each effect toggle asserts ``data-effect`` on the visual layer plus
 * that the canvas / DOM stays mounted (no crash). For the strobe we
 * also verify the overlay div was attached.
 */

test.describe("v2.5.3 — visual layer", () => {
  test("particles / strobe / fractal selectors mount the canvas without crashing", async ({
    page,
    request,
  }) => {
    const e2eUser = await signedInOnDashboard(page, request);

    // Walk planning UI to ckpt1 → live route.
    await gotoNewSession(page, request, e2eUser);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("live-stage")).toBeVisible({ timeout: 15000 });

    // Wait for the visual layer to mount (it's inside the live-stage layout).
    await expect(page.getByTestId("visual-layer")).toBeVisible();
    await expect(page.getByTestId("visual-canvas")).toBeVisible();

    // Default is particles.
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "particles",
    );

    // Toggle to strobe — verify selector switches and overlay is mounted.
    await page.getByTestId("visual-effect-strobe").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "strobe",
    );
    // strobe-bars selector appears.
    await expect(page.getByTestId("strobe-bars-4")).toBeVisible();

    // Toggle to fractal.
    await page.getByTestId("visual-effect-fractal").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "fractal",
    );

    // Back to particles — verify the effect lifecycle handles repeated
    // switches without crashing.
    await page.getByTestId("visual-effect-particles").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "particles",
    );
    await expect(page.getByTestId("visual-canvas")).toBeVisible();
  });

  test("fullscreen toggle button is reachable", async ({ page, request }) => {
    const e2eUser = await signedInOnDashboard(page, request);

    await gotoNewSession(page, request, e2eUser);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("visual-layer")).toBeVisible({
      timeout: 15000,
    });

    // We don't ACTUALLY trigger the Fullscreen API in headless Chromium
    // (it requires a user-activation token and most CI sandboxes refuse
    // it). Verify only that the button exists and is clickable; the
    // promise rejection inside the component is swallowed.
    const fsBtn = page.getByTestId("visual-fullscreen");
    await expect(fsBtn).toBeVisible();
    await fsBtn.click();
  });
});
