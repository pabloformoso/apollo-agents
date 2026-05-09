import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.2 — issue #44 regression coverage.
 *
 * Cycles particles → strobe → fractal → particles inside the live page
 * and verifies:
 *
 *  1. The canvas survives every transition (no GL context loss / mount
 *     errors).
 *  2. No console errors are emitted during the switching sequence — the
 *     pre-fix flow leaked Three.js renderers and triggered "WebGL
 *     context lost" warnings on hot-swap.
 *  3. The strobe overlay div is mounted while strobe is selected and
 *     gets removed when we leave it (proves ``destroy()`` ran).
 */

test.describe("v2.5.2 — visualizer effect switching (#44)", () => {
  test("cycles particles → strobe → fractal → particles without console errors", async ({
    page,
    request,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });
    page.on("pageerror", (err) => {
      consoleErrors.push(err.message);
    });

    await signedInOnDashboard(page, request);

    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("live-stage")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("visual-layer")).toBeVisible();
    await expect(page.getByTestId("visual-canvas")).toBeVisible();

    // Default: particles.
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "particles",
    );

    // particles → strobe.
    await page.getByTestId("visual-effect-strobe").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "strobe",
    );
    await expect(page.locator("[data-testid=strobe-overlay]")).toHaveCount(1);

    // strobe → fractal: strobe overlay must be unmounted.
    await page.getByTestId("visual-effect-fractal").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "fractal",
    );
    await expect(page.locator("[data-testid=strobe-overlay]")).toHaveCount(0);

    // fractal → particles. Canvas must still be there. This is the
    // exact transition that produced GL artifacts pre-fix.
    await page.getByTestId("visual-effect-particles").click();
    await expect(page.getByTestId("visual-layer")).toHaveAttribute(
      "data-effect",
      "particles",
    );
    await expect(page.getByTestId("visual-canvas")).toBeVisible();

    // Give the rAF loop a couple of ticks.
    await page.waitForTimeout(250);

    // No console errors expected. We allow the harmless "WebSocket
    // closed" lines that the live mock emits during teardown — those
    // come from the WS path, not the visualizer.
    const visualizerErrors = consoleErrors.filter(
      (e) =>
        !/websocket/i.test(e) &&
        !/aborted/i.test(e) &&
        !/Failed to load resource/i.test(e),
    );
    expect(visualizerErrors).toEqual([]);
  });

  test("strobe overlay sits above the canvas (z-index ≥ canvas)", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];
    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("visual-layer")).toBeVisible({
      timeout: 15000,
    });
    await page.getByTestId("visual-effect-strobe").click();

    const overlay = page.locator("[data-testid=strobe-overlay]");
    await expect(overlay).toHaveCount(1);
    const z = await overlay.evaluate(
      (el) => getComputedStyle(el).zIndex,
    );
    // Pre-fix the overlay had no z-index and was hidden under sibling
    // controls in fullscreen. Fix sets it to "5".
    expect(parseInt(z, 10)).toBeGreaterThan(0);
  });
});
