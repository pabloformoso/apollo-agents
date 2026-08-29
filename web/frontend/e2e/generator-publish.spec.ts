import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * G2b — publishing a generated take into the catalog, from the take's row.
 *
 * Sibling of `generator-wizard.spec.ts` (which walks G1 up to the takes);
 * this one starts where that one stops and walks take → confirm → published.
 *
 * `/api/generator/*` is stubbed with the same house `addInitScript` fetch
 * wrapper, so the spec passes whether or not the ACE box is on. The publish
 * stub does two things worth the trouble:
 *
 *   - it CAPTURES the request body, so the spec can assert the page sent the
 *     take's DECODED path (ACE's `file` is `/v1/audio?path=<percent-encoded
 *     absolute path>`, and the backend wants the inner path) with no task id
 *     anywhere near it — the plan's persistence rule;
 *   - it refuses the first attempt with a real ingest refusal, so the
 *     verbatim-error path is exercised before the happy one.
 *
 * The second take then publishes as a VARIANT of the first, which is the
 * only way two takes of one prompt link as a single piece for the
 * no-repeat machinery.
 */

const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";
const TAKE_0 = `${ACE_ROOT}/e2e-6f1c2b7e_0.wav`;
const TAKE_1 = `${ACE_ROOT}/e2e-6f1c2b7e_1.wav`;

test.describe("G2b — publish a take to the catalog", () => {
  test("take → confirm → refusal → published chip → variant", async ({
    page,
    request,
  }) => {
    await page.addInitScript(
      ([takeZero, takeOne]) => {
        const origFetch = window.fetch;
        const state = {
          publishBodies: [] as string[],
          publishCalls: 0,
        };
        (window as unknown as { __acePub?: typeof state }).__acePub = state;

        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          });

        const take = (index: number, path: string, bpm: number, key: string) => ({
          index,
          // ACE's real `file` shape: the endpoint plus the totally
          // percent-encoded absolute path (slashes as %2F).
          file: `/v1/audio?path=${encodeURIComponent(path)}`,
          prompt: "dark melodic techno, hypnotic, driving",
          lyrics: "",
          metas: {
            bpm,
            duration: 181.4,
            genres: "techno",
            keyscale: key,
            timesignature: "4",
          },
          seed_value: 4242 + index,
        });

        const TAKES = [
          take(0, takeZero, 138, "A Minor"),
          take(1, takeOne, 136, "C Major"),
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
              stats: { avg_job_seconds: 40, queue_size: 0 },
            });
          }
          if (/\/api\/generator\/tasks$/.test(url) && method === "POST") {
            return json({
              task_id: "e2e-pub-1",
              queue_position: 0,
              eta_seconds: 5,
            });
          }
          if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
            return json({ status: "done", takes: TAKES, eta_seconds: 0 });
          }
          if (/\/api\/generator\/publish$/.test(url) && method === "POST") {
            const body = typeof init?.body === "string" ? init.body : "";
            state.publishBodies.push(body);
            state.publishCalls += 1;
            const parsed = JSON.parse(body || "{}");
            // First attempt: a real ingest refusal, verbatim.
            if (state.publishCalls === 1) {
              return json(
                {
                  detail:
                    "bpm 138 is outside the 'healing' window 40-80 BPM",
                },
                422,
              );
            }
            const variant = Boolean(parsed.variant_of);
            return json({
              track_id: variant
                ? "techno--neon-rain-v2"
                : "techno--neon-rain",
              file: variant
                ? "tracks/techno/Neon Rain (1).wav"
                : "tracks/techno/Neon Rain.wav",
              display_name: "Neon Rain",
              camelot_key: variant ? "8B" : "8A",
              bpm: parsed.metas?.bpm ?? 0,
              variant_of: variant ? "Neon Rain" : null,
              note:
                "Ingested without madmom: duration, beatgrid, waveform peaks " +
                "and the MP3 sibling are still missing. Run `python main.py " +
                "--fix-incomplete` before this track goes into a set.",
            });
          }
          if (/\/api\/generator\/audio/.test(url)) {
            return new Response(new ArrayBuffer(8), { status: 200 });
          }
          if (/\/api\/catalog/.test(url)) {
            return json({
              tracks: [],
              genres: ["lofi - ambient", "healing", "techno"],
            });
          }
          return origFetch(input, init);
        };
      },
      [TAKE_0, TAKE_1],
    );

    const user = await signedInOnDashboard(page, request);

    await gotoNewSession(page, request, user);
    const sid = page.url().split("/session/")[1].split("/")[0];
    await page
      .getByPlaceholder(/60-minute cyberpunk set/i)
      .fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/editor?session=${sid}`);
    await expect(
      page.getByRole("button", { name: /add a track/i }),
    ).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("generator-open").click();
    await expect(page.getByTestId("generator-dialog")).toBeVisible();
    await page.getByTestId("generator-prompt").fill("dark melodic techno, hypnotic");
    await page.getByTestId("generator-genre").selectOption("techno");
    await page.getByTestId("generator-submit").click();

    const takes = page.getByTestId("generator-take");
    await expect(takes).toHaveCount(2, { timeout: 25_000 });

    // ── Take 1: confirm ───────────────────────────────────────────────────
    const first = takes.first();
    const publishBtn = first.getByTestId("generator-publish");
    await expect(publishBtn).toBeEnabled();
    await publishBtn.click();

    const confirm = first.getByTestId("generator-publish-confirm");
    await expect(confirm).toBeVisible();
    // The title is prefilled from the prompt and the genre from the form.
    await expect(first.getByTestId("generator-publish-name")).toHaveValue(
      "Dark Melodic Techno",
    );
    await expect(first.getByTestId("generator-publish-genre")).toHaveValue(
      "techno",
    );
    // Nothing published yet, so there is nothing to be a variant of.
    await expect(first.getByTestId("generator-publish-variant")).toHaveCount(0);

    await first.getByTestId("generator-publish-name").fill("Neon Rain");

    // ── The refusal reads verbatim, and the form stays up ─────────────────
    await first.getByTestId("generator-publish-submit").click();
    await expect(first.getByTestId("generator-publish-error")).toContainText(
      "bpm 138 is outside the 'healing' window 40-80 BPM",
    );
    await expect(confirm).toBeVisible();

    // ── Retry lands ───────────────────────────────────────────────────────
    await first.getByTestId("generator-publish-submit").click();

    const chip = first.getByTestId("generator-published");
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toContainText("techno--neon-rain");
    await expect(chip).toContainText("8A");
    await expect(chip).toContainText("--fix-incomplete");
    // The confirm form is gone and the button is inert.
    await expect(first.getByTestId("generator-publish-confirm")).toHaveCount(0);
    await expect(publishBtn).toBeDisabled();
    await expect(publishBtn).toContainText(/published/i);

    // ── What actually went on the wire ────────────────────────────────────
    const bodies = await page.evaluate(
      () =>
        (window as unknown as { __acePub?: { publishBodies: string[] } }).__acePub
          ?.publishBodies ?? [],
    );
    expect(bodies.length).toBe(2);
    const sent = JSON.parse(bodies[1]);
    // The DECODED path, as the page persisted it — never the encoded field,
    // and never a task id (ACE's job records expire; its files do not).
    expect(sent.file).toBe(TAKE_0);
    expect(sent).not.toHaveProperty("task_id");
    expect(sent.display_name).toBe("Neon Rain");
    expect(sent.genre_folder).toBe("techno");
    expect(sent.metas).toEqual({
      bpm: 138,
      keyscale: "A Minor",
      duration: 181.4,
    });
    expect(sent.variant_of).toBeUndefined();

    // ── Take 2 is offered as a variant of the first ───────────────────────
    const second = takes.nth(1);
    await second.getByTestId("generator-publish").click();
    const variantSelect = second.getByTestId("generator-publish-variant");
    await expect(variantSelect).toBeVisible();
    await expect(variantSelect).toHaveValue("Neon Rain");
    await expect(second.getByTestId("generator-publish-name")).toHaveValue(
      "Neon Rain",
    );

    await second.getByTestId("generator-publish-submit").click();
    const secondChip = second.getByTestId("generator-published");
    await expect(secondChip).toBeVisible({ timeout: 10_000 });
    await expect(secondChip).toContainText("techno--neon-rain-v2");
    await expect(secondChip).toContainText("take of Neon Rain");

    const allBodies = await page.evaluate(
      () =>
        (window as unknown as { __acePub?: { publishBodies: string[] } }).__acePub
          ?.publishBodies ?? [],
    );
    const variantSent = JSON.parse(allBodies[2]);
    expect(variantSent.file).toBe(TAKE_1);
    expect(variantSent.variant_of).toBe("Neon Rain");
    expect(variantSent.metas.bpm).toBe(136);

    // The first take stayed published through all of it.
    await expect(first.getByTestId("generator-published")).toBeVisible();
  });

  test("a take with unreadable metadata cannot be published", async ({
    page,
    request,
  }) => {
    await page.addInitScript(() => {
      const origFetch = window.fetch;
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });

      window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        const method = (init?.method ?? "GET").toUpperCase();

        if (/\/api\/generator\/health/.test(url)) {
          return json({ available: true, blocked_by_live: false, stats: {} });
        }
        if (/\/api\/generator\/tasks$/.test(url) && method === "POST") {
          return json({ task_id: "e2e-pub-2", queue_position: 0, eta_seconds: 3 });
        }
        if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
          return json({
            status: "done",
            eta_seconds: 0,
            takes: [
              {
                index: 0,
                file: "/v1/audio?path=%2Ftmp%2Fbroken_0.wav",
                prompt: "warm lofi keys",
                lyrics: "",
                metas: null,
                seed_value: null,
                result_parse_error: "result is not valid JSON",
              },
            ],
          });
        }
        if (/\/api\/catalog/.test(url)) {
          return json({ tracks: [], genres: ["lofi - ambient", "techno"] });
        }
        return origFetch(input, init);
      };
    });

    const user = await signedInOnDashboard(page, request);
    await gotoNewSession(page, request, user);
    const sid = page.url().split("/session/")[1].split("/")[0];
    await page
      .getByPlaceholder(/60-minute cyberpunk set/i)
      .fill("30-minute lofi set, calm");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expectPhase(page, "ckpt1");

    await page.goto(`/editor?session=${sid}`);
    await page.getByTestId("generator-open").click();
    await page.getByTestId("generator-prompt").fill("warm lofi keys");
    await page.getByTestId("generator-submit").click();

    const take = page.getByTestId("generator-take").first();
    await expect(take).toBeVisible({ timeout: 25_000 });

    // No bpm and no key means the catalog would have to guess them, and
    // guessed metadata is what poisoned it in the first place.
    const publish = take.getByTestId("generator-publish");
    await expect(publish).toBeDisabled();
    await expect(publish).toHaveAttribute("title", /BPM or a key/i);
    await publish.click({ force: true });
    await expect(take.getByTestId("generator-publish-confirm")).toHaveCount(0);
  });
});
