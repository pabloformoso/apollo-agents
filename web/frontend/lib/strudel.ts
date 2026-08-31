/**
 * §11 S3 — the one place that knows how to load and boot Strudel.
 *
 * Two hard-won rules live here. Both were found by a real browser, not by
 * reasoning, and both fail SILENTLY when broken.
 *
 * 1. **Strudel must not be bundled.** Its bundle resolves its own AudioWorklet
 *    asset with `new URL("assets/clockworker-<hash>.js", import.meta.url)` —
 *    relative to the module's own URL. Bundled, `import.meta.url` becomes a
 *    hashed chunk path, `assets/` resolves next to that chunk where nothing
 *    exists, `addModule()` 404s, and then EVERY AudioWorkletNode construction
 *    throws "AudioWorklet does not have a valid AudioWorkletGlobalScope" —
 *    once per event, forever, while superdough still logs "[superdough] ready".
 *    So it is staged into `public/vendor/strudel/` (scripts/vendor-strudel.mjs,
 *    run from predev/prebuild) and loaded by URL, which is the same topology
 *    `scripts/algorave-spike/serve.mjs` serves and the playground has always
 *    relied on.
 *
 * 2. **Sample sources must be registered before anything plays.** `initStrudel`
 *    boots the engine but registers no sounds; `.bank("RolandTR909")` then
 *    resolves to nothing and every event logs `sound RolandTR909_bd not found!`
 *    while the transport happily runs. The playground registers the palette's
 *    sources first; so does `boot()` below.
 *
 * The import is made opaque to the bundler on purpose — see `loadStrudel`.
 */

/** The slice of Strudel's 1017 exports the app actually calls. */
export interface StrudelModule {
  /** The pattern class. Used for identity checks; never constructed here. */
  Pattern: unknown;
  initStrudel: (options?: Record<string, unknown>) => Promise<void>;
  evaluate: (code: string) => Promise<unknown>;
  hush: () => void;
  /** Registers a sample map. `base` is prepended to every path inside it. */
  samples: (
    json: string | Record<string, unknown>,
    base?: string,
    options?: { prebake?: boolean; tag?: string },
  ) => Promise<unknown>;
}

/** A sample source, shaped like an entry of palette.json's `sources`. */
export interface SampleSource {
  json: string;
  base: string;
  tag?: string;
}

export const STRUDEL_URL = "/vendor/strudel/index.mjs";

/**
 * The tidal-drum-machines source, verbatim from the playground's
 * FALLBACK_SOURCES. Used when the palette registry is not reachable — network
 * trouble must degrade the palette, never ground the jam.
 */
const CDN = "https://strudel.b-cdn.net";
export const FALLBACK_SOURCES: SampleSource[] = [
  {
    json: `${CDN}/tidal-drum-machines.json`,
    base: `${CDN}/tidal-drum-machines/machines/`,
    tag: "drum-machines",
  },
];

/**
 * `new Function` rather than a plain `import()` so no bundler can see the
 * specifier and decide to help. A magic comment would depend on the bundler
 * honouring it; this does not. It is the whole point of rule 1 above.
 */
const opaqueImport = new Function("u", "return import(u)") as (
  u: string,
) => Promise<StrudelModule>;

let cached: Promise<StrudelModule> | null = null;

/** Loads the engine once per page. Safe to call from anywhere. */
export function loadStrudel(): Promise<StrudelModule> {
  cached ??= opaqueImport(STRUDEL_URL);
  return cached;
}

export interface BootResult {
  strudel: StrudelModule;
  /** Tags of the sources that registered successfully. */
  registered: string[];
  /** Sources that failed, with the reason. Boot succeeds anyway. */
  failed: { tag: string; error: string }[];
}

/**
 * Boots the engine and registers sample sources. Must be called from a user
 * gesture: an AudioContext created without one is suspended and stays silent.
 *
 * A source that fails to register is reported, not thrown — one dead CDN must
 * not cost the whole session.
 */
export async function boot(
  sources: SampleSource[] = FALLBACK_SOURCES,
): Promise<BootResult> {
  const strudel = await loadStrudel();
  await strudel.initStrudel();

  const registered: string[] = [];
  const failed: { tag: string; error: string }[] = [];
  await Promise.all(
    sources.map(async (src) => {
      const tag = src.tag ?? "palette";
      try {
        await strudel.samples(src.json, src.base, { prebake: true, tag });
        registered.push(tag);
      } catch (err) {
        failed.push({ tag, error: String(err) });
      }
    }),
  );

  return { strudel, registered, failed };
}
