/**
 * §11 S7 — the palette, checked against the REAL registry.
 *
 * These read `scripts/algorave-spike/palette.json` itself rather than a
 * fixture. That is deliberate: the registry is the one vocabulary the
 * validator, the mind and the page share (§10), so a test against a copy would
 * pass while the thing that matters drifted.
 *
 * The load-bearing assertion is AC2: **every sound in the registry, inserted,
 * yields a buffer that parses.** A syntax error found mid-set is a pattern
 * that stops.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  banksFor,
  insertIntoBuffer,
  insertionFor,
  readPalette,
} from "@/lib/palette";

const registry = JSON.parse(
  readFileSync(
    join(__dirname, "..", "..", "..", "scripts", "algorave-spike", "palette.json"),
    "utf8",
  ),
);
const palette = readPalette(registry);

const OPENING = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("hh*8").bank("RolandTR909").gain(0.4)
).cpm(124/4)`;

/** Parses as JavaScript. It will not RUN outside Strudel, but it must parse. */
function parses(code: string): boolean {
  try {
    new Function(code);
    return true;
  } catch {
    return false;
  }
}

describe("the registry is reachable and whole", () => {
  it("carries the three categories the bank rule is built on", () => {
    expect(palette.drums.length).toBeGreaterThan(0);
    expect(palette.synths.length).toBeGreaterThan(0);
    expect(palette.instruments.length).toBeGreaterThan(0);
    expect(Object.keys(palette.banks).length).toBeGreaterThan(0);
  });

  it("matches the file it was read from — no second copy anywhere", () => {
    expect(palette.drums).toEqual(registry.drums);
    expect(palette.synths).toEqual(registry.synths);
    expect(palette.instruments).toEqual(registry.instruments);
  });

  it("has exactly the orphan drums we already know about", () => {
    // The registry's own doc: "a .bank() must both exist here and carry that
    // sound — a pair this matrix lacks plays SILENCE live". A drum no bank
    // carries is therefore listed in the mind's palette and unusable by it:
    // dead weight the validator will reject whichever bank is tried.
    //
    // `fx` is in that state today (2026-08-31). Removing it is a registry
    // decision, not a frontend one, so it is pinned here rather than fixed:
    // a NEW orphan fails this test, and the browser already renders these
    // permanently disabled with "<bank> does not carry <sound>".
    const orphans = palette.drums.filter((d) => banksFor(palette, d).length === 0);
    expect(orphans).toEqual(["fx"]);
  });
});

describe("the bank rule", () => {
  it("refuses to write a drum without a bank rather than guessing one", () => {
    expect(insertionFor("drums", "bd")).toBeNull();
    expect(insertionFor("drums", "bd", "RolandTR909")).toContain('.bank("RolandTR909")');
  });

  it("NEVER puts a bank on a sampled instrument — that is silence, not an error", () => {
    for (const sound of palette.instruments) {
      const line = insertionFor("instruments", sound);
      expect(line).not.toBeNull();
      expect(line).not.toContain(".bank(");
    }
  });

  it("never puts a bank on a synth either", () => {
    for (const sound of palette.synths) {
      expect(insertionFor("synths", sound)).not.toContain(".bank(");
    }
  });
});

describe("insertion always yields a buffer that parses (AC2)", () => {
  it("for every drum, on every bank that carries it", () => {
    let checked = 0;
    for (const sound of palette.drums) {
      for (const bank of banksFor(palette, sound)) {
        const line = insertionFor("drums", sound, bank);
        expect(line).not.toBeNull();
        const next = insertIntoBuffer(OPENING, line as string);
        expect(parses(next), `${sound} on ${bank}: ${next}`).toBe(true);
        checked++;
      }
    }
    // Guard against a silently empty loop passing this test.
    expect(checked).toBeGreaterThan(20);
  });

  it("for every synth and every sampled instrument", () => {
    for (const sound of [...palette.synths, ...palette.instruments]) {
      const category = palette.synths.includes(sound) ? "synths" : "instruments";
      const line = insertionFor(category, sound) as string;
      const next = insertIntoBuffer(OPENING, line);
      expect(parses(next), `${sound}: ${next}`).toBe(true);
    }
  });
});

describe("insertIntoBuffer", () => {
  it("puts the comma where the stack needs it", () => {
    // The last element of a stack carries no trailing comma, so appending
    // before the closing paren without moving it gives `a\nb)` — a syntax
    // error that only shows up when the buffer is evaluated.
    const out = insertIntoBuffer('stack(\n  s("bd*4")\n)', 's("hh*8")');
    expect(parses(out)).toBe(true);
    expect(out).toContain('s("bd*4"),');
  });

  it("starts a stack when there is nothing to add to", () => {
    expect(insertIntoBuffer("", 's("bd*4")')).toBe('s("bd*4")');
  });

  it("wraps a buffer that is not a stack, instead of corrupting it", () => {
    const out = insertIntoBuffer('s("bd*4")', 's("hh*8")');
    expect(parses(out)).toBe(true);
    expect(out.startsWith("stack(")).toBe(true);
  });

  it("survives a trailing newline, which an editor leaves constantly", () => {
    expect(parses(insertIntoBuffer('stack(\n  s("bd*4")\n)\n', 's("cp")'))).toBe(true);
  });
});
