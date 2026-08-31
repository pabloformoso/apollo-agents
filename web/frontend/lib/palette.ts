/**
 * §11 S7 — the palette, and the bank rule made explicit.
 *
 * The rule the whole registry is built on (§10):
 *
 *   - **drums** are bank-prefixed and REQUIRE a bank. `s("bd")` with no bank
 *     resolves to whatever a default map happens to hold; the pair
 *     (sound, bank) must exist in the matrix or it is not a sound.
 *   - **synths** are oscillators. No bank exists for them and none is wanted.
 *   - **instruments** are SAMPLED and must NEVER carry a bank. A `.bank()` on
 *     one is not an error — it is SILENCE, which is the worst kind of wrong
 *     because it looks like it worked.
 *
 * Insertion is a pure function so that "can this produce invalid Strudel?" is
 * a question a test can answer for every sound in the registry, rather than
 * something discovered mid-set.
 */

export type PaletteCategory = "drums" | "synths" | "instruments";

export interface Palette {
  drums: string[];
  synths: string[];
  instruments: string[];
  /** bank name → the drum sounds that bank actually has. */
  banks: Record<string, string[]>;
  sources?: { json: string; base: string; tag?: string }[];
}

export const CATEGORIES: ReadonlyArray<[PaletteCategory, string, string]> = [
  ["drums", "Drums", "bank-prefixed · a bank is required"],
  ["synths", "Synths", "oscillators · no bank"],
  ["instruments", "Instruments", "sampled · a bank is silence"],
];

/** Normalises whatever the registry route returned into the shape used here. */
export function readPalette(raw: unknown): Palette {
  const o = (raw ?? {}) as Record<string, unknown>;
  const list = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const banksIn = (o.banks ?? {}) as Record<string, unknown>;
  const banks: Record<string, string[]> = {};
  for (const [name, sounds] of Object.entries(banksIn)) banks[name] = list(sounds);
  return {
    drums: list(o.drums),
    synths: list(o.synths),
    instruments: list(o.instruments),
    banks,
  };
}

/** Which banks actually carry this drum sound. Empty means: not playable. */
export function banksFor(palette: Palette, sound: string): string[] {
  return Object.entries(palette.banks)
    .filter(([, sounds]) => sounds.includes(sound))
    .map(([name]) => name);
}

/**
 * The Strudel line for one sound.
 *
 * A drum without a bank returns null rather than a guess: the caller must
 * choose one, and inventing a default is how a set ends up playing a sound
 * nobody picked. Instruments and synths never take a bank — the parameter is
 * not even accepted, so a caller cannot pass one by accident.
 */
export function insertionFor(
  category: PaletteCategory,
  sound: string,
  bank?: string,
): string | null {
  if (category === "drums") {
    if (!bank) return null;
    return `s("${sound}*4").bank("${bank}")`;
  }
  // Both oscillators and sampled instruments are pitched, and neither may
  // carry a bank. Same line for both, which is the point: the difference is
  // where the sound comes from, not how it is written.
  return `note("c3 eb3 g3").s("${sound}")`;
}

/**
 * Adds a line to a `stack(...)` buffer, or starts one.
 *
 * The comma placement is the whole job: the last element of a stack carries no
 * trailing comma, so appending before the closing paren without moving it
 * produces `a\nb)` — a syntax error that only shows up when the buffer is
 * evaluated, which during a set means the pattern stops.
 */
export function insertIntoBuffer(buffer: string, line: string): string {
  const trimmed = buffer.trimEnd();
  const close = trimmed.lastIndexOf(")");

  if (!trimmed.startsWith("stack(") || close === -1) {
    // Not a stack we understand: wrap both, which is always valid.
    return trimmed.length === 0
      ? line
      : `stack(\n  ${trimmed.replace(/\n/g, "\n  ")},\n  ${line}\n)`;
  }

  const head = trimmed.slice(0, close).trimEnd();
  const tail = trimmed.slice(close);
  const needsComma = !head.endsWith(",");
  return `${head}${needsComma ? "," : ""}\n  ${line}\n${tail}`;
}
