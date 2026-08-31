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
  /**
   * The sample maps the engine must register before ANY of this is playable.
   * Load only `drum-machines` and every `instruments` entry — the piano and the
   * nine VCSL sounds of #146/#147 — resolves to nothing, silently: no error,
   * no sample fetch, no sound. The browser would offer them and they would not
   * play, which is the worst failure this lane has.
   */
  sources: { json: string; base: string; tag?: string }[];
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
  const sources = Array.isArray(o.sources)
    ? (o.sources as Record<string, unknown>[])
        .filter((s) => typeof s?.json === "string" && typeof s?.base === "string")
        .map((s) => ({
          json: String(s.json),
          base: String(s.base),
          tag: typeof s.tag === "string" ? s.tag : undefined,
        }))
    : [];

  return {
    drums: list(o.drums),
    synths: list(o.synths),
    instruments: list(o.instruments),
    banks,
    sources,
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
 * Finds the `)` that closes the `stack(` a buffer opens with, or -1.
 *
 * `lastIndexOf(")")` is NOT this, and the difference is a silent musical bug:
 * the opening buffer ends `).cpm(124/4)`, so the last paren closes `cpm`, and
 * inserting before it makes the new layer a SECOND ARGUMENT to `cpm` —
 * perfectly valid JavaScript that plays nothing at all. Found 2026-08-31 by a
 * piano that registered, never triggered, and therefore never loaded.
 *
 * Depth counting, and string-aware: a `")"` inside a mini-notation literal
 * must not close anything.
 */
export function stackCloseIndex(buffer: string): number {
  const open = buffer.indexOf("stack(");
  if (open === -1) return -1;

  let depth = 0;
  let quote: string | null = null;
  for (let i = open + "stack".length; i < buffer.length; i++) {
    const ch = buffer[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "(") depth++;
    else if (ch === ")") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * The stack's TOP-LEVEL arguments — its layers. Used by the tests to assert
 * that an insertion actually became a layer, rather than merely leaving the
 * buffer parseable.
 */
export function stackLayers(buffer: string): string[] {
  const open = buffer.indexOf("stack(");
  const close = stackCloseIndex(buffer);
  if (open === -1 || close === -1) return [];

  const inner = buffer.slice(open + "stack(".length, close);
  const out: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") depth--;
    else if (ch === "," && depth === 0) {
      out.push(inner.slice(start, i).trim());
      start = i + 1;
    }
  }
  const last = inner.slice(start).trim();
  if (last) out.push(last);
  return out.filter((x) => x.length > 0);
}

/**
 * Adds a line to a `stack(...)` buffer as a new LAYER, or starts one.
 *
 * Two things have to be right, and both bite silently:
 *   - the paren must be the STACK's, not the last one in the buffer
 *     (see `stackCloseIndex`);
 *   - the last existing layer carries no trailing comma, so one has to be
 *     added or the result is `a\nb)` — a syntax error that only surfaces on
 *     evaluate, which mid-set is the pattern stopping.
 */
export function insertIntoBuffer(buffer: string, line: string): string {
  const trimmed = buffer.trimEnd();
  const close = stackCloseIndex(trimmed);

  if (close === -1) {
    // Not a stack we understand: wrap both, which is always valid.
    return trimmed.length === 0
      ? line
      : `stack(\n  ${trimmed.replace(/\n/g, "\n  ")},\n  ${line}\n)`;
  }

  const head = trimmed.slice(0, close).trimEnd();
  const tail = trimmed.slice(close);
  const needsComma = !head.endsWith(",") && !head.endsWith("stack(");
  return `${head}${needsComma ? "," : ""}\n  ${line}\n${tail}`;
}
