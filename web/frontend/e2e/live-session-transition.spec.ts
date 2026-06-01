import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.0.1 — Track-transition reliability regression.
 * v3.4 update — adapted for AudioBufferSourceNode substrate.
 *
 * Original failure (v2.5.0): live session plays the first track cleanly,
 * but at end-of-track audio just stops — no crossfade, no next track.
 * Backend logs showed the second track's ``/api/tracks/.../stream``
 * was never requested.
 *
 * Original root cause: the engine's watchdog is event-sourced from the
 * browser's ``playback_pos`` ping. When ``<audio>`` finished naturally
 * it paused and froze ``currentTime`` — the ping value flatlined, the
 * threshold was never crossed, the engine never advanced.
 *
 * Original fix: forward the ``<audio>`` element's natural ``ended``
 * event as a synthetic ``{type: track_ended}`` WS message. The backend's
 * ``LiveEngineBrowser.report_track_ended`` advances the cursor and emits
 * ``track_started`` for the next track. Backend "endgame safeguard"
 * inside ``report_playback_pos`` also fires the same advance when
 * ``current_time`` lands within the last 2 s of the track.
 *
 * v3.4 — playback substrate moved to AudioBufferSourceNode. The
 * end-of-track signal is now ``source.onended`` (a callback on the
 * source instance) rather than an ``ended`` event on a DOM element.
 * Forwarding still happens the same way (synthetic ``track_ended`` WS
 * message); only the test harness's way of *firing* the end changes —
 * we patch ``AudioContext.prototype.createBufferSource`` to register
 * every created source and then invoke ``onended`` directly on the
 * active one. Stream URL network proof is unchanged because v3.4
 * still hits the same ``/api/tracks/.../stream`` endpoint to fetch
 * MP3 bytes before decoding (the URL is the load mechanism; decode is
 * what changed).
 */

test.describe("v2.5.0.1 — track transition advances on natural end", () => {
  test("second track stream is requested after first track ends", async ({
    page,
    request,
  }) => {
    // v3.4 — three init-script patches make the test self-contained
    // against the v3.4 substrate without needing the E2E backend to
    // actually serve a valid audio file:
    //
    // (1) Wrap fetch to short-circuit stream URLs with a synthetic OK
    //     response. We ALSO fire the real underlying request via the
    //     original fetch (and discard the result) so Playwright's
    //     page.on("request") still captures the URL — the existing
    //     network-proof assertion ("both stream URLs requested") keeps
    //     working unchanged.
    // (2) Stub AudioContext.decodeAudioData to return a 1 s silent
    //     PCM buffer regardless of input. The synthetic empty
    //     ArrayBuffer from (1) won't decode for real, so we bypass
    //     decoding entirely and hand the deck a working buffer.
    // (3) Wrap AudioContext.createBufferSource to register every
    //     source in window.__apolloE2ESources so the test can later
    //     find the active one and fire its onended directly (the v3.4
    //     analogue of dispatching "ended" on a DOM element).
    await page.addInitScript(() => {
      // (1) — fetch shim for /api/tracks/*/stream
      const origFetch = window.fetch;
      window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        if (/\/api\/tracks\/[^/]+\/stream/.test(url)) {
          // Fire-and-forget the real request so the page.on("request")
          // listener captures the URL; we discard its (potentially
          // 404) response.
          try {
            origFetch(input, init).catch(() => {});
          } catch {
            /* ignore */
          }
          return new Response(new ArrayBuffer(8), {
            status: 200,
            statusText: "OK",
          });
        }
        return origFetch(input, init);
      };

      type Ctx = typeof AudioContext;
      const Ctor: Ctx | undefined =
        (window as unknown as { AudioContext?: Ctx }).AudioContext ??
        (window as unknown as { webkitAudioContext?: Ctx }).webkitAudioContext;
      if (!Ctor) return;

      // (2) — stub decodeAudioData to return a 1 s silent stereo buffer.
      Ctor.prototype.decodeAudioData = function (
        _arrayBuffer: ArrayBuffer,
        success?: (buf: AudioBuffer) => void,
        _error?: (e: Error) => void,
      ): Promise<AudioBuffer> {
        const buf = this.createBuffer(2, 44100, 44100);
        if (success) success(buf);
        return Promise.resolve(buf);
      };

      // (3) — register every AudioBufferSourceNode.
      const origCreate = Ctor.prototype.createBufferSource;
      const sources: AudioBufferSourceNode[] = [];
      Ctor.prototype.createBufferSource = function () {
        const src = origCreate.call(this);
        sources.push(src);
        return src;
      };
      (
        window as unknown as { __apolloE2ESources?: AudioBufferSourceNode[] }
      ).__apolloE2ESources = sources;
    });

    const e2eUser = await signedInOnDashboard(page, request);

    // 1. Walk planning to ckpt1 so ctx.playlist is persisted.
    await gotoNewSession(page, request, e2eUser);
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

    // v3.4 — fire the active source's onended directly. The hook
    // wraps the user-supplied onended around the source's natural one
    // (the wrapper clears the deck's source ref and forwards the
    // synthetic ``track_ended`` WS message). The active source is the
    // one with an onended set — BufferDeck assigns it on every
    // scheduleSource() call. Be defensive: BufferDeck may need a beat
    // to actually create the source after the autoplay overlay
    // dismissal, so poll briefly.
    await page.waitForFunction(
      () => {
        const sources = (
          window as unknown as { __apolloE2ESources?: AudioBufferSourceNode[] }
        ).__apolloE2ESources;
        return !!sources && sources.some((s) => typeof s.onended === "function");
      },
      { timeout: 5000 },
    );
    await page.evaluate(() => {
      const sources = (
        window as unknown as { __apolloE2ESources?: AudioBufferSourceNode[] }
      ).__apolloE2ESources;
      if (!sources || sources.length === 0) return;
      // The active source is the most recently created one with a live
      // onended handler — BufferDeck.stop() clears the prior source's
      // onended before stop()ping it, so only the active source still
      // has a callable handler.
      const active = [...sources]
        .reverse()
        .find((s) => typeof s.onended === "function");
      if (active && active.onended) {
        active.onended.call(active, new Event("ended"));
      }
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
