import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.2 — Mic perception E2E.
 *
 * Walks the planning flow until ``ckpt1`` (so the backend has a playlist),
 * navigates to ``/live``, then toggles the new "Mic perception" switch.
 *
 * The browser's real ``getUserMedia`` is patched via ``addInitScript`` so
 * the mic toggle resolves a fake stream + analyser, the LiveStage level
 * meter renders, and the WS-side mock pipeline emits the v2.5.2
 * ``dj_chat`` "Reading the room." acknowledgement on the first sample.
 */

// Patch getUserMedia / AudioContext so mic perception can boot without
// hardware. Raw audio never leaves anywhere - this is just enough plumbing
// for the module to do its lifecycle. Defined as a real function so
// Playwright's addInitScript can serialise it without templating quirks.
function installMicStub() {
  const fakeAudioCtx = function () {
    const fakeAnalyser = {
      fftSize: 2048,
      smoothingTimeConstant: 0.85,
      frequencyBinCount: 1024,
      getByteTimeDomainData(buf: Uint8Array) {
        for (let i = 0; i < buf.length; i++) buf[i] = 128;
      },
      getByteFrequencyData(buf: Uint8Array) {
        for (let i = 0; i < buf.length; i++) buf[i] = 0;
      },
      disconnect() {},
    };
    const fakeSource = { connect() {}, disconnect() {} };
    return {
      createMediaStreamSource() {
        return fakeSource;
      },
      createAnalyser() {
        return fakeAnalyser;
      },
      close() {
        return Promise.resolve();
      },
    };
  };
  Object.defineProperty(window, "AudioContext", {
    value: fakeAudioCtx,
    configurable: true,
  });
  Object.defineProperty(window, "webkitAudioContext", {
    value: fakeAudioCtx,
    configurable: true,
  });
  // jsdom doesn't ship navigator.mediaDevices — patch unconditionally.
  type GUM = (
    constraints: MediaStreamConstraints,
  ) => Promise<MediaStream>;
  const fakeGetUserMedia: GUM = () =>
    Promise.resolve({
      getTracks() {
        return [{ stop() {} }];
      },
    } as unknown as MediaStream);
  if (!navigator.mediaDevices) {
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: fakeGetUserMedia },
      configurable: true,
    });
  } else {
    (navigator.mediaDevices as unknown as { getUserMedia: GUM }).getUserMedia =
      fakeGetUserMedia;
  }
}

test.describe("v2.5.2 — mic perception", () => {
  test("mic toggle starts perception, level meter renders, dj_chat surfaces", async ({
    page,
    request,
  }) => {
    await page.addInitScript(installMicStub);

    await signedInOnDashboard(page, request);

    // Walk planning to ckpt1 so ctx.playlist is seeded.
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // Navigate to /live and dismiss the autoplay overlay if present.
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

    // The mic toggle is OFF by default (privacy). Flip it ON.
    const toggle = page.getByTestId("mic-perception-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toBeChecked();
    await toggle.check();
    await expect(toggle).toBeChecked();

    // The level meter renders once the API has booted.
    await expect(page.getByTestId("mic-level-meter")).toBeVisible({
      timeout: 5000,
    });

    // The mock backend echoes the first perception sample as a dj_chat
    // event ("Reading the room."). It only takes one publish interval
    // (~2 s) for the fake mic to push a sample.
    await expect(page.getByTestId("dj-chat-list")).toBeVisible({
      timeout: 10000,
    });
    const firstEntry = page.getByTestId("dj-chat-entry").first();
    await expect(firstEntry).toContainText(/reading the room/i, {
      timeout: 10000,
    });

    // Toggling OFF cleans up — meter disappears.
    await toggle.uncheck();
    await expect(toggle).not.toBeChecked();
    await expect(page.getByTestId("mic-level-meter")).toHaveCount(0);
  });
});
