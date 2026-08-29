import { test, expect, type Page } from "@playwright/test";
import { signedInOnDashboard } from "./fixtures/auth";

/**
 * G6 — the generations library, the feed the wizard's own state never was.
 *
 * Walks the whole surface in one pass: reach `/generations` through the
 * house nav, read four cards whose statuses mean four different things,
 * play a take through the audio proxy, publish one (optimistic chip),
 * discard another (it folds behind the card's toggle, and the PATCH is
 * asserted on the wire), and resume the pending card.
 *
 * `/api/generator/*` is scripted with the same `addInitScript` fetch wrapper
 * the other generator specs use, so this passes whether or not the ACE box
 * is on. The ONE exception is the audio itself: `<audio>` does not go
 * through `window.fetch`, so the proxy is served a real (silent) WAV through
 * `page.route` — which is also what proves the take is fetched from the
 * proxy rather than from the box.
 */

const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";
const TAKE_0 = `${ACE_ROOT}/e2e-feed_0.wav`;
const TAKE_1 = `${ACE_ROOT}/e2e-feed_1.wav`;
const TAKE_2 = `${ACE_ROOT}/e2e-feed_2.wav`;
const RESUMED = `${ACE_ROOT}/e2e-resumed_0.wav`;

/** A real, tiny, silent WAV — enough for the element to load and play. */
function silentWav(seconds = 1, rate = 8000): Buffer {
  const dataSize = seconds * rate * 2;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + dataSize, 4);
  buf.write("WAVE", 8);
  buf.write("fmt ", 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(1, 22); // mono
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(dataSize, 40);
  return buf;
}

type Wire = { patches: string[]; refreshes: string[]; publishes: string[] };

async function scriptGenerator(page: Page): Promise<void> {
  await page.addInitScript(
    ([t0, t1, t2, resumed]) => {
      const origFetch = window.fetch;
      const state: Wire = { patches: [], refreshes: [], publishes: [] };
      (window as unknown as { __aceFeed?: Wire }).__aceFeed = state;

      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });

      const take = (
        index: number,
        path: string,
        over: Record<string, unknown> = {},
      ) => ({
        index,
        // ACE's real `file` shape: the endpoint plus the totally
        // percent-encoded absolute path (slashes as %2F).
        file: `/v1/audio?path=${encodeURIComponent(path)}`,
        prompt: "dark melodic techno, hypnotic, driving",
        lyrics: "",
        metas: {
          bpm: 138,
          duration: 181.4,
          genres: "techno",
          keyscale: "A Minor",
          timesignature: "4",
        },
        seed_value: 4242 + index,
        state: "fresh",
        published_track_id: null,
        ...over,
      });

      // The store, as this browser sees it. The PATCH and the refresh
      // mutate it, so a re-fetch reconciles to the same thing the page
      // already showed optimistically.
      const store = [
        {
          id: "gen-done",
          created_at: "2026-08-29T09:00:00Z",
          status: "done",
          request: {
            prompt: "dark melodic techno, hypnotic, driving",
            genre_folder: "techno",
            audio_duration: 180,
            bpm: 138,
            batch_size: 3,
          },
          takes: [
            take(0, t0),
            take(1, t1),
            take(2, t2, {
              state: "published",
              published_track_id: "techno--older-take",
            }),
          ],
        },
        {
          id: "gen-pending",
          created_at: "2026-08-29T08:00:00Z",
          status: "pending",
          request: {
            prompt: "slow healing pads, very long tails",
            genre_folder: "healing",
            batch_size: 1,
          },
          takes: [],
        },
        {
          id: "gen-failed",
          created_at: "2026-08-29T07:00:00Z",
          status: "failed",
          request: { prompt: "one that did not land", genre_folder: "techno" },
          takes: [],
          error: "CUDA out of memory",
        },
        {
          id: "gen-stale",
          created_at: "2026-08-29T06:00:00Z",
          status: "stale",
          request: { prompt: "one ACE has forgotten", genre_folder: "techno" },
          takes: [],
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
        const body = typeof init?.body === "string" ? init.body : "";

        if (/\/api\/generator\/health/.test(url)) {
          return json({ available: true, blocked_by_live: false, stats: {} });
        }

        const refresh = /\/api\/generator\/generations\/([^/?]+)\/refresh/.exec(url);
        if (refresh && method === "POST") {
          state.refreshes.push(refresh[1]);
          const gen = store.find((g) => g.id === refresh[1])!;
          gen.status = "done";
          gen.takes = [take(0, resumed)];
          return json(gen);
        }

        const patch = /\/api\/generator\/generations\/([^/?]+)\/takes\/(\d+)/.exec(url);
        if (patch && method === "PATCH") {
          state.patches.push(`${patch[1]}:${patch[2]}:${body}`);
          const gen = store.find((g) => g.id === patch[1]);
          const hit = gen?.takes.find((t) => t.index === Number(patch[2]));
          if (hit) hit.state = JSON.parse(body || "{}").state;
          return json({ ok: true });
        }

        if (/\/api\/generator\/generations(\?|$)/.test(url)) {
          const offset = Number(/[?&]offset=(\d+)/.exec(url)?.[1] ?? "0");
          const limit = Number(/[?&]limit=(\d+)/.exec(url)?.[1] ?? "10");
          // A BARE array, the way the router answers it (and the way
          // `/api/playlists` has always answered) — the client reads that
          // or the plan's envelope, so this pins the shape that ships.
          return json(
            JSON.parse(JSON.stringify(store.slice(offset, offset + limit))),
          );
        }

        if (/\/api\/generator\/publish$/.test(url) && method === "POST") {
          state.publishes.push(body);
          return json({
            track_id: "techno--neon-rain",
            file: "tracks/techno/Neon Rain.wav",
            display_name: "Neon Rain",
            camelot_key: "8A",
            bpm: 138,
            variant_of: null,
            note:
              "Ingested without madmom: duration, beatgrid, waveform peaks " +
              "and the MP3 sibling are still missing. Run `python main.py " +
              "--fix-incomplete` before this track goes into a set.",
          });
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
    [TAKE_0, TAKE_1, TAKE_2, RESUMED],
  );

  // `<audio>` never touches window.fetch — the proxy is served here.
  await page.route("**/api/generator/audio*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "audio/wav",
      body: silentWav(),
    }),
  );
}

test.describe("G6 — the generations library", () => {
  test("feed → play → publish → discard → resume", async ({ page, request }) => {
    await scriptGenerator(page);
    await signedInOnDashboard(page, request);

    // ── The nav affordance is the way in ──────────────────────────────────
    await page.getByRole("link", { name: "Generations" }).click();
    await expect(page).toHaveURL(/\/generations/);

    const cards = page.getByTestId("generation-card");
    await expect(cards).toHaveCount(4, { timeout: 15_000 });
    // Newest first, whatever order the page arrived in.
    await expect(cards.nth(0)).toHaveAttribute("data-generation-id", "gen-done");
    await expect(cards.nth(1)).toHaveAttribute(
      "data-generation-id",
      "gen-pending",
    );

    const done = page.locator('[data-generation-id="gen-done"]');
    await expect(done.getByTestId("generation-title")).toHaveText(
      "dark melodic techno, hypnotic, driving",
    );
    await expect(done.getByTestId("generation-status")).toHaveText("done");
    await expect(done.getByTestId("generation-chip")).toHaveText([
      "techno",
      "180s",
      "138 BPM",
      "3 takes",
    ]);

    // ── The failed and stale cards render honestly, and neither resumes ───
    const failed = page.locator('[data-generation-id="gen-failed"]');
    await expect(failed.getByTestId("generation-status")).toHaveText("failed");
    await expect(failed.getByTestId("generation-note")).toContainText(
      "CUDA out of memory",
    );
    await expect(failed.getByTestId("generation-resume")).toHaveCount(0);

    const stale = page.locator('[data-generation-id="gen-stale"]');
    await expect(stale.getByTestId("generation-status")).toHaveText("stale");
    await expect(stale.getByTestId("generation-note")).toContainText(
      "24-hour window",
    );
    await expect(stale.getByTestId("generation-resume")).toHaveCount(0);

    // ── A take published in an earlier session comes back marked ──────────
    const takes = done.getByTestId("generator-take");
    await expect(takes).toHaveCount(3);
    const stored = takes.nth(2);
    await expect(stored.getByTestId("generator-published")).toContainText(
      "techno--older-take",
    );
    await expect(stored.getByTestId("generator-publish")).toBeDisabled();

    // ── Play take 1 through the proxy ─────────────────────────────────────
    const first = takes.nth(0);
    const audio = page.waitForRequest(/\/api\/generator\/audio/);
    await first.getByTestId("generator-take-play").click();
    const audioUrl = new URL((await audio).url());
    // The browser never talks to the ACE box — auth and LAN isolation are
    // the backend's, and the JWT rides the query string because `<audio>`
    // cannot set a header. `path` is ACE's `file`, forwarded UNREWRITTEN.
    expect(audioUrl.host).not.toContain("8001");
    expect(audioUrl.pathname).toContain("/api/generator/audio");
    expect(audioUrl.searchParams.get("path")).toBe(
      `/v1/audio?path=${encodeURIComponent(TAKE_0)}`,
    );
    expect(audioUrl.searchParams.get("token")).toBeTruthy();
    await expect(first.getByTestId("generator-take-play")).toHaveAttribute(
      "aria-label",
      /Pause Take 1/,
    );

    // ── Publish take 1: the chip lands optimistically ─────────────────────
    await first.getByTestId("generator-publish").click();
    await first.getByTestId("generator-publish-name").fill("Neon Rain");
    await expect(first.getByTestId("generator-publish-genre")).toHaveValue(
      "techno",
    );
    await first.getByTestId("generator-publish-submit").click();

    const chip = first.getByTestId("generator-published");
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await expect(chip).toContainText("techno--neon-rain");
    await expect(chip).toContainText("--fix-incomplete");
    await expect(first.getByTestId("generator-publish")).toBeDisabled();
    // Publishing is a write to the CATALOG, not to the card: the take stays
    // exactly where it is, discardable and playable.
    await expect(takes).toHaveCount(3);

    // ── Discard take 2: it folds behind the card's toggle ─────────────────
    await expect(done.getByTestId("generation-discarded-toggle")).toHaveCount(0);
    await takes.nth(1).getByTestId("generation-discard").click();

    await expect(takes).toHaveCount(2);
    const toggle = done.getByTestId("generation-discarded-toggle");
    await expect(toggle).toContainText("1 discarded");
    // Collapsed until asked — nothing was deleted, it is just out of the way.
    await expect(done.getByTestId("generation-discarded")).toHaveCount(0);
    await toggle.click();
    const discarded = done.getByTestId("generation-discarded");
    await expect(discarded.getByTestId("generator-take")).toHaveCount(1);
    await expect(
      discarded.getByTestId("generation-restore"),
    ).toBeVisible();
    // The take published a moment ago is untouched by its sibling folding.
    await expect(chip).toContainText("techno--neon-rain");

    // ── What actually went on the wire ────────────────────────────────────
    const wire = await page.evaluate(
      () => (window as unknown as { __aceFeed?: Wire }).__aceFeed!,
    );
    expect(wire.patches).toEqual([
      'gen-done:1:{"state":"discarded"}',
    ]);
    const published = JSON.parse(wire.publishes[0]);
    // The DECODED path, as the store handed it over — never a task id.
    expect(published.file).toBe(TAKE_0);
    expect(published.display_name).toBe("Neon Rain");
    expect(published.genre_folder).toBe("techno");
    expect(published).not.toHaveProperty("task_id");

    // ── Resume the pending card ───────────────────────────────────────────
    const pending = page.locator('[data-generation-id="gen-pending"]');
    await expect(pending.getByTestId("generation-status")).toHaveText("pending");
    await expect(pending.getByTestId("generator-take")).toHaveCount(0);
    await pending.getByTestId("generation-resume").click();

    await expect(pending.getByTestId("generation-status")).toHaveText("done", {
      timeout: 10_000,
    });
    await expect(pending.getByTestId("generator-take")).toHaveCount(1);
    // Resumed, so there is nothing left to resume.
    await expect(pending.getByTestId("generation-resume")).toHaveCount(0);
    // The card reconciled in place rather than jumping to the top.
    await expect(cards.nth(1)).toHaveAttribute(
      "data-generation-id",
      "gen-pending",
    );

    const afterResume = await page.evaluate(
      () => (window as unknown as { __aceFeed?: Wire }).__aceFeed!,
    );
    expect(afterResume.refreshes).toEqual(["gen-pending"]);
  });
});
