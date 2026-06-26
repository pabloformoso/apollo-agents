/**
 * v3.6 bug 3 regression — crossfade `when` must align to the outgoing
 * downbeat, not an arbitrary clock instant.
 *
 * Found live 2026-06-26: transition Deep Dive→Twilight Echo sounded
 * "desfasado desde el primer golpe" DESPITE grid_warp active and a clean
 * incoming grid, because the frontend pinned the incoming downbeat to
 * `ctx.currentTime + lookahead` and never used the backend's
 * `outgoing_anchor_sec`. See memory project_v36_beatmatch_endbar_bug.
 *
 * RED-FIRST: the desired-behaviour tests are xfail(strict) until the v3.6
 * fix lands in computeCrossfadeWhen / live.ts.
 */
import { describe, it, expect } from "vitest";

import { computeCrossfadeWhen } from "../lib/crossfade_timing";

describe("computeCrossfadeWhen — fallback (no phase-lock)", () => {
  it("returns ctxNow + lookahead when no outgoing anchor is given", () => {
    const when = computeCrossfadeWhen({
      ctxNow: 10.0,
      lookaheadSec: 0.1,
      outgoingPosSec: 123.4,
      outgoingAnchorSec: undefined,
    });
    expect(when).toBeCloseTo(10.1, 6);
  });
});

describe("computeCrossfadeWhen — v3.6 downbeat alignment", () => {
  it(
    "waits until the outgoing deck reaches its anchor downbeat",
    () => {
      // Outgoing deck is at 293.04s; backend wants the crossfade to begin
      // at the 293.54s downbeat — i.e. 0.5s of audio from now. The blend
      // must land ~0.5s in the future (plus lookahead slack), NOT at
      // ctxNow + lookahead (which would be only 0.1s).
      const when = computeCrossfadeWhen({
        ctxNow: 50.0,
        lookaheadSec: 0.1,
        outgoingPosSec: 293.04,
        outgoingAnchorSec: 293.54,
      });
      // Desired: when ≈ ctxNow + (anchor - pos) = 50.0 + 0.5 = 50.5
      expect(when).toBeCloseTo(50.5, 3);
    },
  );

  it(
    "never schedules in the past — clamps to at least ctxNow + lookahead",
    () => {
      // Outgoing deck already PAST its anchor (anchor - pos = -0.3s). We
      // must not return a `when` before ctxNow + lookahead. This invariant
      // must hold in BOTH the buggy and fixed versions (it's a safety
      // floor, not the alignment behaviour), so it's a normal passing test
      // — it guards the fix from ever scheduling in the past.
      const when = computeCrossfadeWhen({
        ctxNow: 50.0,
        lookaheadSec: 0.1,
        outgoingPosSec: 293.84,
        outgoingAnchorSec: 293.54,
      });
      expect(when).toBeGreaterThanOrEqual(50.1 - 1e-9);
    },
  );

  it(
    "incoming downbeat coincides with outgoing downbeat by construction",
    () => {
      // The whole point: the incoming source starts at `when` (its own
      // downbeat via the offset arg), so `when` must equal the wall-clock
      // moment the outgoing deck is AT its downbeat. Distance from now to
      // that moment is (anchor - pos).
      const ctxNow = 12.345;
      const lookaheadSec = 0.1;
      const outgoingPosSec = 100.0;
      const outgoingAnchorSec = 101.875; // 1.875s = one bar @ 128 BPM
      const when = computeCrossfadeWhen({
        ctxNow,
        lookaheadSec,
        outgoingPosSec,
        outgoingAnchorSec,
      });
      const secondsUntilOutgoingDownbeat = outgoingAnchorSec - outgoingPosSec;
      expect(when - ctxNow).toBeCloseTo(secondsUntilOutgoingDownbeat, 3);
    },
  );
});
