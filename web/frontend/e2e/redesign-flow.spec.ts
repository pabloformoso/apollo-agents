import { test, expect } from "@playwright/test";
import {
  installToken,
  registerViaApi,
  signedInOnDashboard,
} from "./fixtures/auth";

/**
 * Apollo v2.6.0 — Ember redesign flow regression suite.
 *
 * Covers the user-reported bug where logging in, submitting a brief, and
 * landing on Curate sometimes bounced back to /login. The tests below
 * exercise the full Brief → Curate → Editor → Render → Live nav so any
 * auth/hydration/redirect regression surfaces immediately.
 */

test.describe("v2.6.0 redesign flow", () => {
  test("Login form renders with ember design", async ({ page }) => {
    await page.goto("/login");
    // Italic display headline + ember accent dot.
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    await expect(page.locator("input[type=text]").first()).toBeVisible();
    await expect(page.locator("input[type=password]")).toBeVisible();
    // Stripe poster on the right pane (hidden on mobile, visible on md+).
    await expect(
      page.getByText(/assemble.*critique.*perform/i),
    ).toBeVisible();
  });

  test("Dashboard renders the ember Library hero", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);
    await expect(
      page.getByRole("heading", { name: /what will you make tonight/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /start a session/i }),
    ).toBeVisible();
  });

  test("Brief → Curate flow keeps the user signed in", async ({
    page,
    request,
  }) => {
    // Reproduces the user-reported bug: login → brief → first prompt →
    // bounced to /login. The test asserts every navigation step lands
    // on the expected route and that the user never sees /login again
    // until they explicitly sign out.
    await signedInOnDashboard(page, request);

    // Click "Start a session" — should land on /brief with a session id.
    await page.getByRole("button", { name: /start a session/i }).click();
    await expect(page).toHaveURL(/\/brief(\?session=[^&]+)?$/);

    // Hero copy + textarea + suggestions present.
    await expect(
      page.getByRole("heading", { name: /one sentence/i }),
    ).toBeVisible();
    const textarea = page.getByPlaceholder(/lofi ambient set/i);
    await expect(textarea).toBeVisible();

    // Type the prompt and submit.
    await textarea.fill(
      "30 minutes of lofi for a rainy garden afternoon",
    );
    await page.getByRole("button", { name: /curate this set/i }).click();

    // The user should land on /curate with their session — NOT bounce to
    // /login. This is the core regression.
    await page.waitForURL(/\/curate\?session=[^&]+/, { timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/login/);

    // Curate's empty state is fine here — a fresh session has no playlist
    // yet because the v2.5.x phase machine drives planning out-of-band.
    // What matters is the user is on /curate, signed in, with the new UI.
    await expect(page.locator("text=/curate/i").first()).toBeVisible();
  });

  test("Direct nav to /curate auto-resolves session via library", async ({
    page,
    request,
  }) => {
    // The redesign nav links don't carry a `?session=` param; the
    // `useAutoSession` hook should pick the most recent eligible session
    // and update the URL in place. With a brand-new user (no sessions),
    // /curate redirects to /brief.
    const user = await registerViaApi(request);
    await installToken(page, user);
    await page.goto("/curate");
    await page.waitForURL(/\/(brief|curate)(\?|$)/, { timeout: 5_000 });
    // Either way: NEVER bounce to /login.
    await expect(page).not.toHaveURL(/\/login/);
  });

  test("Top nav reaches Editor / Render / Live without bouncing", async ({
    page,
    request,
  }) => {
    await signedInOnDashboard(page, request);
    for (const route of ["/editor", "/render", "/live"]) {
      await page.goto(route);
      // Auto-session may redirect to /brief if there's no eligible
      // session; that's fine, just not /login.
      await page.waitForLoadState("networkidle");
      await expect(page).not.toHaveURL(/\/login/);
    }
  });

  test("Legacy /session/[id] does NOT bounce signed-in user to /login", async ({
    page,
    request,
  }) => {
    // Reproduces the user-reported bug: after the v2.6.0 ember rewrite of
    // the legacy session detail page, the auth-gating effect didn't wait
    // for the `useAuth` hydration tick, so it observed `user = null` on
    // the first render and called `router.push('/login')` before the
    // hook had a chance to read localStorage. This test asserts the page
    // stays on the session route.
    const user = await signedInOnDashboard(page, request);

    // Create a session via the API so we have a real id to visit.
    const apiBase =
      process.env.APOLLO_E2E_API ?? "http://localhost:8801";
    const res = await request.post(`${apiBase}/api/sessions`, {
      headers: { Authorization: `Bearer ${user.token}` },
    });
    expect(res.ok()).toBeTruthy();
    const session = await res.json();

    await page.goto(`/session/${session.id}`);
    await page.waitForLoadState("networkidle");
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page).toHaveURL(new RegExp(`/session/${session.id}`));
  });
});
