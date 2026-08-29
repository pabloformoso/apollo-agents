import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * G1 — "Generate (ACE)" in the wizard's track-selection stage.
 *
 * Walks the real UI: Editor → the Generate tile → the Suno-surface form →
 * submit → the task card (queue position + ETA countdown) → the takes with
 * their metadata chips and the disabled G2 publish seam.
 *
 * `/api/generator/*` is stubbed with the house pattern — an `addInitScript`
 * wrapper around `window.fetch` (same shape as the transition spec's stream
 * shim). That keeps the spec independent of whether the ACE box is on, and
 * lets us script a **degraded poll**: the first two polls come back
 * `{status: "pending", degraded: true}`, which must show as a quiet blip and
 * must NOT tear the task card down. `/api/catalog` is stubbed too so the
 * genre select is deterministic; everything else (auth, sessions, the phase
 * machine) hits the real E2E backend.
 */

test.describe("G1 — generate a track with ACE from the editor", () => {
  test("form → submit → task card → takes rendered", async ({
    page,
    request,
  }) => {
    await page.addInitScript(() => {
      const origFetch = window.fetch;
      const state = { polls: 0, postBody: null as string | null };
      (window as unknown as { __ace?: typeof state }).__ace = state;

      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });

      const TAKES = [
        {
          index: 0,
          file: "outputs/ace/e2e_0.wav",
          prompt: "warm lofi keys",
          lyrics: "",
          metas: {
            bpm: 82,
            duration: 181.4,
            genres: "lofi",
            keyscale: "A minor",
            timesignature: "4/4",
          },
          seed_value: 4242,
        },
        {
          index: 1,
          file: "outputs/ace/e2e_1.wav",
          prompt: "warm lofi keys",
          lyrics: "",
          metas: {
            bpm: 80,
            duration: 176,
            genres: "lofi",
            keyscale: "C major",
            timesignature: "4/4",
          },
          seed_value: 99,
        },
      ];

      window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        const method = (init?.method ?? "GET").toUpperCase();

        if (/\/api\/generator\/health/.test(url)) {
          return json({
            available: true,
            blocked_by_live: false,
            stats: { avg_job_seconds: 40, queue_size: 1 },
          });
        }
        if (/\/api\/generator\/tasks$/.test(url) && method === "POST") {
          state.postBody =
            typeof init?.body === "string" ? init.body : null;
          return json({
            task_id: "e2e-task-1",
            queue_position: 2,
            eta_seconds: 42,
          });
        }
        if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
          state.polls += 1;
          // Two degraded polls, then a clean one, then the result. The
          // degraded pair is the point: a blip must not fail the task.
          if (state.polls <= 2) {
            return json({
              status: "pending",
              eta_seconds: 30 - state.polls * 5,
              degraded: true,
            });
          }
          if (state.polls === 3) {
            return json({ status: "pending", eta_seconds: 6 });
          }
          return json({ status: "done", takes: TAKES, eta_seconds: 0 });
        }
        if (/\/api\/generator\/audio/.test(url)) {
          return new Response(new ArrayBuffer(8), { status: 200 });
        }
        if (/\/api\/catalog/.test(url)) {
          return json({
            tracks: [],
            genres: ["lofi - ambient", "deep house", "techno"],
          });
        }
        return origFetch(input, init);
      };
    });

    const user = await signedInOnDashboard(page, request);

    // Drive planning to ckpt1 so the session has a persisted playlist — the
    // Editor's track row (where the Generate tile lives) only renders once
    // there are tracks.
    await gotoNewSession(page, request, user);
    const sid = page.url().split("/session/")[1].split("/")[0];
    await page
      .getByPlaceholder(/60-minute cyberpunk set/i)
      .fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    // ── The affordance sits beside "Add a track" ──────────────────────────
    await page.goto(`/editor?session=${sid}`);
    await expect(
      page.getByRole("button", { name: /add a track/i }),
    ).toBeVisible({ timeout: 15_000 });

    const tile = page.getByTestId("generator-open");
    await expect(tile).toBeVisible({ timeout: 10_000 });
    await expect(tile).toBeEnabled();
    await tile.click();

    // ── The Suno surface ──────────────────────────────────────────────────
    await expect(page.getByTestId("generator-dialog")).toBeVisible();
    await page
      .getByTestId("generator-prompt")
      .fill("warm lofi keys, dusty tape hiss, rain on a window");
    await page
      .getByTestId("generator-lyrics")
      .fill("[Verse]\nrain on the window\n\n[Chorus]\nstay a while");
    await page.getByTestId("generator-duration").fill("240");
    await page.getByTestId("generator-language").selectOption("en");
    await page.getByTestId("generator-genre").selectOption("deep house");
    await page.getByTestId("generator-batch").fill("2");

    // Experimental starts collapsed; open it and pin the seed.
    const expToggle = page.getByTestId("generator-experimental-toggle");
    await expect(expToggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("generator-seed")).toHaveCount(0);
    await expToggle.click();
    await page.getByTestId("generator-seed").fill("4242");

    await page.getByTestId("generator-submit").click();

    // ── The task card ─────────────────────────────────────────────────────
    const card = page.getByTestId("generator-task-card");
    await expect(card).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("generator-queue-position")).toContainText(
      /queue position 2/i,
    );
    await expect(page.getByTestId("generator-eta")).toContainText(
      /~\d+s left|any second now/,
    );

    // The degraded polls read as a quiet blip, not an error — and the card
    // is still standing.
    await expect(page.getByTestId("generator-degraded")).toBeVisible({
      timeout: 8_000,
    });
    await expect(page.getByTestId("generator-error")).toHaveCount(0);

    // The form sent the contract's shape.
    const posted = await page.evaluate(
      () => (window as unknown as { __ace?: { postBody: string | null } }).__ace?.postBody,
    );
    expect(posted).toBeTruthy();
    const body = JSON.parse(posted as string);
    expect(body.genre_folder).toBe("deep house");
    expect(body.audio_duration).toBe(240);
    expect(body.batch_size).toBe(2);
    expect(body.vocal_language).toBe("en");
    expect(body.lyrics).toContain("[Verse]");
    expect(body.experimental.seed).toBe(4242);

    // ── The takes ─────────────────────────────────────────────────────────
    const takes = page.getByTestId("generator-take");
    await expect(takes).toHaveCount(2, { timeout: 25_000 });
    // The blip cleared once a clean poll landed.
    await expect(page.getByTestId("generator-degraded")).toHaveCount(0);

    const first = takes.first();
    await expect(first).toContainText("Take 1");
    await expect(first).toContainText("82 BPM");
    await expect(first).toContainText("A minor");
    await expect(first).toContainText("3:01");
    await expect(first).toContainText("seed 4242");
    await expect(first.getByTestId("generator-take-play")).toBeVisible();

    // G2b brought this to life — the seam it used to mark is now the
    // publish flow (walked in `generator-publish.spec.ts`); here it only
    // has to be present and offered.
    const publish = page.getByTestId("generator-publish").first();
    await expect(publish).toBeEnabled();
    await expect(publish).toContainText(/publish to catalog/i);
  });
});
