import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.0.1 — Track-transition reliability regression.
 *
 * The user reported (v2.5.0 final): live session plays the first track
 * cleanly, but at end-of-track audio just stops — no crossfade, no next
 * track. Backend logs showed the second track's ``/api/tracks/.../stream``
 * was never requested.
 *
 * Root cause: the engine's watchdog is event-sourced from the browser's
 * ``playback_pos`` ping. When ``<audio>`` finishes naturally it pauses
 * and freezes ``currentTime`` — the ping value flatlines, the threshold
 * is never crossed, the engine never advances.
 *
 * Fix: forward the ``<audio>`` element's natural ``ended`` event as a
 * synthetic ``{type: track_ended}`` WS message. The backend's
 * ``LiveEngineBrowser.report_track_ended`` advances the cursor and emits
 * ``track_started`` for the next track. There's also a backend-side
 * "endgame safeguard" inside ``report_playback_pos`` that fires the same
 * advance when ``current_time`` lands within the last 2 s of the track —
 * belt-and-braces in case the ``ended`` event is lost.
 *
 * This spec drives the UI through the planning flow → live page, then
 * monitors the network for the second track's ``/stream`` request after
 * the first track's natural end. The mock backend serves a 1 s silence
 * WAV per track, so end-of-track happens deterministically inside the
 * first ~2 s of the live session.
 */

test.describe("v2.5.0.1 — track transition advances on natural end", () => {
  test("second track stream is requested after first track ends", async ({
    page,
    request,
  }) => {
    // Register the Audio constructor wrapper *before* any page script
    // runs so the hook's ``new Audio()`` calls land in our registry.
    // We can then ``dispatchEvent('ended')`` from the test process.
    await page.addInitScript(() => {
      const OrigAudio = window.Audio;
      const audios: HTMLAudioElement[] = [];
      // Replace the constructor with a thin wrapper that pushes into
      // the registry and otherwise delegates.
      class TrackedAudio extends OrigAudio {
        constructor(...args: ConstructorParameters<typeof Audio>) {
          super(...args);
          audios.push(this);
        }
      }
      window.Audio = TrackedAudio as unknown as typeof Audio;
      (
        window as unknown as { __apolloE2EAudios?: HTMLAudioElement[] }
      ).__apolloE2EAudios = audios;
    });

    await signedInOnDashboard(page, request);

    // 1. Walk planning to ckpt1 so ctx.playlist is persisted.
    await page.getByRole("button", { name: /new session/i }).click();
    await page.waitForURL(/\/session\/[0-9a-f-]+/);
    const sid = page.url().split("/session/")[1].split("/")[0];

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // Capture stream requests so we can prove BOTH track 1 AND track 2
    // were actually fetched. Pre-fix the test would only ever see track 1.
    const streamUrls: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      if (/\/api\/tracks\/[^/]+\/stream/.test(url)) {
        streamUrls.push(url);
      }
    });

    // 2. Open the live page.
    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("live-stage")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 1",
      { timeout: 15000 },
    );

    // Headless Chromium blocks autoplay — dismiss the resume overlay so
    // playback actually starts (and ``ended`` can eventually fire).
    const resumeBtn = page.getByTestId("live-autoplay-resume");
    if (await resumeBtn.isVisible().catch(() => false)) {
      await resumeBtn.click();
      await expect(page.getByTestId("live-autoplay-overlay")).toHaveCount(0);
    }

    // The mock backend serves a 1 s silence WAV. Fire the ``ended`` event
    // explicitly via the registry we set up in addInitScript so the spec
    // is robust to headless audio quirks and runs in milliseconds.
    await page.evaluate(() => {
      const audios = (
        window as unknown as { __apolloE2EAudios?: HTMLAudioElement[] }
      ).__apolloE2EAudios;
      if (!audios || audios.length === 0) return;
      // The active deck is whichever element is non-paused with a
      // src set. Fall back to the latest if none qualify.
      const active =
        audios.find((a) => !a.paused && a.src) ??
        audios.find((a) => a.src) ??
        audios[audios.length - 1];
      active.dispatchEvent(new Event("ended"));
    });

    // 3. Assert the UI now shows Track 2 (regardless of which path —
    //    the explicit ``track_ended`` WS message OR the endgame
    //    safeguard — drove the advance).
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 2",
      { timeout: 15000 },
    );

    // 4. Network proof: BOTH stream URLs were requested. Pre-fix the
    //    test would only ever see one (Track 1's), because the second
    //    never loaded.
    expect(streamUrls.length).toBeGreaterThanOrEqual(2);
    // Confirm two distinct track ids were fetched.
    const ids = new Set(
      streamUrls.map((u) => u.match(/\/tracks\/([^/]+)\/stream/)?.[1] ?? ""),
    );
    expect(ids.size).toBeGreaterThanOrEqual(2);
  });
});
