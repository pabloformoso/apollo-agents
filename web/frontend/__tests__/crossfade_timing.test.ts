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

import {
  computeCrossfadeWhen,
  buildMeasurementProfile,
  applyPitchNudge,
} from "../lib/crossfade_timing";

describe("applyPitchNudge (W3 reinforcement input)", () => {
  it("earlier nudge is positive and speeds up (rate > 1)", () => {
    const r = applyPitchNudge("earlier", 0);
    expect(r.accumMs).toBe(5);
    expect(r.rate).toBeGreaterThan(1);
  });

  it("later nudge is negative and slows down (rate < 1)", () => {
    const r = applyPitchNudge("later", 0);
    expect(r.accumMs).toBe(-5);
    expect(r.rate).toBeLessThan(1);
  });

  it("accumulates across presses", () => {
    let acc = 0;
    acc = applyPitchNudge("earlier", acc).accumMs; // +5
    acc = applyPitchNudge("earlier", acc).accumMs; // +5
    acc = applyPitchNudge("later", acc).accumMs; //  -5
    expect(acc).toBe(5);
  });

  it("honors custom step and rate bump", () => {
    const r = applyPitchNudge("earlier", 10, 8, 0.05);
    expect(r.accumMs).toBe(18);
    expect(r.rate).toBeCloseTo(1.05, 6);
  });
});

describe("computeCrossfadeWhen — fallback (no phase-lock)", () => {
  it("returns ctxNow + lookahead when no outgoing anchor is given", () => {
    const r = computeCrossfadeWhen({
      ctxNow: 10.0,
      lookaheadSec: 0.1,
      outgoingPosSec: 123.4,
      outgoingAnchorSec: undefined,
    });
    expect(r.when).toBeCloseTo(10.1, 6);
    expect(r.secondsUntilDownbeat).toBeNull();
    expect(r.clamped).toBe(false);
    expect(r.residualMs).toBe(0);
  });
});

describe("computeCrossfadeWhen — residualMs (W2 measured signal)", () => {
  it("is 0 when the downbeat is hit (not clamped)", () => {
    const r = computeCrossfadeWhen({
      ctxNow: 50.0,
      lookaheadSec: 0.1,
      outgoingPosSec: 293.04,
      outgoingAnchorSec: 293.54, // 0.5s ahead → comfortably future, no clamp
    });
    expect(r.clamped).toBe(false);
    expect(r.residualMs).toBe(0);
  });

  it("equals the clamp gap in ms when the downbeat was missed", () => {
    // Deck 0.3s PAST its anchor → ideal is 0.3s in the past; clamp bumps to
    // ctxNow+lookahead. residual = when - ideal = 0.3s + lookahead = 0.4s.
    const r = computeCrossfadeWhen({
      ctxNow: 50.0,
      lookaheadSec: 0.1,
      outgoingPosSec: 293.84,
      outgoingAnchorSec: 293.54,
    });
    expect(r.clamped).toBe(true);
    expect(r.residualMs).toBeCloseTo(400, 0); // (0.3 + 0.1) * 1000
  });

  it("is never negative", () => {
    const r = computeCrossfadeWhen({
      ctxNow: 0,
      lookaheadSec: 0.05,
      outgoingPosSec: 0,
      outgoingAnchorSec: 100,
    });
    expect(r.residualMs).toBeGreaterThanOrEqual(0);
  });
});

describe("buildMeasurementProfile", () => {
  it("builds key_pair + 2-BPM bucket from outgoing/incoming tracks", () => {
    const p = buildMeasurementProfile(
      { bpm: 121.8, camelot_key: "8A" },
      { camelot_key: "8B" },
    );
    expect(p.keyPair).toBe("8A->8B");
    expect(p.bpmBucket).toBe("120-122");
    expect(p.profile).toBe("8A->8B|bpm120-122");
  });

  it("floors bpm to the lower even band edge", () => {
    expect(buildMeasurementProfile({ bpm: 123.0 }, {}).bpmBucket).toBe("122-124");
    expect(buildMeasurementProfile({ bpm: 120.0 }, {}).bpmBucket).toBe("120-122");
  });

  it("uses '?' for unknown key / bpm", () => {
    const p = buildMeasurementProfile({}, {});
    expect(p.keyPair).toBe("?->?");
    expect(p.bpmBucket).toBe("?");
    expect(p.profile).toBe("?->?|bpm?");
  });

  it("handles null fields", () => {
    const p = buildMeasurementProfile(
      { bpm: null, camelot_key: null },
      { camelot_key: null },
    );
    expect(p.profile).toBe("?->?|bpm?");
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
      const r = computeCrossfadeWhen({
        ctxNow: 50.0,
        lookaheadSec: 0.1,
        outgoingPosSec: 293.04,
        outgoingAnchorSec: 293.54,
      });
      // Desired: when ≈ ctxNow + (anchor - pos) = 50.0 + 0.5 = 50.5
      expect(r.when).toBeCloseTo(50.5, 3);
      expect(r.secondsUntilDownbeat).toBeCloseTo(0.5, 6);
      expect(r.clamped).toBe(false);
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
      const r = computeCrossfadeWhen({
        ctxNow: 50.0,
        lookaheadSec: 0.1,
        outgoingPosSec: 293.84,
        outgoingAnchorSec: 293.54,
      });
      expect(r.when).toBeGreaterThanOrEqual(50.1 - 1e-9);
      // And it reports the clamp fired — the diagnostic that distinguishes a
      // missed-downbeat constant offset from output latency.
      expect(r.clamped).toBe(true);
      expect(r.secondsUntilDownbeat).toBeCloseTo(-0.3, 6);
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
      const r = computeCrossfadeWhen({
        ctxNow,
        lookaheadSec,
        outgoingPosSec,
        outgoingAnchorSec,
      });
      const secondsUntilOutgoingDownbeat = outgoingAnchorSec - outgoingPosSec;
      expect(r.when - ctxNow).toBeCloseTo(secondsUntilOutgoingDownbeat, 3);
      expect(r.clamped).toBe(false);
    },
  );
});
