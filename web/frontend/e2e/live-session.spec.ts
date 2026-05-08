import { test, expect } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";

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
 * This spec drives the UI through the full path: log in → seed playlist
 * via the API → navigate to /session/{id}/live → assert the live stage,
 * the first track, and that "Skip" lands on the second track.
 */

const API_BASE = process.env.APOLLO_E2E_API ?? "http://localhost:8801";

async function seedSession(
  request: import("@playwright/test").APIRequestContext,
  token: string,
): Promise<string> {
  // Create a fresh session.
  const create = await request.post(`${API_BASE}/api/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(create.ok(), `create session failed: ${await create.text()}`).toBeTruthy();
  const sid = (await create.json()).id as string;

  // Drive a single genre_intent through the WS so the planning phase fires
  // and seeds ``ctx.playlist`` — that's exactly what the live WS expects on
  // the session. Doing this via the real WS is the cheapest setup that
  // mirrors a real flow without coupling the spec to the planning UI.
  const wsBase = (process.env.APOLLO_E2E_WS ?? API_BASE).replace(
    /^http/,
    "ws",
  );
  await new Promise<void>((resolve, reject) => {
    const ws = new WebSocket(
      `${wsBase}/ws/sessions/${sid}?token=${encodeURIComponent(token)}`,
    );
    let receivedPhaseComplete = false;
    const timeout = setTimeout(() => {
      ws.close();
      if (receivedPhaseComplete) resolve();
      else reject(new Error("planning never landed"));
    }, 15000);
    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          type: "genre_intent",
          content: "30-minute lofi set, calm",
        }),
      );
    };
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data as string) as {
          type?: string;
          phase?: string;
        };
        if (data.type === "phase_complete" && data.phase === "planning") {
          receivedPhaseComplete = true;
          clearTimeout(timeout);
          ws.close();
          resolve();
        }
      } catch {
        /* ignore */
      }
    };
    ws.onerror = () => {
      clearTimeout(timeout);
      reject(new Error("session WS error"));
    };
  });
  return sid;
}

test.describe("v2.5.1 — live performance bridge", () => {
  test("live page renders, shows first track, and Skip advances", async ({
    page,
    request,
  }) => {
    const user = await signedInOnDashboard(page, request);
    const sid = await seedSession(request, user.token);

    await page.goto(`/session/${sid}/live`);
    await expect(page.getByTestId("live-stage")).toBeVisible({ timeout: 15000 });

    // Allow the WS to handshake, the engine to emit track_started, and the
    // hook to update the "current track" card.
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 1",
      { timeout: 15000 },
    );

    // Skip → the mock engine advances to the second track and emits
    // track_started for it, which the UI reflects in the now-playing card.
    await page.getByTestId("live-skip").click();
    await expect(page.getByTestId("live-current-track-name")).toContainText(
      "Track 2",
      { timeout: 15000 },
    );

    // The visual layer slot is intentionally a placeholder in v2.5.1 —
    // Agente D fills it in v2.5.3.
    await expect(page.getByTestId("visual-slot")).toBeVisible();
  });
});
