/**
 * Vitest unit tests for ``lib/visualizer/beat_clock.ts``.
 *
 * The function is pure so we cover the integer math + the documented
 * edge cases (bpm=0, time before first beat, infinity guards) without
 * any DOM/Three.js plumbing.
 */
import { describe, expect, it } from "vitest";

import {
  computeBeatClock,
  safeComputeBeatClock,
} from "@/lib/visualizer/beat_clock";

describe("computeBeatClock", () => {
  it("returns the correct beat index for an integer-multiple time", () => {
    // 120 BPM = 0.5 s per beat. first_beat=0.5, currentTime=2.0 →
    // elapsed=1.5, total_beats=3.0 → index=3, phase ~ 0.
    const r = computeBeatClock(120, 0.5, 2.0);
    expect(r.beat_index).toBe(3);
    expect(r.phase_in_beat).toBeCloseTo(0, 5);
  });

  it("advances the index as time crosses each beat boundary", () => {
    // currentTime=2.5 → elapsed=2.0, total_beats=4.0 → index=4.
    const r = computeBeatClock(120, 0.5, 2.5);
    expect(r.beat_index).toBe(4);
    expect(r.phase_in_beat).toBeCloseTo(0, 5);
  });

  it("returns a 0..1 phase mid-beat", () => {
    // currentTime=2.25 → elapsed=1.75, total_beats=3.5 → idx=3, phase=0.5
    const r = computeBeatClock(120, 0.5, 2.25);
    expect(r.beat_index).toBe(3);
    expect(r.phase_in_beat).toBeCloseTo(0.5, 5);
  });

  it("handles bpm=0 by returning all zeros", () => {
    const r = computeBeatClock(0, 0, 10);
    expect(r).toEqual({ beat_index: 0, phase_in_beat: 0, is_downbeat: false });
  });

  it("handles negative bpm gracefully", () => {
    const r = computeBeatClock(-120, 0, 10);
    expect(r).toEqual({ beat_index: 0, phase_in_beat: 0, is_downbeat: false });
  });

  it("returns zeros when currentTime < first_beat_sec", () => {
    const r = computeBeatClock(120, 5.0, 1.0);
    expect(r).toEqual({ beat_index: 0, phase_in_beat: 0, is_downbeat: false });
  });

  it("handles non-finite inputs without crashing", () => {
    expect(computeBeatClock(Infinity, 0, 1).beat_index).toBe(0);
    expect(computeBeatClock(120, NaN, 1).beat_index).toBe(0);
    expect(computeBeatClock(120, 0, NaN).beat_index).toBe(0);
  });

  it("flags every Nth beat as a downbeat (default 4 beats per bar)", () => {
    // first_beat=0, bpm=120 → seconds_per_beat=0.5.
    // beat_index=0 at currentTime=0, which is %4==0 → downbeat.
    expect(computeBeatClock(120, 0, 0).is_downbeat).toBe(true);
    // beat_index=4 at currentTime=2.0 → %4==0 → downbeat.
    expect(computeBeatClock(120, 0, 2.0).is_downbeat).toBe(true);
    // beat_index=2 at currentTime=1.0 → %4==2 → NOT a downbeat.
    expect(computeBeatClock(120, 0, 1.0).is_downbeat).toBe(false);
  });

  it("respects beats_per_bar parameter", () => {
    // With 3-beat bar (waltz time) the downbeat falls every 3 beats.
    expect(computeBeatClock(120, 0, 0, 3).is_downbeat).toBe(true);
    expect(computeBeatClock(120, 0, 1.5, 3).is_downbeat).toBe(true); // beat 3
    expect(computeBeatClock(120, 0, 1.0, 3).is_downbeat).toBe(false); // beat 2
  });

  it("does not flag a downbeat when phase_in_beat exceeds the tolerance", () => {
    // beat_index=4 at exactly currentTime=2.0 → downbeat.
    // currentTime=2.05 (10 % into the next beat) → still index 4 but
    // phase_in_beat=0.1 > 0.05 → NOT a downbeat.
    const r = computeBeatClock(120, 0, 2.05);
    expect(r.beat_index).toBe(4);
    expect(r.phase_in_beat).toBeCloseTo(0.1, 5);
    expect(r.is_downbeat).toBe(false);
  });
});

describe("safeComputeBeatClock", () => {
  it("returns zeros when beatgrid is null", () => {
    const r = safeComputeBeatClock(null, 5);
    expect(r).toEqual({ beat_index: 0, phase_in_beat: 0, is_downbeat: false });
  });

  it("returns zeros when beatgrid is undefined", () => {
    const r = safeComputeBeatClock(undefined, 5);
    expect(r).toEqual({ beat_index: 0, phase_in_beat: 0, is_downbeat: false });
  });

  it("delegates to computeBeatClock when beatgrid is present", () => {
    const r = safeComputeBeatClock({ bpm: 120, first_beat_sec: 0 }, 1.0);
    expect(r.beat_index).toBe(2);
  });
});
