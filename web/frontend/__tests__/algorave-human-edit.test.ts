/**
 * §9.1 — a human edit becomes state, never typed.
 *
 * Nobody live-coding narrates their own edits into a text box mid-phrase, so
 * the ring gets a mechanical summary instead. The implementation is the pen
 * module's (§11.3 seam 2); these pin the CONTRACT the app depends on, since a
 * change to the shared module that broke it would otherwise only be caught on
 * the spike's side.
 */
import { describe, expect, it } from "vitest";
import { pushReason, summarizeHumanEdit } from "@/lib/mind";

const sum = (a: string, b: string) => summarizeHumanEdit(a, b) as string | null;

describe("summarizeHumanEdit", () => {
  it("is null when nothing changed — no change is not an event", () => {
    expect(sum('s("bd*4")', 's("bd*4")')).toBeNull();
  });

  it("reports direction: a layer added reads +1", () => {
    const s = sum('stack(\n  s("bd*4")\n)', 'stack(\n  s("bd*4"),\n  s("hh*8")\n)');
    expect(s).toContain("+1 line");
  });

  it("quotes the COMMA line when a stack layer is added — a real limitation", () => {
    // Adding a layer also changes the line above it (a trailing comma appears),
    // and the summary quotes the FIRST changed line. So it says "+1 line" and
    // shows the comma edit rather than the new layer. The direction is still
    // right and that is what the ring is for, but it is worth knowing before
    // reading a summary as if it named the new sound.
    const s = sum('stack(\n  s("bd*4")\n)', 'stack(\n  s("bd*4"),\n  s("hh*8")\n)');
    expect(s).toContain('s("bd*4"),');
  });

  it("reports an in-place edit as ±0 and quotes what it says NOW", () => {
    // The common case — one gain nudged. The delta is uninformative, so the
    // quoted line has to carry what actually happened.
    const s = sum('s("bd*4").gain(0.9)', 's("bd*4").gain(0.4)');
    expect(s).toContain("±0");
    expect(s).toContain("0.4");
    expect(s).not.toContain("0.9");
  });

  it("reports a removed layer as -1", () => {
    const s = sum('stack(\n  s("bd*4"),\n  s("hh*8")\n)', 'stack(\n  s("bd*4")\n)');
    expect(s).toContain("-1 line");
  });

  it("quotes what went away when the deletion touches nothing else", () => {
    // No comma to shuffle here, so the quoted line IS the one that vanished.
    const s = sum('s("bd*4")\ns("hh*8")', 's("bd*4")');
    expect(s).toContain("hh*8");
  });
});

describe("the ring the mind is shown", () => {
  it("carries human edits beside the mind's own reasons", () => {
    // This is the point: the mind's "do not repeat the recent reasons" rule
    // then notices that a human just moved something.
    let ring: string[] = [];
    ring = pushReason(ring, "opened the bass filter") as string[];
    ring = pushReason(ring, sum('s("bd*4")', 's("bd*2")') as string) as string[];
    expect(ring).toHaveLength(2);
    expect(ring[1]).toMatch(/^human: /);
  });

  it("is capped, so a long set does not send an ever-growing prompt", () => {
    let ring: string[] = [];
    for (let i = 0; i < 20; i++) ring = pushReason(ring, `reason ${i}`) as string[];
    expect(ring.length).toBeLessThanOrEqual(5);
    expect(ring[ring.length - 1]).toBe("reason 19");
  });
});
