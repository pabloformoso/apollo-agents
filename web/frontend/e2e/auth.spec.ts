import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "crypto";

/**
 * A1–A2 — auth lifecycle through the UI. Separate from the API-based fixture
 * because these specifically exercise the login / register / logout forms.
 */
test.describe("A — auth lifecycle", () => {
  async function registerViaUi(page: Page, username: string, password: string) {
    await page.goto("/register");
    // The register form's <label> nodes aren't associated via htmlFor, so we
    // target inputs by type (username=text, email=email, password=password).
    await page.locator('input[type="text"]').fill(username);
    await page.locator('input[type="email"]').fill(`${username}@example.com`);
    await page.locator('input[type="password"]').fill(password);
    await page.getByRole("button", { name: /create account/i }).click();
  }

  test("A1: register via UI, redirect to dashboard, token persists across reload", async ({ page }) => {
    const username = `e2e-a1-${randomUUID().slice(0, 8)}`;
    const password = "pw12345";

    await registerViaUi(page, username, password);
    await page.waitForURL(/\/dashboard$/);
    // v2.6.0 — username surfaces in the Shell header (top-right) instead
    // of the legacy "Welcome, {username}" string.
    await expect(page.getByText(username, { exact: true })).toBeVisible();

    // Reload — token must persist via localStorage
    await page.reload();
    await expect(page.getByText(username, { exact: true })).toBeVisible();
  });

  test("A2: sign out clears localStorage and redirects to /login", async ({ page }) => {
    const username = `e2e-a2-${randomUUID().slice(0, 8)}`;
    const password = "pw12345";

    await registerViaUi(page, username, password);
    await page.waitForURL(/\/dashboard$/);

    // v2.6.0 — Sign out lives in the dashboard footer (`Sign out` lower-case);
    // /(sign out|signout)/i still matches.
    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL(/\/login$/);
    const token = await page.evaluate(() => localStorage.getItem("apollo_token"));
    expect(token).toBeNull();
  });
});
