/**
 * §11 S3 — minimal ambient types for Strudel.
 *
 * `@strudel/web` ships no `.d.ts` and has no `exports` field, only `main`
 * (CJS `dist/index.js`) and `module` (ESM `dist/index.mjs`). TypeScript
 * resolves it through `main`, which is a second reason the Turbopack alias in
 * next.config.ts pins the file explicitly rather than trusting resolution.
 *
 * These declarations cover only what the app actually calls. They are not an
 * attempt to type the 1017 exports of the bundle — everything else stays
 * `unknown` on purpose, so reaching for an untyped export is a compile error
 * and not a silent `any`.
 *
 * `@strudel/core` is declared with the SAME `Pattern` type deliberately: the
 * alias makes both specifiers the same module at runtime, and the identity
 * assertion in `/algorave-spike` is what proves it.
 */

/** The pattern class. Opaque here — we only ever compare its identity. */
type StrudelPatternClass = new (...args: never[]) => unknown;

declare module "@strudel/web" {
  export const Pattern: StrudelPatternClass;
  /** Boots the audio engine. Needs a user gesture, or the context stays suspended. */
  export function initStrudel(options?: Record<string, unknown>): Promise<void>;
  /** Evaluates pattern source and hot-swaps it into the running scheduler. */
  export function evaluate(code: string): Promise<unknown>;
  /** Stops everything. */
  export function hush(): void;
}

declare module "@strudel/core" {
  export const Pattern: StrudelPatternClass;
}
