import { expect, test } from "@playwright/test";

test("catalog player follows search results without interrupting the song", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("apollo_token", "catalog-layout-test");
    localStorage.setItem("apollo_user", JSON.stringify({ id: 1, username: "listener" }));
    class TestAudio extends EventTarget {
      src = ""; paused = true; duration = 180; currentTime = 0; volume = 1;
      async play() { this.paused = false; this.dispatchEvent(new Event("play")); this.dispatchEvent(new Event("loadedmetadata")); }
      pause() { this.paused = true; this.dispatchEvent(new Event("pause")); }
      load() {}
      removeAttribute() { this.src = ""; }
    }
    Object.defineProperty(window, "Audio", { value: TestAudio, configurable: true });
  });
  const tracks = ["Amber", "Blue", "Cloud"].map((display_name, i) => ({
    id: String(i), display_name, bpm: 100, camelot_key: "8A", duration_sec: 180,
    genre: i < 2 ? "ambient" : "house", genre_folder: i < 2 ? "ambient" : "house", user_rating: i === 1 ? 5 : null,
  }));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/catalog") {
      await route.fulfill({ json: { genres: ["ambient", "house"], tracks: tracks.filter((t) => !url.searchParams.get("genre") || t.genre === url.searchParams.get("genre")) } });
    } else await route.fulfill({ json: { available: false } });
  });
  await page.goto("/catalog");
  const player = page.getByRole("region", { name: "Catalog player" });
  await expect(player).toBeInViewport({ ratio: 1, timeout: 15000 });
  await page.getByRole("button", { name: "Play results", exact: true }).click();
  await expect(page.getByTestId("catalog-player-title")).toHaveText("Amber");
  await page.getByPlaceholder("search name · tag · key…").fill("Blue");
  await expect(page.getByTestId("track-card")).toHaveCount(1);
  await expect(page.getByTestId("catalog-queue-summary")).toContainText("1 tracks");
  await expect(page.getByTestId("catalog-player-title")).toHaveText("Amber");
  await page.getByRole("button", { name: "Next track", exact: true }).click();
  await expect(page.getByTestId("catalog-player-title")).toHaveText("Blue");
  await expect(page.getByRole("button", { name: "Next track", exact: true })).toBeDisabled();
  await page.getByPlaceholder("search name · tag · key…").fill("no matches");
  await expect(page.getByRole("button", { name: "Play results", exact: true })).toBeDisabled();
  await page.getByPlaceholder("search name · tag · key…").fill("");
  await page.getByTestId("favorites-filter").click();
  await expect(page.getByTestId("track-card")).toHaveCount(1);
  await expect(page.getByTestId("catalog-queue-summary")).toContainText("Favorites");
  await page.getByTestId("favorites-filter").click();
  await page.getByRole("button", { name: "house", exact: true }).click();
  await expect(page.getByTestId("track-card")).toHaveCount(1);
  await expect(page.getByTestId("track-card")).toContainText("Cloud");
  await page.getByRole("button", { name: "Next track", exact: true }).click();
  await expect(page.getByTestId("catalog-player-title")).toHaveText("Cloud");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(player).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeInViewport({ ratio: 1 });
});
