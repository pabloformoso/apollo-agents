import { test, expect } from "@playwright/test";

for (const viewport of [
  { width: 3440, height: 1270 },
  { width: 1920, height: 1080 },
  { width: 1366, height: 600 },
  { width: 390, height: 844 },
]) {
  test(`dashboard keeps actions reachable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      localStorage.setItem("apollo_token", "layout-test");
      localStorage.setItem("apollo_user", JSON.stringify({ id: 1, username: "layout-test" }));
    });
    // This is a layout test: no account, session or GPU side effects.
    await page.route("**/api/**", (route) => route.fulfill({ json: [] }));
    await page.goto("/dashboard");
    const start = page.getByRole("button", { name: "Start a session" });
    const footer = page.getByRole("button", { name: "Sign out" });
    await expect(start).toBeVisible();
    const hero = page.locator("section [class*='aspect-']");
    const box = await hero.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    expect(box!.height).toBeLessThanOrEqual(viewport.height);
    if (viewport.width >= 1920) {
      await expect(start).toBeInViewport({ ratio: 1 });
      await expect(footer).toBeInViewport({ ratio: 1 });
    }
    // Short and narrow screens may scroll, but must never clip the controls.
    for (const control of [start, footer]) {
      await control.scrollIntoViewIfNeeded();
      await expect(control).toBeInViewport({ ratio: 1 });
    }
  });
}
