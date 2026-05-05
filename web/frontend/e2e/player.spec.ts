import { test, expect } from "@playwright/test";
import { registerViaApi, installToken } from "./fixtures/auth";

/**
 * v2.2.0 — Persistent in-browser player.
 *
 * Login → /catalog → click play on a tile → mini-player visible →
 * navigate to /dashboard → mini-player still visible → click pause →
 * state reflects paused.
 */
test.describe("v2.2.0 — player", () => {
  test("plays a track from /catalog and the mini-player persists across navigation", async ({
    page,
    request,
  }) => {
    const user = await registerViaApi(request);
    await installToken(page, user);

    await page.goto("/catalog");
    // The mock backend exposes a single track ("Mock Silence") — wait until
    // it's rendered before clicking the hover-only play button.
    await expect(page.locator("text=Mock Silence").first()).toBeVisible();

    // Hover the card to reveal the play button.
    const card = page.locator("text=Mock Silence").first();
    await card.hover();
    const playBtn = page.locator('[data-testid="track-card-play"]').first();
    await playBtn.click({ force: true });

    // Mini-player surfaces with the track name.
    await expect(page.locator('[data-testid="mini-player"]')).toBeVisible();
    await expect(page.locator('[data-testid="mini-player-title"]')).toHaveText(
      /Mock Silence/i,
    );

    // Soft-navigate to /dashboard via the in-page link — that's what
    // exercises the "audio survives the route change" guarantee. A hard
    // page.goto() would reload the React tree and reset everything.
    await page.getByRole("button", { name: /← Dashboard/i }).click();
    await page.waitForURL(/\/dashboard$/);
    await expect(page.locator('[data-testid="mini-player"]')).toBeVisible();
    await expect(page.locator('[data-testid="mini-player-title"]')).toHaveText(
      /Mock Silence/i,
    );

    // Click pause and verify the icon flips back to ▶.
    await page.locator('[data-testid="mini-player-toggle"]').click();
    await expect(page.locator('[data-testid="mini-player-toggle"]')).toHaveText(
      /▶/,
    );
  });

  test("hitting the stream endpoint returns audio for a known track id", async ({
    request,
  }) => {
    const user = await registerViaApi(request);
    const url = `http://localhost:8801/api/tracks/mock-lofi-silence/stream?token=${encodeURIComponent(
      user.token,
    )}`;
    const res = await request.get(url);
    expect(res.status(), `stream failed: ${await res.text()}`).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/audio\/(wav|x-wav)/);
  });
});
