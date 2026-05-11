import { Page, expect } from "@playwright/test";

/**
 * PhaseBar renders each phase as a span with text-neon + font-bold when active.
 * This helper waits for the given label to be the active (font-bold) node.
 * Labels mirror app/session/[id]/page.tsx's PHASES array (with "checkpoint" → "ckpt").
 */
export type PhaseLabel =
  | "genre"
  | "planning"
  | "ckpt1"
  | "critique"
  | "ckpt2"
  | "editing"
  | "validating"
  | "rating"
  | "complete";

export async function expectPhase(page: Page, label: PhaseLabel, timeout = 25_000): Promise<void> {
  // v2.6.0 — the ember PhaseBar tags the active span with
  // ``data-testid="phase-active"``. The legacy v2.5.x neon UI used
  // ``.font-bold`` instead; we keep that selector as a fallback so the
  // fixture works against either UI during the redesign rollout.
  const active = page
    .locator('[data-testid="phase-active"], .font-bold')
    .filter({ hasText: new RegExp(`^${label}$`, "i") });
  await expect(active).toBeVisible({ timeout });
}

/** Wait for the phase bar to advance *past* `label` (phase no longer active). */
export async function expectPhaseNotActive(page: Page, label: PhaseLabel): Promise<void> {
  const active = page
    .locator('[data-testid="phase-active"], .font-bold')
    .filter({ hasText: new RegExp(`^${label}$`, "i") });
  await expect(active).toHaveCount(0, { timeout: 15_000 });
}
