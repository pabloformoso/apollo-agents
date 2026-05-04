import { test, expect } from "@playwright/test";
import { registerViaApi, installToken } from "./fixtures/auth";

/**
 * v2.2.2 — Per-user track ratings + favorites filter.
 *
 * Login → catalog → 5★ a track → reload → rating persists. Then rate two more
 * tracks 4★ and one 3★, toggle the "★ Favoritos" chip and confirm only ≥4★
 * tracks remain. Finally, click the filled 5★ to clear the rating and confirm
 * the track drops out of the filtered list.
 */
const API_BASE = process.env.APOLLO_E2E_API ?? "http://localhost:8801";

async function setRatingViaApi(
  request: import("@playwright/test").APIRequestContext,
  token: string,
  trackId: string,
  rating: number,
): Promise<void> {
  // Reset before each test run so previous-spec state doesn't leak in.
  await request.delete(`${API_BASE}/api/tracks/${encodeURIComponent(trackId)}/rating`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (rating > 0) {
    const res = await request.put(
      `${API_BASE}/api/tracks/${encodeURIComponent(trackId)}/rating`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { rating },
      },
    );
    expect(res.ok(), `rating PUT failed: ${await res.text()}`).toBeTruthy();
  }
}

test.describe("v2.2.2 — ratings", () => {
  test("rate a track → reload → rating persists", async ({ page, request }) => {
    const user = await registerViaApi(request);
    await installToken(page, user);
    await page.goto("/catalog");

    // Wait for the catalog grid to render.
    await expect(page.locator("text=Mock Silence").first()).toBeVisible();

    // Find the card for "Mock Silence" and click its 5th star.
    const card = page
      .locator(".group.bg-surface")
      .filter({ hasText: "Mock Silence" })
      .first();
    await expect(card).toBeVisible();
    await card.locator('[data-testid="star-5"]').click();

    // Optimistic update — the star should be filled (★) immediately.
    await expect(card.locator('[data-testid="star-5"]')).toHaveAttribute(
      "data-filled",
      "true",
    );

    // Reload and confirm the rating survives a full page round-trip.
    await page.reload();
    await expect(page.locator("text=Mock Silence").first()).toBeVisible();
    const cardAfter = page
      .locator(".group.bg-surface")
      .filter({ hasText: "Mock Silence" })
      .first();
    await expect(cardAfter.locator('[data-testid="star-5"]')).toHaveAttribute(
      "data-filled",
      "true",
    );
  });

  test("favorites filter shows only tracks with rating ≥ 4", async ({
    page,
    request,
  }) => {
    const user = await registerViaApi(request);
    // Pre-seed via API — much faster than driving the UI for 4 separate
    // ratings, and we already exercise the full UI path in the test above.
    await setRatingViaApi(request, user.token, "mock-lofi-silence", 5);
    await setRatingViaApi(request, user.token, "mock-lofi-alpha", 4);
    await setRatingViaApi(request, user.token, "mock-lofi-bravo", 4);
    await setRatingViaApi(request, user.token, "mock-lofi-charlie", 3);

    await installToken(page, user);
    await page.goto("/catalog");

    await expect(page.locator("text=Mock Silence").first()).toBeVisible();
    await expect(page.locator("text=Mock Charlie").first()).toBeVisible();

    // Toggle the "★ Favoritos" filter chip.
    await page.locator('[data-testid="favorites-filter"]').click();

    // The 3★ track should now be hidden; the 4★ and 5★ ones stay visible.
    await expect(page.locator("text=Mock Silence").first()).toBeVisible();
    await expect(page.locator("text=Mock Alpha").first()).toBeVisible();
    await expect(page.locator("text=Mock Bravo").first()).toBeVisible();
    await expect(page.locator("text=Mock Charlie")).toHaveCount(0);

    // Click the already-filled 5★ on Mock Silence. Because that track had
    // rating === 5, clicking the same star fires onClear and the track
    // drops below the favorites threshold.
    const silenceCard = page
      .locator(".group.bg-surface")
      .filter({ hasText: "Mock Silence" })
      .first();
    await silenceCard.locator('[data-testid="star-5"]').click();

    await expect(page.locator("text=Mock Silence")).toHaveCount(0);
    // The 4★ tracks remain.
    await expect(page.locator("text=Mock Alpha").first()).toBeVisible();
    await expect(page.locator("text=Mock Bravo").first()).toBeVisible();
  });
});
