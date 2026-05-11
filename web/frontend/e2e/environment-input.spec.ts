import { test, expect } from "@playwright/test";
import { gotoNewSession, signedInOnDashboard } from "./fixtures/auth";
import { expectPhase } from "./fixtures/phase";

/**
 * v2.5.0 — environment-perception input.
 *
 * The session intake screen has two fields:
 *   1. the existing genre/duration/mood single-line input;
 *   2. a small textarea for the listening environment (e.g. "loud crowded
 *      bar").
 *
 * The textarea is decorative: its value is concatenated as
 * "(environment: <text>)" onto the main message before being sent over
 * the WebSocket as `genre_intent`. The mock pipeline's `fake_genre`
 * echoes whatever text appears between the parens back into ctx, so the
 * value is visible in the agent log via the page's phase_complete handler.
 *
 * Spec verifies:
 *   - The login → /session/{id} → fill both fields → submit → phase
 *     advances to ckpt1 (so the genre flow is unblocked by the new field).
 *   - The agent log surfaces the environment text on the genre
 *     phase_complete event (proving the value made the full round trip).
 *   - An empty environment textarea remains backwards-compatible (no
 *     "(environment:" suffix is appended; agent log gets no env line).
 */

test.describe("v2.5.0 — environment-perception input", () => {
  test("accepts environment text and surfaces it in the agent log", async ({
    page,
    request,
  }) => {
    const e2eUser = await signedInOnDashboard(page, request);

    await gotoNewSession(page, request, e2eUser);

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await expect(genreInput).toBeEnabled();
    await genreInput.fill("60-minute cyberpunk set, dark and intense");

    // The new textarea — decorative; mock_pipeline's fake_genre echoes
    // whatever it captures between the (environment:) parens.
    const envInput = page.getByLabel(/listening environment/i);
    await expect(envInput).toBeEnabled();
    await envInput.fill("loud crowded bar");

    await page.getByRole("button", { name: /^send$/i }).click();

    // The pipeline auto-runs the planner once the genre is confirmed, so
    // we land at ckpt1. If the genre flow regresses on the new field
    // shape this assertion will time out before the env-log check.
    await expectPhase(page, "ckpt1");

    // The page appends an "environment: ..." log line on the genre
    // phase_complete event when ctx.environment is non-empty.
    await expect(
      page.locator("text=/environment: loud crowded bar/i").first(),
    ).toBeVisible();
  });

  test("blank environment textarea behaves like a 3-field session", async ({
    page,
    request,
  }) => {
    const e2eUser = await signedInOnDashboard(page, request);

    await gotoNewSession(page, request, e2eUser);

    const genreInput = page.getByPlaceholder(/60-minute cyberpunk set/i);
    await genreInput.fill("60-minute techno set, dark");
    // Intentionally leave the environment textarea empty.
    await page.getByRole("button", { name: /^send$/i }).click();

    await expectPhase(page, "ckpt1");
    // No "environment:" line should appear in the log when the user did
    // not provide one — keeps the legacy 3-field UX clean.
    await expect(page.locator("text=/^environment:/i")).toHaveCount(0);
  });
});
