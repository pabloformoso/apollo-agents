import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * G4 — scoring a take from its own row.
 *
 * Sibling of `generator-wizard.spec.ts` (G1, up to the takes),
 * `generator-publish.spec.ts` (G2b) and `generator-edit.spec.ts` (G3).
 * This one walks take → Score → chips + paragraph, because the claims worth
 * pinning only exist once the panel is on screen:
 *
 *   - each reference-informed metric renders as a chip carrying its value
 *     AND the band it was judged against, toned in/out of that band, while
 *     the loudness tier renders as advisory — measured, never failed;
 *   - the LLM's paragraph renders under them when there is one;
 *   - a genre with no committed references renders its NOTE instead of a
 *     verdict — a normal answer, not an error, and still no blocked publish;
 *   - Publish stays enabled throughout: scoring informs, it never gates.
 *
 * `/api/generator/*` is stubbed with the house `addInitScript` fetch
 * wrapper, so the spec passes whether or not the ACE box is on and no LLM
 * is ever contacted.
 */

const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";
const TAKE_0 = `${ACE_ROOT}/e2e-score-a_0.wav`;
const TAKE_1 = `${ACE_ROOT}/e2e-score-b_1.wav`;

const CRITIQUE =
  "The centroid and tilt both sit inside the deep references, so this reads " +
  "as the warm groove that was asked for; if anything, open the top end a " +
  "little on the next attempt.";

const NO_REFERENCES_NOTE =
  "no references for genre 'techno' in quality_references.json " +
  "(has: ambient, deep, lofi)";

test.describe("G4 — score a take", () => {
  test("take → score → chips, band readings and the critique paragraph", async ({
    page,
    request,
  }) => {
    await page.addInitScript(
      ([pathA, pathB, critique, note]) => {
        const origFetch = window.fetch;
        const state = { critiqueBodies: [] as string[] };
        (window as unknown as { __aceScore?: typeof state }).__aceScore = state;

        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          });

        const take = (index: number, path: string) => ({
          index,
          // ACE's real `file` shape: the endpoint plus the totally
          // percent-encoded absolute path (slashes as %2F).
          file: `/v1/audio?path=${encodeURIComponent(path)}`,
          prompt: "warm deep house, dusty rhodes, patient groove",
          lyrics: "",
          metas: {
            bpm: 122,
            duration: 181.4,
            genres: "deep house",
            keyscale: "A Minor",
            timesignature: "4",
          },
          seed_value: 4242 + index,
        });

        // The first take scores against real bands; the second stands in
        // for a genre nobody has extracted references for yet.
        const scored = {
          passed: true,
          reference_genre: "deep",
          reference_informed: { centroid_hz: 4400.4, tilt_db_per_oct: -3.42 },
          advisory: { lufs: -17.2, lra: 4.05, crest_db: 11.94 },
          bands: {
            centroid_hz: {
              min: 1734.8,
              max: 11934.5,
              reference_min: 4336.9,
              reference_max: 4773.8,
            },
            tilt_db_per_oct: {
              min: -11.89,
              max: 4.97,
              reference_min: -3.89,
              reference_max: -3.03,
            },
            advisory_lufs: {
              min: -18.0,
              max: -16.9,
              reference_min: -18.0,
              reference_max: -16.9,
            },
          },
          failures: [],
          critique,
          note: null,
        };
        const unscored = {
          passed: null,
          reference_genre: "techno",
          reference_informed: null,
          advisory: null,
          bands: null,
          failures: [],
          critique: null,
          note,
        };

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
              task_id: "e2e-score",
              queue_position: 0,
              eta_seconds: 4,
            });
          }
          if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [take(0, pathA), take(1, pathB)],
            });
          }
          if (/\/api\/generator\/critique$/.test(url) && method === "POST") {
            const raw = typeof init?.body === "string" ? init.body : "{}";
            state.critiqueBodies.push(raw);
            // Which take was sent decides which answer comes back, so one
            // walk covers both a verdict and a verdict-less genre.
            return json(JSON.parse(raw).file === pathA ? scored : unscored);
          }
          if (/\/api\/generator\/audio/.test(url)) {
            return new Response(new ArrayBuffer(8), { status: 200 });
          }
          if (/\/api\/catalog/.test(url)) {
            return json({ tracks: [], genres: ["lofi - ambient", "deep house"] });
          }
          return origFetch(input, init);
        };
      },
      [TAKE_0, TAKE_1, CRITIQUE, NO_REFERENCES_NOTE],
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
    await page.getByTestId("generator-prompt").fill("warm deep house, dusty rhodes");
    await page.getByTestId("generator-genre").selectOption("deep house");
    await page.getByTestId("generator-submit").click();

    const takes = page.getByTestId("generator-take");
    await expect(takes).toHaveCount(2, { timeout: 25_000 });
    const first = takes.first();
    const second = takes.nth(1);

    // ── Nothing is measured until it is asked for ───────────────────────
    await expect(first.getByTestId("generator-score-panel")).toHaveCount(0);
    await expect(first.getByTestId("generator-score")).toBeEnabled();

    await first.getByTestId("generator-score").click();

    const panel = first.getByTestId("generator-score-panel");
    await expect(panel).toBeVisible({ timeout: 10_000 });
    // The label carries the contract: this informs a decision, it is not
    // standing in front of one.
    await expect(panel).toContainText(/informs, never blocks/i);
    await expect(panel.getByTestId("generator-score-verdict")).toHaveText(
      "Sits inside the deep references.",
    );

    // ── The chips: value + band, toned by where the value sits ──────────
    const chips = panel.getByTestId("generator-score-chip");
    await expect(chips).toHaveCount(5);
    await expect(chips.nth(0)).toContainText("centroid 4400 Hz");
    await expect(chips.nth(0)).toContainText("band 1735–11935");
    await expect(chips.nth(0)).toHaveAttribute("data-tone", "in");
    await expect(chips.nth(1)).toContainText("tilt -3.4 dB/oct");
    await expect(chips.nth(1)).toHaveAttribute("data-tone", "in");
    // Loudness, range and crest are measured and reported, never failed.
    await expect(chips.nth(2)).toContainText("loudness -17.2 LUFS");
    for (const i of [2, 3, 4]) {
      await expect(chips.nth(i)).toHaveAttribute("data-tone", "advisory");
    }

    // ── …and the read of them ───────────────────────────────────────────
    await expect(panel.getByTestId("generator-score-critique")).toHaveText(
      CRITIQUE,
    );

    // Scoring gates nothing: the take is still publishable, and editable.
    await expect(first.getByTestId("generator-publish")).toBeEnabled();
    await expect(first.getByTestId("generator-edit")).toBeEnabled();
    // The button admits the score can be taken again after an edit.
    await expect(first.getByTestId("generator-score")).toHaveText(/score again/i);

    // ── What actually went on the wire ──────────────────────────────────
    const bodies = await page.evaluate(
      () =>
        (window as unknown as { __aceScore?: { critiqueBodies: string[] } })
          .__aceScore?.critiqueBodies ?? [],
    );
    expect(bodies.length).toBe(1);
    const sent = JSON.parse(bodies[0]);
    // The DECODED path the page persisted — never the encoded field, and
    // never a task id (ACE's job records expire, its result files do not).
    expect(sent.file).toBe(TAKE_0);
    expect(sent).not.toHaveProperty("task_id");
    expect(sent.genre_folder).toBe("deep house");
    expect(sent.metas).toEqual({ bpm: 122, keyscale: "A Minor", duration: 181.4 });
    // The prompt travels because only the page still holds it.
    expect(sent.prompt).toBe("warm deep house, dusty rhodes, patient groove");

    // ── A genre with no references reads as a note, not an error ────────
    await second.getByTestId("generator-score").click();
    const secondPanel = second.getByTestId("generator-score-panel");
    await expect(secondPanel).toBeVisible({ timeout: 10_000 });
    await expect(secondPanel.getByTestId("generator-score-verdict")).toHaveText(
      "No reference bands for this genre yet.",
    );
    await expect(secondPanel.getByTestId("generator-score-note")).toContainText(
      "no references for genre 'techno'",
    );
    // Nothing was measured, so nothing is drawn — and nothing is blocked.
    await expect(secondPanel.getByTestId("generator-score-chip")).toHaveCount(0);
    await expect(secondPanel.getByTestId("generator-score-critique")).toHaveCount(0);
    await expect(second.getByTestId("generator-publish")).toBeEnabled();
  });

  test("an edited take scores from inside its chained card", async ({
    page,
    request,
  }) => {
    // The claim: Score lives in the take ROW, so it comes with every take
    // an edit produces — a chained take is an ordinary take.
    await page.addInitScript(
      ([sourcePath, editedPath]) => {
        const origFetch = window.fetch;
        const state = { editPolls: 0, scored: [] as string[] };
        (window as unknown as { __aceChainScore?: typeof state }).__aceChainScore =
          state;

        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          });

        const take = (index: number, path: string) => ({
          index,
          file: `/v1/audio?path=${encodeURIComponent(path)}`,
          prompt: "warm deep house, dusty rhodes, patient groove",
          lyrics: "",
          metas: {
            bpm: 122,
            duration: 181.4,
            genres: "deep house",
            keyscale: "A Minor",
            timesignature: "4",
          },
          seed_value: 99 + index,
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
            return json({ task_id: "e2e-chain-src", queue_position: 0, eta_seconds: 3 });
          }
          if (/\/api\/generator\/tasks\/e2e-chain-edit/.test(url)) {
            state.editPolls += 1;
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [take(0, editedPath)],
            });
          }
          if (/\/api\/generator\/tasks\/[^/?]+/.test(url)) {
            return json({
              status: "done",
              eta_seconds: 0,
              takes: [take(0, sourcePath)],
            });
          }
          if (/\/api\/generator\/edit$/.test(url) && method === "POST") {
            return json({ task_id: "e2e-chain-edit", queue_position: 1, eta_seconds: 5 });
          }
          if (/\/api\/generator\/critique$/.test(url) && method === "POST") {
            const raw = typeof init?.body === "string" ? init.body : "{}";
            state.scored.push(JSON.parse(raw).file);
            return json({
              passed: false,
              reference_genre: "deep",
              reference_informed: { centroid_hz: 14200.9, tilt_db_per_oct: -3.42 },
              advisory: { lufs: -17.2, lra: 4.05, crest_db: 11.94 },
              bands: {
                centroid_hz: {
                  min: 1734.8,
                  max: 11934.5,
                  reference_min: 4336.9,
                  reference_max: 4773.8,
                },
                tilt_db_per_oct: {
                  min: -11.89,
                  max: 4.97,
                  reference_min: -3.89,
                  reference_max: -3.03,
                },
                advisory_lufs: {
                  min: -18.0,
                  max: -16.9,
                  reference_min: -18.0,
                  reference_max: -16.9,
                },
              },
              failures: ["centroid 14201Hz outside [1735, 11935]"],
              critique: null,
              note: null,
            });
          }
          if (/\/api\/generator\/audio/.test(url)) {
            return new Response(new ArrayBuffer(8), { status: 200 });
          }
          if (/\/api\/catalog/.test(url)) {
            return json({ tracks: [], genres: ["lofi - ambient", "deep house"] });
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
    await page.getByTestId("generator-open").click();
    await page.getByTestId("generator-prompt").fill("warm deep house");
    await page.getByTestId("generator-genre").selectOption("deep house");
    await page.getByTestId("generator-submit").click();

    const source = page.getByTestId("generator-take").first();
    await expect(source).toBeVisible({ timeout: 25_000 });
    await source.getByTestId("generator-edit").click();
    await source.getByTestId("generator-edit-submit").click();

    // Locators go through the chained card, never the outer take: once a
    // card nests, `source.getByTestId(...)` matches twice and strict mode
    // bites (the G3 spec's lesson).
    const chained = page.getByTestId("generator-chained-card");
    await expect(chained).toBeVisible({ timeout: 10_000 });
    const edited = chained.getByTestId("generator-take");
    await expect(edited).toHaveCount(1, { timeout: 25_000 });

    await edited.getByTestId("generator-score").click();
    const panel = edited.getByTestId("generator-score-panel");
    await expect(panel).toBeVisible({ timeout: 10_000 });
    await expect(panel.getByTestId("generator-score-verdict")).toContainText(
      "Outside the deep references",
    );
    await expect(panel.getByTestId("generator-score-chip").first()).toHaveAttribute(
      "data-tone",
      "out",
    );
    // No LLM answered, so there is simply no paragraph — not an error.
    await expect(panel.getByTestId("generator-score-critique")).toHaveCount(0);
    await expect(panel.getByTestId("generator-score-error")).toHaveCount(0);

    // The EDITED take's path went out, not its source's.
    const scored = await page.evaluate(
      () =>
        (window as unknown as { __aceChainScore?: { scored: string[] } })
          .__aceChainScore?.scored ?? [],
    );
    expect(scored).toEqual([TAKE_1]);
  });
});
