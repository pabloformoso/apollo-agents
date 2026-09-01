/**
 * Reading a verdict — the distinction a performer acts on.
 *
 * `invalid` means the pattern will NOT play. Out-of-key means it WILL play and
 * clash. Flattening those into one colour would tell someone to stop when they
 * only need to listen, and plenty of good music is out of key on purpose.
 */
import { describe, expect, it } from "vitest";
import { readVerdict, type Verdict } from "@/lib/validate";

const v = (over: Partial<Verdict>): Verdict => ({
  valid: true, error: null, reason: null, stats: {}, ...over,
});

describe("readVerdict", () => {
  it("says nothing has been checked before anything has", () => {
    expect(readVerdict(null).tone).toBe("unknown");
  });

  it("is an ERROR when the validator refused it — this will not play", () => {
    const r = readVerdict(v({ valid: false, error: "palette violation: sound(s) not in the palette — east" }));
    expect(r.tone).toBe("error");
    expect(r.headline).toContain("east");
  });

  it("is a WARNING when out of key — this plays, and clashes", () => {
    const r = readVerdict(v({ stats: { out_of_key: ["C#", "G#"] } }));
    expect(r.tone).toBe("warn");
    expect(r.headline).toContain("C#");
    expect(r.headline).toContain("G#");
  });

  it("never downgrades an invalid pattern to a warning because of the key", () => {
    // Both wrong at once: the one that stops the music wins the colour.
    const r = readVerdict(v({ valid: false, error: "syntax error", stats: { out_of_key: ["C#"] } }));
    expect(r.tone).toBe("error");
  });

  it("carries the facts worth glancing at mid-set", () => {
    const r = readVerdict(v({ stats: { events: 44, sounds: ["bd", "cp"], kick_four_on_floor: true } }));
    expect(r.tone).toBe("ok");
    expect(r.facts).toContain("44 events");
    expect(r.facts).toContain("bd cp");
    expect(r.facts).toContain("kick 4/4");
  });

  it("keeps the facts even when refusing, so the refusal is readable", () => {
    const r = readVerdict(v({ valid: false, error: "nope", stats: { events: 12 } }));
    expect(r.facts).toContain("12 events");
  });
});
