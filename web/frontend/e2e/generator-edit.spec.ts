import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * G3 — editing a take before it is trusted, from the take's own row.
 *
 * Sibling of `generator-wizard.spec.ts` (G1, up to the takes) and
 * `generator-publish.spec.ts` (G2b, take → catalog). This one walks
 * take → publish → edit (repaint 10–20 s) → chained card → the edited take,
 * because the interesting claims only show up in that order:
 *
 *   - the chained card is rendered UNDER its source and says where it came
 *     from ("edited from Neon Rain · repaint") — once the source has a
 *     catalog name, the lineage uses that name, not "Take 1";
 *   - the edited take is an ordinary take: it polls, it renders, and it
 *     offers Publish and Edit like any original;
 *   - it is offered `variant of` the SOURCE take's published name, which is
 *     the only way the no-repeat machinery learns the two are one piece;
 *   - what went on the wire is the source take's DECODED path plus the
 *     mode's own parameters, and no task id anywhere (the persistence rule:
 *     ACE's job records expire, its result files do not).
 *
 * `/api/generator/*` is stubbed with the house `addInitScript` fetch
 * wrapper, so the spec passes whether or not the ACE box is on.
 */

const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";
const TAKE_0 = `${ACE_ROOT}/e2e-edit-source_0.wav`;
const EDITED_0 = `${ACE_ROOT}/e2e-edit-result_0.wav`;

test.describe("G3 — edit a take", () => {
  test("take → edit (repaint 10-20s) → chained card → edited take", async ({
    page,
    request,
  }) => {
    await page.addInitScript(
      ([sourcePath, editedPath]) => {
        const origFetch = window.fetch;
        const state = { editBodies: [] as string[], editPolls: 0 };
        (window as unknown as { __aceEdit?: typeof state }).__aceEdit = state;

        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          });

        const take = (index: number, path: string, prompt: string) => ({
          index,
          // ACE's real `file` shape: the endpoint plus the totally
          // percent-encoded absolute path (slashes as %2F).
          file: `/v1/audio?path=${encodeURIComponent(path)}`,
          prompt,
          lyrics: "",
          metas: {
            bpm: 138,
            duration: 181.4,
            genres: "techno",
            keyscale: "A Minor",
            timesignature: "4",
          },
          seed_value: 4242 + index,
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
            return json({
              available: true,
              blocked_by_live: false,
              stats: { avg_job_seconds: 40, queue_size: 0 },
            });
          }
          if (/\/api\/generator\/tasks$/.test(url) && method === "POST") {
            return json({
              task_id: "e2e-edit-src",
              queue_position: 0,
              eta_seconds: 4,
            });
          }
          // The edit's task id is polled by the SAME endpoint — that is the
          // contract: an edit is just another task.
          if (/\/api\/generator\/tasks\/e2e-edit-chained/.test(url)) {
            state.editPolls += 1;
            if (state.editPolls === 1) {
              // One pending poll first, so the chained card's own ETA and
              // spinner are exercised before the takes land.
              return json({ status: "pending", takes: [], eta_seconds: 6 });
            }
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [take(0, editedPath, "dark melodic techno, hypnotic, driving")],
            });
          }
          if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [take(0, sourcePath, "dark melodic techno, hypnotic, driving")],
            });
          }
          if (/\/api\/generator\/edit$/.test(url) && method === "POST") {
            state.editBodies.push(typeof init?.body === "string" ? init.body : "");
            return json({
              task_id: "e2e-edit-chained",
              queue_position: 1,
              eta_seconds: 8,
            });
          }
          if (/\/api\/generator\/publish$/.test(url) && method === "POST") {
            const parsed = JSON.parse(
              typeof init?.body === "string" ? init.body : "{}",
            );
            return json({
              track_id: parsed.variant_of
                ? "techno--neon-rain-v2"
                : "techno--neon-rain",
              file: "tracks/techno/Neon Rain.wav",
              display_name: "Neon Rain",
              camelot_key: "8A",
              bpm: parsed.metas?.bpm ?? 0,
              variant_of: parsed.variant_of ?? null,
              note: "Run `python main.py --fix-incomplete` before this goes in a set.",
            });
          }
          if (/\/api\/generator\/audio/.test(url)) {
            return new Response(new ArrayBuffer(8), { status: 200 });
          }
          if (/\/api\/catalog/.test(url)) {
            return json({ tracks: [], genres: ["lofi - ambient", "techno"] });
          }
          return origFetch(input, init);
        };
      },
      [TAKE_0, EDITED_0],
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
    await expect(takes).toHaveCount(1, { timeout: 25_000 });
    const source = takes.first();

    // ── Publish the source first, so the lineage can use its real name ──
    await source.getByTestId("generator-publish").click();
    await source.getByTestId("generator-publish-name").fill("Neon Rain");
    await source.getByTestId("generator-publish-submit").click();
    await expect(source.getByTestId("generator-published")).toBeVisible({
      timeout: 10_000,
    });

    // ── Edit: repaint seconds 10–20 ─────────────────────────────────────
    const editBtn = source.getByTestId("generator-edit");
    await expect(editBtn).toBeEnabled();
    await editBtn.click();

    const panel = source.getByTestId("generator-edit-panel");
    await expect(panel).toBeVisible();
    // Repaint is the default, and the default range is the whole take.
    await expect(source.getByTestId("generator-edit-mode")).toHaveValue("repaint");
    await expect(source.getByTestId("generator-edit-start")).toHaveValue("0");
    await expect(source.getByTestId("generator-edit-end")).toHaveValue("-1");

    await source.getByTestId("generator-edit-start").fill("10");
    await source.getByTestId("generator-edit-end").fill("20");
    // A backwards range is caught before it is ever sent.
    await source.getByTestId("generator-edit-end").fill("5");
    await expect(source.getByTestId("generator-edit-range-error")).toBeVisible();
    await expect(source.getByTestId("generator-edit-submit")).toBeDisabled();
    await source.getByTestId("generator-edit-end").fill("20");
    await expect(source.getByTestId("generator-edit-range-error")).toHaveCount(0);

    await source.getByTestId("generator-edit-submit").click();

    // ── The chained card lands under its source, and says so ────────────
    const chained = page.getByTestId("generator-chained-card");
    await expect(chained).toBeVisible({ timeout: 10_000 });
    // The source is published, so the lineage uses its catalog name.
    await expect(chained.getByTestId("generator-chained-lineage")).toHaveText(
      "edited from Neon Rain · repaint",
    );
    // The panel closed — the card is the whole story now.
    await expect(source.getByTestId("generator-edit-panel")).toHaveCount(0);

    // ── …and polls to its own take, which is an ordinary take ───────────
    const edited = chained.getByTestId("generator-take");
    await expect(edited).toHaveCount(1, { timeout: 25_000 });
    await expect(edited).toContainText("Neon Rain · repaint 1");
    await expect(edited.getByTestId("generator-take-play")).toBeVisible();
    // Nested inside its source: the tree IS the lineage.
    await expect(page.getByTestId("generator-take")).toHaveCount(2);

    // ── What actually went on the wire ──────────────────────────────────
    const bodies = await page.evaluate(
      () =>
        (window as unknown as { __aceEdit?: { editBodies: string[] } }).__aceEdit
          ?.editBodies ?? [],
    );
    expect(bodies.length).toBe(1);
    const sent = JSON.parse(bodies[0]);
    // The DECODED path, as the page persisted it — never the encoded field,
    // and never a task id.
    expect(sent.file).toBe(TAKE_0);
    expect(sent).not.toHaveProperty("task_id");
    expect(sent.mode).toBe("repaint");
    expect(sent.repainting_start).toBe(10);
    expect(sent.repainting_end).toBe(20);
    expect(sent.genre_folder).toBe("techno");
    // Empty override ⇒ the take's own prompt, which only the page holds.
    expect(sent.prompt).toBe("dark melodic techno, hypnotic, driving");
    // A repaint carries no cover strength — the server 422s a stray one.
    expect(sent).not.toHaveProperty("audio_cover_strength");

    // ── The edited take publishes as a variant OF its source ────────────
    await edited.getByTestId("generator-publish").click();
    const variant = edited.getByTestId("generator-publish-variant");
    await expect(variant).toBeVisible();
    await expect(variant).toHaveValue("Neon Rain");
    // …and can be edited again: the chain has no floor.
    await expect(edited.getByTestId("generator-edit")).toBeEnabled();
  });

  test("a refused edit reads verbatim and keeps the panel open", async ({
    page,
    request,
  }) => {
    await page.addInitScript(
      (sourcePath) => {
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
            return json({ task_id: "e2e-edit-409", queue_position: 0, eta_seconds: 3 });
          }
          if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [
                {
                  index: 0,
                  file: `/v1/audio?path=${encodeURIComponent(sourcePath)}`,
                  prompt: "warm lofi keys",
                  lyrics: "",
                  metas: { bpm: 82, duration: 190, keyscale: "C Major" },
                  seed_value: 7,
                },
              ],
            });
          }
          if (/\/api\/generator\/edit$/.test(url) && method === "POST") {
            // The VRAM protocol, in the server's own words.
            return json(
              {
                detail:
                  "VRAM protocol: a set is on air. ACE-Step holds ~12.5 GB of " +
                  "the shared 16 GB GPU, so generating now would starve the " +
                  "live DJ's model. Try again when the session ends.",
              },
              409,
            );
          }
          if (/\/api\/generator\/audio/.test(url)) {
            return new Response(new ArrayBuffer(8), { status: 200 });
          }
          if (/\/api\/catalog/.test(url)) {
            return json({ tracks: [], genres: ["lofi - ambient", "techno"] });
          }
          return origFetch(input, init);
        };
      },
      TAKE_0,
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
    await page.getByTestId("generator-open").click();
    await page.getByTestId("generator-prompt").fill("warm lofi keys");
    await page.getByTestId("generator-submit").click();

    const take = page.getByTestId("generator-take").first();
    await expect(take).toBeVisible({ timeout: 25_000 });

    await take.getByTestId("generator-edit").click();
    await take.getByTestId("generator-edit-mode").selectOption("cover");
    // Cover swaps the range for a strength — the modes do not share fields.
    await expect(take.getByTestId("generator-edit-strength")).toBeVisible();
    await expect(take.getByTestId("generator-edit-start")).toHaveCount(0);

    await take.getByTestId("generator-edit-submit").click();

    // Verbatim: a protocol refusal is never paraphrased.
    await expect(take.getByTestId("generator-edit-error")).toContainText(
      "VRAM protocol: a set is on air.",
    );
    // The panel stays up, and nothing was chained.
    await expect(take.getByTestId("generator-edit-panel")).toBeVisible();
    await expect(page.getByTestId("generator-chained-card")).toHaveCount(0);
  });
});
