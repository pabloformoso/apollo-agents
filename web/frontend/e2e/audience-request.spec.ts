import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.2 — Audience request E2E.
 *
 * The audience uses the existing free-form chat textarea to send a
 * message that isn't a control word ("skip"/"stay"). The mock pipeline
 * replies with a polite ``dj_chat`` event — proxy of the real DJ's
 * "noted, but staying course" path — and the new dj_chat panel renders
 * the reply.
 */

test.describe("v2.5.2 — audience request", () => {
  test("free-form chat post produces a dj_chat reply in the panel", async ({
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
    await expect(page.getByTestId("live-stage")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 1",
      { timeout: 15000 },
    );
    const resumeBtn = page.getByTestId("live-autoplay-resume");
    if (await resumeBtn.isVisible().catch(() => false)) {
      await resumeBtn.click();
      await expect(page.getByTestId("live-autoplay-overlay")).toHaveCount(0);
    }

    // The dj_chat panel starts empty.
    await expect(page.getByTestId("dj-chat-empty")).toBeVisible();

    // Submit a free-form audience request.
    const chat = page.getByTestId("live-chat-input");
    await chat.fill("anything classic disco-y?");
    await page.getByTestId("live-chat-send").click();

    // The mock pipeline emits a dj_chat event in response. The panel
    // surfaces it.
    await expect(page.getByTestId("dj-chat-list")).toBeVisible({
      timeout: 10000,
    });
    const entry = page.getByTestId("dj-chat-entry").first();
    await expect(entry).toContainText(/staying the course|heard/i, {
      timeout: 10000,
    });
  });
});
