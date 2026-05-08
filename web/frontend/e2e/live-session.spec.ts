import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.1 — Live performance smoke E2E.
 *
 * The mock backend's ``fake_phase_live`` is a deterministic stub that:
 *   1. Calls ``engine.play(playlist)`` — the engine emits ``track_started``
 *      for the first track and a ``load`` engine_command for the browser.
 *   2. Synthesises a single ``approaching_crossfade`` event so the UI shows
 *      its countdown widget.
 *   3. Acks ``user_msg`` commands ("skip" / "stay" / etc.) by calling the
 *      matching engine method (no LLM in the loop).
 *
 * This spec drives the UI through the full path: log in → walk the
 * planning flow until ckpt1 (which seeds ctx.playlist) → navigate to
 * /session/{id}/live → assert the live stage, the first track, and that
 * "Skip" lands on the second track. We deliberately use the UI-driven
 * planning flow instead of opening a raw WebSocket from the test process:
 * Node 20's global ``WebSocket`` only landed in 22, and the CI runner
 * uses 20.x, so a top-level ``new WebSocket(...)`` would be a
 * ReferenceError there.
 */

test.describe("v2.5.1 — live performance bridge", () => {
  test("live page renders, shows first track, and Skip advances", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);

    // 1. Create a session and walk through the planning flow until ckpt1
    //    so the backend persists ctx.playlist into the session — the live
    //    WS rejects sessions with no playlist.
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const url = page.url();
    const sid = url.split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // 2. Navigate to the live page directly.
    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("live-stage")).toBeVisible({
      timeout: 15000,
    });

    // 3. Wait for the WS handshake + the engine's first track_started to
    //    propagate into the now-playing card.
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 1",
      { timeout: 15000 },
    );

    // 3b. Headless Chromium blocks autoplay without a prior user gesture
    //     (we navigated to /live programmatically). The UI surfaces a
    //     click-to-start overlay — dismiss it so the action buttons are
    //     reachable.
    const resumeBtn = page.getByTestId("live-autoplay-resume");
    if (await resumeBtn.isVisible().catch(() => false)) {
      await resumeBtn.click();
      await expect(page.getByTestId("live-autoplay-overlay")).toHaveCount(0);
    }

    // 4. Skip → mock engine advances to the second track and emits
    //    track_started for it. The UI reflects it in the now-playing card.
    await page.getByTestId("live-skip").click();
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 2",
      { timeout: 15000 },
    );

    // 5. The visual layer slot is intentionally a placeholder in v2.5.1 —
    //    Agente D fills it in v2.5.3.
    await expect(page.getByTestId("visual-slot")).toBeVisible();
  });

  /**
   * v2.5.1.1 — Go Live button surfaces at phase=editing.
   *
   * Live mode is an *alternative* to Build, not a sequel. The button used to
   * live only at phase=rating / phase=complete which forced the user to
   * render the mp4 first. This test walks the planning UI up to phase=editing
   * (after ckpt2 approve) and asserts the Go Live button is reachable there
   * and navigates to /session/{id}/live without going through Build/Rate.
   */
  test("Go Live button surfaces at phase=editing as alternative to Build", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);

    // Create session and walk planning flow to ckpt1 → ckpt2 → editing.
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // Approve playlist → critic → ckpt2.
    await page.getByRole("button", { name: /run the critic/i }).click();
    await expectPhase(page, "ckpt2");

    // Approve critique → editing.
    await page.getByRole("button", { name: /continue to editor/i }).click();
    await expectPhase(page, "editing");

    // The new Go Live button must be visible alongside the EditorInput,
    // BEFORE any build/rate happens.
    const goLive = page.getByTestId("go-live-button");
    await expect(goLive).toBeVisible();

    // Click → navigate to /session/{id}/live without rendering an mp4 first.
    await goLive.click();
    await page.waitForURL(new RegExp(`/session/${sid}/live`));
    expect(page.url()).toMatch(new RegExp(`/session/${sid}/live$`));
  });
});
