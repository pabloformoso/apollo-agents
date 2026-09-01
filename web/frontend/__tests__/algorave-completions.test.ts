/**
 * Autocomplete — which suggestions are legal where.
 *
 * The load-bearing case is `.bank("`: the validator has always REJECTED a bank
 * that does not carry its sound, the browser has always shown the rule, and a
 * wrong pair still plays silence rather than failing. Completion is the first
 * place the wrong bank can simply not be offered — so these tests are about
 * the ranking as much as the list.
 */
import { describe, expect, it } from "vitest";
import { completionsFor, noteNames, soundBefore } from "@/lib/completions";
import { readPalette, type Palette } from "@/lib/palette";

const palette: Palette = readPalette({
  drums: ["bd", "sd", "cb", "fx"],
  synths: ["supersaw"],
  instruments: ["piano", "gretsch"],
  banks: {
    RolandTR909: ["bd", "sd"],
    RolandTR808: ["bd", "sd", "cb"],
  },
  sources: [],
  pitched: { piano: true, gretsch: false },
});

const labels = (before: string) =>
  (completionsFor(before, palette)?.options ?? []).map((o) => o.label);
const find = (before: string, label: string) =>
  completionsFor(before, palette)?.options.find((o) => o.label === label);

describe("soundBefore", () => {
  it("takes the LAST sound named, not the first", () => {
    expect(soundBefore('stack(s("bd*4").bank("X"), s("cb")')).toBe("cb");
  });

  it("is null when nothing has been named yet", () => {
    expect(soundBefore('stack(\n  ')).toBeNull();
  });
});

describe('inside s("…")', () => {
  it("offers everything the registry holds, and says how each is played", () => {
    const l = labels('s("');
    expect(l).toContain("bd");
    expect(l).toContain("supersaw");
    expect(l).toContain("piano");
    expect(find('s("', "supersaw")?.detail).toContain("note()");
    // The chromatic/one-shot distinction, at the point of typing.
    expect(find('s("', "piano")?.detail).toContain("chromatic");
    expect(find('s("', "gretsch")?.detail).toContain("one-shots");
  });

  it("names the banks a drum can use, rather than only that it needs one", () => {
    expect(find('s("', "bd")?.detail).toMatch(/RolandTR909|RolandTR808/);
  });

  it("marks a drum no bank carries instead of offering it as normal", () => {
    // `fx` is the registry's known orphan: listed, and unusable.
    expect(find('s("', "fx")?.detail).toContain("NO BANK");
    expect(find('s("', "fx")?.boost).toBeLessThan(0);
  });

  it("completes the word under the cursor inside mini-notation", () => {
    // "bd*4 ~ c" — the token being typed is `c`, not the whole argument.
    const c = completionsFor('s("bd*4 ~ c', palette);
    expect(c).not.toBeNull();
    expect(c!.from).toBe('s("bd*4 ~ '.length);
  });
});

describe('inside .bank("…") — the rule becomes unbreakable', () => {
  it("ranks the banks that carry the sound above the ones that do not", () => {
    const carrying = find('s("cb").bank("', "RolandTR808");
    const notCarrying = find('s("cb").bank("', "RolandTR909");
    expect(carrying?.detail).toContain("carries cb");
    expect(notCarrying?.detail).toContain("does NOT carry");
    expect(carrying!.boost!).toBeGreaterThan(notCarrying!.boost!);
  });

  it("says a wrong pair is SILENCE, not an error — the thing that makes it dangerous", () => {
    expect(find('s("cb").bank("', "RolandTR909")?.detail).toContain("silence");
  });

  it("offers nothing at all for a sound that takes no bank", () => {
    // A sampled instrument with a bank resolves to no sample. Offering one
    // would be offering silence.
    expect(labels('s("piano").bank("')).toEqual([]);
    expect(labels('s("supersaw").bank("')).toEqual([]);
  });

  it("falls back to every bank when no sound has been named yet", () => {
    expect(labels('.bank("')).toEqual(["RolandTR909", "RolandTR808"]);
  });
});

describe("notes and methods", () => {
  it('offers note names inside note("…")', () => {
    expect(labels('note("')).toContain("c3");
    expect(labels('note("')).toContain("ds4");
  });

  it("offers methods after a dot, outside a string", () => {
    const l = labels('s("bd*4").');
    expect(l).toContain("bank");
    expect(l).toContain("gain");
    expect(l).toContain("midi");
  });

  it("completes a half-typed method from where it starts", () => {
    const c = completionsFor('s("bd*4").ga', palette);
    expect(c!.from).toBe('s("bd*4").'.length);
    expect(c!.options.map((o) => o.label)).toContain("gain");
  });

  it("offers nothing in open code that is neither a string nor a dot", () => {
    expect(completionsFor("stack(\n  ", palette)).toBeNull();
  });

  it("covers the octaves a live set actually uses", () => {
    expect(noteNames()).toContain("c1");
    expect(noteNames()).toContain("b6");
  });
});
