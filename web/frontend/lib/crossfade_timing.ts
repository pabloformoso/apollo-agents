/**
 * Crossfade timing math — extracted from ``crossfadeToNext`` (live.ts) so the
 * "when does the blend land?" decision is pure and unit-testable.
 *
 * v3.6 bug 3 context: the live engine's backend computes a sample-accurate
 * ``outgoing_anchor_sec`` (the outgoing track's downbeat where the crossfade
 * should begin), but the frontend historically scheduled everything at
 * ``ctx.currentTime + SCHEDULE_LOOKAHEAD_SEC`` — an ARBITRARY clock instant.
 * That pins the incoming downbeat to a random point in the outgoing bar, so
 * the mix is off from the very first kick even when grid-warp is active
 * (grid-warp corrects tempo SLOPE, not phase INTERCEPT).
 *
 * The fix: land the crossfade when the outgoing deck actually REACHES its
 * anchor downbeat, so the incoming downbeat (started at ``when``) coincides
 * with the outgoing downbeat by construction.
 */

export interface CrossfadeWhenInput {
  /** AudioContext.currentTime right now (seconds, context clock). */
  ctxNow: number;
  /** Spec lookahead slack so the render thread can pick up the event. */
  lookaheadSec: number;
  /**
   * Current playback position of the OUTGOING deck, in catalog seconds
   * (``fromDeck.position()``).
   */
  outgoingPosSec: number;
  /**
   * Backend-computed outgoing downbeat (catalog seconds) where the crossfade
   * should begin. ``undefined`` when no phase-lock payload (legacy / loose
   * grid) — then we fall back to the plain lookahead instant.
   */
  outgoingAnchorSec?: number;
}

/**
 * Return the AudioContext time at which to land the crossfade.
 *
 * BUGGY status-quo implementation (mirrors live.ts today): ignores
 * ``outgoingAnchorSec`` entirely and just returns ``ctxNow + lookahead``.
 * The v3.6 fix replaces the body so ``when`` waits for the outgoing deck to
 * reach its anchor downbeat.
 */
export function computeCrossfadeWhen(input: CrossfadeWhenInput): number {
  const { ctxNow, lookaheadSec, outgoingPosSec, outgoingAnchorSec } = input;
  const floor = ctxNow + lookaheadSec;
  // No phase-lock payload (legacy / loose grid) → plain lookahead instant.
  if (typeof outgoingAnchorSec !== "number") {
    return floor;
  }
  // v3.6 bug 3 fix: land the blend when the OUTGOING deck actually reaches
  // its anchor downbeat. The incoming source starts at `when` on its own
  // downbeat (via the start() offset), so making `when` coincide with the
  // outgoing downbeat aligns the two by construction — no more "off from the
  // first kick". Distance from now to that downbeat is (anchor - pos).
  const secondsUntilDownbeat = outgoingAnchorSec - outgoingPosSec;
  const when = ctxNow + secondsUntilDownbeat;
  // Never schedule in the past: if the outgoing deck is already at/past its
  // anchor, fall back to the lookahead floor (the next-best landing).
  return Math.max(when, floor);
}
