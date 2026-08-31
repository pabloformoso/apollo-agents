#!/usr/bin/env node
/*
 * ApolloAgents — algorave lane, iteration 1 (S2). docs/algorave-livecoding-plan.md §8.1.
 *
 *   node validate.mjs [--cycles N] [--key "A:minor"] [--genre deep]
 *
 * Reads Strudel REPL-dialect code on stdin, evaluates it against a Node-only
 * scope (@strudel/core + mini + tonal — NO webaudio, no network, no audio),
 * and prints exactly ONE verdict JSON line on stdout:
 *
 *   {"valid": bool, "error": str|null, "reason": str|null,
 *    "stats": {"events": int, "cycles_checked": int, "sounds": [str],
 *              "kick_four_on_floor": bool, "out_of_key": [str]}}
 *
 * Exit code is 0 whenever a verdict was computed — valid OR invalid. Nonzero
 * exit means the HARNESS broke (Strudel itself failed to load), not that the
 * pattern was bad; on that path stdout stays empty and the diagnosis goes to
 * stderr. This is what lets agent/generative/strudel_mind.py treat a nonzero
 * exit as its own bug and a `{"valid": false}` verdict as the model's.
 *
 * ---------------------------------------------------------------------------
 * The @strudel/core import problem (see README "API surprises" #1 for the
 * full story) — restated here because it is *why* this file looks the way it
 * does: @strudel/core@1.2.6's dist/index.mjs does
 *   import { SalatRepl } from '@kabelsalat/web'
 * and @kabelsalat/web@0.4.1's "main" is an IIFE bundle, not ESM — Node's loader
 * refuses to bind a named export out of it and EVERY import of @strudel/core
 * (hence @strudel/mini, @strudel/transpiler) dies with "does not provide an
 * export named 'SalatRepl'". vitest.config.mjs fixes this with a Vite
 * `resolve.alias`, but that mechanism does not exist outside Vite — this is a
 * plain Node script, so it needs a plain-Node fix.
 *
 * The workaround verified here: Node's own `module.registerHooks()` (stable,
 * synchronous, same-thread — no `--experimental-loader` flag, no extra file on
 * disk) intercepts the ESM resolver and redirects the bare specifier
 * "@kabelsalat/web" to that package's OWN real ESM build, dist/index.mjs.
 * Registered once, before anything touches @strudel/*, every transitive
 * `import ... from '@kabelsalat/web'` resolves to the working file instead of
 * the broken one. This has to run BEFORE @strudel/core is imported, which is
 * why those imports are dynamic (`await import(...)`) inside `main()` rather
 * than static top-of-file imports — static imports are hoisted and would
 * execute before the hook is registered.
 * ---------------------------------------------------------------------------
 */

import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

// ---------------------------------------------------------------------------
// Constants — the §8.1 contract.
// ---------------------------------------------------------------------------

// Four cycles == four bars: long enough for `<a b>`-style per-bar alternation
// to actually be exercised (the deep house few-shot leans on it for the bass
// root and the chord change), short enough that a rejection is instant.
// agent/generative/strudel_mind.py always passes --cycles explicitly, but a
// human running this by hand should get a sensible default too.
export const DEFAULT_CYCLES = 4;

// The sound vocabulary comes from palette.json — ONE registry (plan §10) that
// this validator, agent/generative/strudel_mind.py and the spike pages all
// read, so sounds and banks are enabled by DATA, never by code. v1's
// "`bank()` is free-form" rule died with the registry: the registered sample
// map is machine-prefixed (`RolandTR909_bd`), so a bank the registry does not
// know — or a (sound, bank) pair its matrix lacks — resolves to no sample and
// plays SILENCE live, which is exactly the failure this gate exists to catch.
//
// The registry has THREE sound categories, and only the `.bank()` rule tells
// them apart: `drums` are bank-prefixed samples (they need the right bank),
// `synths` are oscillators (no samples at all), and `instruments` are
// sample-backed sounds whose map is NOT bank-prefixed — `piano.json` keys the
// sound name directly, so `.bank()` on one resolves to nothing exactly the way
// it does on a synth voice. No pitched-vs-percussive distinction is made or
// needed: an instrument is simply a bankless sound.

// Word-boundary match, not an AST walk — deliberately blunt (see §8.1: "hygiene
// against a confused model, not a security boundary against attackers"). This
// means a mini-notation step named e.g. s("process") would also trip it; that
// false positive is the accepted cost of a scan simple enough to audit at a
// glance.
const BANNED_TOKEN_RE = /\b(import|require|fetch|eval|process)\b/g;

// First-line-only, case-insensitive, tab-tolerant — mirrors
// agent/generative/strudel_mind.py's own `_REASON_RE` character classes
// exactly (`[ \t]*...[ \t]*:[ \t]*(.+)`), except that regex `.search()`es the
// whole (multiline) reply as a fallback while this one is scoped to line 1
// only, per §8.1's "optional FIRST line". That asymmetry is intentional: the
// Python-side fallback exists precisely to catch what this stricter rule
// doesn't.
const REASON_RE = /^[ \t]*\/\/[ \t]*reason[ \t]*:[ \t]*(.+)$/i;

// "A:minor" / "a#:major" / etc. Octave-qualified roots like the pattern-code
// convention ".scale(\"A1:minor\")" are a Strudel note-parsing detail, not the
// --key flag's format — agent/generative/strudel_mind.py always passes a bare
// "A:minor".
const KEY_RE = /^([A-Ga-g])([#b]?):(minor|major)$/i;

// Note-name parsing, and the pitch-class arithmetic below, use the SAME
// letter->semitone table @strudel/core itself uses internally (verified
// against node_modules/@strudel/core/dist/index.mjs) and the same sharp
// spelling as agent/generative/scales.py's `_PC_NAMES`.
const LETTER_PC = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
const PC_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

// Natural-minor / major step patterns (semitones from the tonic).
const MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10];
const MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11];

const REQUIRED_KICK_PHASES = [0, 0.25, 0.5, 0.75];

// ---------------------------------------------------------------------------
// Helpers — no @strudel import, no I/O on import. Safe to `import` from a test
// file without triggering the CLI (see `isMain()` at the bottom): none of this
// runs Strudel, reads stdin, or touches console.log/process.exitCode at import
// time. The one function that touches the filesystem, `loadPaletteRegistry`,
// only does so when called.
// ---------------------------------------------------------------------------

/** `["--cycles", "8", "--key", "A:minor", "--genre", "deep"]` ->
 * `{cycles: 8, key: "A:minor", genre: "deep"}`.
 * Unrecognised or unparsable flag values fall back to a safe default rather
 * than crashing the process — CLI-usage mistakes are not the kind of failure
 * this tool's exit-code contract is about (see the module header). */
export function parseArgs(argv) {
  let cycles = DEFAULT_CYCLES;
  let key = null;
  let genre = null;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--cycles') {
      const raw = argv[++i];
      const n = Number.parseInt(raw, 10);
      if (Number.isInteger(n) && n > 0) {
        cycles = n;
      } else {
        process.stderr.write(
          `validate.mjs: ignoring malformed --cycles value ${JSON.stringify(raw)}, using default ${DEFAULT_CYCLES}\n`,
        );
      }
    } else if (arg === '--key') {
      key = argv[++i] ?? null;
    } else if (arg === '--genre') {
      genre = argv[++i] ?? null;
    }
  }
  return { cycles, key, genre };
}

/** Reads and shape-checks `palette.json` (next to this file). Throws on a
 * missing or malformed registry — that is HARNESS breakage (a committed file
 * is gone or corrupt), never a verdict about the model's code, so `main()`
 * routes it to stderr + exit 1 exactly like a broken Strudel install. */
export function loadPaletteRegistry() {
  const file = fileURLToPath(new URL('./palette.json', import.meta.url));
  const registry = JSON.parse(readFileSync(file, 'utf8'));
  // `roles` is required here even though nothing below enforces it (an event
  // cannot be attributed to a role, so the table is prompt-side data): the two
  // sides shape-check the ONE registry identically, or they drift.
  for (const field of ['sources', 'drums', 'synths', 'instruments', 'roles', 'banks', 'genres']) {
    if (!(field in registry)) {
      throw new Error(`palette.json is missing the "${field}" field`);
    }
  }
  return registry;
}

/** The enforcement sets for one run: the genre's entry when the registry has
 * it, the registry-wide vocabulary otherwise (an unknown genre narrows
 * nothing — same degrade rule as a malformed --key). `genre` in the result is
 * the entry actually used, or null when it fell back.
 *
 * `instruments` is read per-FIELD rather than per-entry: a genre entry that
 * does not mention instruments inherits the registry-wide list instead of
 * silently having none. That keeps adding an instrument to the registry a
 * pure-data move even for genres written before the category existed. */
export function paletteFor(registry, genre) {
  const has = (obj, key) => obj != null && Object.prototype.hasOwnProperty.call(obj, key);
  const entry = genre && has(registry.genres, genre) ? registry.genres[genre] : null;
  const drums = entry ? entry.drums : registry.drums;
  const synths = entry ? entry.synths : registry.synths;
  const instruments = has(entry, 'instruments') ? entry.instruments : registry.instruments;
  const bankNames = entry ? entry.banks : Object.keys(registry.banks);
  return {
    sounds: new Set([...drums, ...synths, ...instruments]),
    synths: new Set(synths),
    instruments: new Set(instruments),
    banks: new Map(bankNames.map((name) => [name, new Set(registry.banks[name] ?? [])])),
    genre: entry ? genre : null,
  };
}

/** Splits the optional `// reason: ...` first line out of raw code.
 * Returns `{ reason, codeForScreening }`: `codeForScreening` is everything
 * AFTER that line (or the whole input, unchanged, when there is no reason
 * line) — the text the token screen runs over, so reason prose can never trip
 * it (§8.1: "a `// reason:` comment line is exempt from the screen"). The code
 * actually transpiled/evaluated is always the full original input: `//`
 * comments are inert to the JS parser, so there is no need to strip one out. */
export function extractReason(rawCode) {
  const newlineIdx = rawCode.indexOf('\n');
  const firstLineRaw = newlineIdx === -1 ? rawCode : rawCode.slice(0, newlineIdx);
  const firstLine = firstLineRaw.replace(/\r$/, ''); // tolerate CRLF input
  const match = firstLine.match(REASON_RE);
  if (!match) return { reason: null, codeForScreening: rawCode };
  const rest = newlineIdx === -1 ? '' : rawCode.slice(newlineIdx + 1);
  return { reason: match[1].trim(), codeForScreening: rest };
}

/** A note value (string like "bb3"/"gs4"/"A1", or a bare number) -> pitch
 * class 0-11, or `null` if it can't be read as a note. Accidentals follow
 * @strudel/core's own alphabet: `#`/`s` raise a semitone, `b`/`f` lower one
 * (verified: note("cs4 df4 gs4") round-trips through the real evaluator as
 * typed). Numbers are treated as semitones with pitch class 0 = C, matching
 * @strudel/core's own note<->number convention (verified: note("0 3 7") ->
 * {note:0}/{note:3}/{note:7}, i.e. C/D#/G). */
export function notePitchClass(noteValue) {
  if (typeof noteValue === 'number' && Number.isFinite(noteValue)) {
    return (((Math.round(noteValue) % 12) + 12) % 12);
  }
  if (typeof noteValue !== 'string') return null;
  const match = noteValue.match(/^([a-gA-G])([#bsf]*)(-?\d+)?$/);
  if (!match) return null;
  const base = LETTER_PC[match[1].toLowerCase()];
  let offset = 0;
  for (const ch of match[2] ?? '') {
    if (ch === '#' || ch === 's') offset += 1;
    else if (ch === 'b' || ch === 'f') offset -= 1;
  }
  return (((base + offset) % 12) + 12) % 12;
}

/** Pitch class 0-11 -> canonical sharp-spelled name ("C#"), matching
 * agent/generative/scales.py's `pc_name`. */
export function pcName(pc) {
  return PC_NAMES[((pc % 12) + 12) % 12];
}

/** "A:minor" -> the Set of allowed pitch classes, or `null` if the string
 * isn't in `<letter>[#b]:<minor|major>` form. Mirrors
 * agent/generative/scales.py's `camelot_scale`: minor additionally admits the
 * raised 7th (harmonic-minor leading tone) — Tidal idiom leans on `.scale()`,
 * and a V7 in a minor key is idiomatic, not a mistake. Major gets no
 * alteration, same as the Python source. */
export function keyPitchClasses(key) {
  if (typeof key !== 'string') return null;
  const match = key.match(KEY_RE);
  if (!match) return null;
  const [, letter, accidental, mode] = match;
  let tonic = LETTER_PC[letter.toLowerCase()];
  if (accidental === '#') tonic = (tonic + 1) % 12;
  else if (accidental === 'b') tonic = (tonic + 11) % 12;
  const steps = mode.toLowerCase() === 'minor' ? MINOR_STEPS : MAJOR_STEPS;
  const pcs = new Set(steps.map((s) => (tonic + s) % 12));
  if (mode.toLowerCase() === 'minor') pcs.add((tonic + 11) % 12);
  return pcs;
}

const roundPhase = (x) => Math.round(x * 1e6) / 1e6;

/** One pass over `pattern.queryArc(0, cycles)`'s onset events -> every §8.1
 * stat plus two internal violation lists: `violations` (sounds outside the
 * palette — including events with no sound at all, which cannot reach
 * superdough either) and `bankViolations` (a `.bank()` the registry does not
 * know, a (sound, bank) pair the bank's matrix row lacks, or a bank on a
 * synth voice or an instrument — each of which resolves to no sample and
 * plays silence).
 * Callers decide what non-empty lists mean for `valid`; this function only
 * observes. `palette` is a `paletteFor()` result. Does not import or know
 * about @strudel — `pattern` just needs a `queryArc(from, to)` returning hits
 * with `.hasOnset()`/`.whole.begin`/`.value`, so this stays testable against
 * a fake in principle even though the real caller always passes a live
 * Strudel Pattern. */
export function computeStats(pattern, cycles, keyPcs, palette) {
  const haps = pattern.queryArc(0, cycles).filter((h) => h.hasOnset());

  const sounds = new Set();
  const violations = new Set();
  const bankViolations = new Set();
  const outOfKey = new Set();
  const kickPhasesByCycle = Array.from({ length: cycles }, () => new Set());

  for (const hap of haps) {
    const value = hap.value;
    const isObj = value !== null && typeof value === 'object';
    const soundName = isObj ? value.s : undefined;

    if (typeof soundName === 'string') sounds.add(soundName);
    if (!palette.sounds.has(soundName)) {
      violations.add(typeof soundName === 'string' ? soundName : '(missing sound)');
    }

    const bank = isObj ? value.bank : undefined;
    if (typeof bank === 'string' && bank.length > 0) {
      if (palette.synths.has(soundName)) {
        bankViolations.add(
          `.bank("${bank}") on synth voice '${soundName}' plays silence — synth layers take no bank`,
        );
      } else if (palette.instruments.has(soundName)) {
        // Same rationale as the synth case, different reason: an instrument
        // IS sample-backed, but its map is not bank-prefixed, so the pair
        // resolves to no sample at all. The fix is to drop the bank, not to
        // find a bank that carries it — hence its own message.
        bankViolations.add(
          `.bank("${bank}") on instrument '${soundName}' plays silence — a sampled ` +
            `instrument's map is not bank-prefixed; play it bare: .s("${soundName}")`,
        );
      } else if (!palette.banks.has(bank)) {
        bankViolations.add(
          `unknown bank '${bank}' — the banks that exist: ${[...palette.banks.keys()].sort().join(', ')}`,
        );
      } else if (
        typeof soundName === 'string' &&
        palette.sounds.has(soundName) &&
        !palette.banks.get(bank).has(soundName)
      ) {
        const carriers = [...palette.banks.entries()]
          .filter(([, roles]) => roles.has(soundName))
          .map(([name]) => name)
          .sort();
        bankViolations.add(
          carriers.length > 0
            ? `'${soundName}' is not in bank ${bank} — banks that have it: ${carriers.join(', ')}`
            : `'${soundName}' is not in bank ${bank}`,
        );
      }
    }

    if (soundName === 'bd') {
      const begin = hap.whole.begin.valueOf();
      const cycleIndex = Math.floor(begin);
      if (cycleIndex >= 0 && cycleIndex < cycles) {
        kickPhasesByCycle[cycleIndex].add(roundPhase(begin - cycleIndex));
      }
    }

    if (keyPcs && isObj && 'note' in value) {
      const pc = notePitchClass(value.note);
      if (pc !== null && !keyPcs.has(pc)) outOfKey.add(pcName(pc));
    }
  }

  const kickFourOnFloor =
    cycles > 0 &&
    kickPhasesByCycle.every((phases) => REQUIRED_KICK_PHASES.every((p) => phases.has(p)));

  return {
    events: haps.length,
    sounds: [...sounds].sort(),
    kickFourOnFloor,
    outOfKey: [...outOfKey].sort(),
    violations: [...violations].sort(),
    bankViolations: [...bankViolations].sort(),
  };
}

/** Builds the exact §8.1 verdict shape, key order fixed so identical inputs
 * serialize byte-for-byte identical (the spec's determinism requirement —
 * list stats are pre-sorted by computeStats/the caller, and this function
 * never reorders or omits a key). */
export function makeVerdict(valid, error, reason, stats) {
  return {
    valid,
    error: error ?? null,
    reason: reason ?? null,
    stats: {
      events: stats?.events ?? 0,
      cycles_checked: stats?.cyclesChecked ?? 0,
      sounds: stats?.sounds ?? [],
      kick_four_on_floor: stats?.kickFourOnFloor ?? false,
      out_of_key: stats?.outOfKey ?? [],
    },
  };
}

// ---------------------------------------------------------------------------
// I/O
// ---------------------------------------------------------------------------

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8').replace(/\r\n/g, '\n');
}

function emit(verdict) {
  // process.stdout.write, not console.log: console.log is silenced for the
  // whole run below (Strudel prints its own banner through it), and using the
  // raw stream here means the verdict line is unaffected by that regardless
  // of ordering.
  process.stdout.write(JSON.stringify(verdict) + '\n');
}

/** Registers the @kabelsalat/web redirect (see the module header) and dynamic-
 * imports core/mini/tonal/transpiler, in that order, then populates the
 * REPL-style global scope (`stack`, `s`, `n`, `note`, `mini`/`m`, ...) via
 * `core.evalScope`. Importing @strudel/tonal is also what registers
 * `.scale()` onto Pattern.prototype — a side effect of the import itself, not
 * of evalScope. Throws on genuine harness breakage (missing/broken
 * node_modules); the caller treats that as fatal, not a verdict. */
async function loadStrudel() {
  const kabelsalatEsm = pathToFileURL(
    fileURLToPath(new URL('./node_modules/@kabelsalat/web/dist/index.mjs', import.meta.url)),
  ).href;

  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier === '@kabelsalat/web') return nextResolve(kabelsalatEsm, context);
      return nextResolve(specifier, context);
    },
  });

  const core = await import('@strudel/core');
  const mini = await import('@strudel/mini');
  const tonal = await import('@strudel/tonal'); // side effect: registers .scale()
  const transpilerPkg = await import('@strudel/transpiler');

  await core.evalScope(core, mini, tonal);

  // `.midi("port")` is a browser method — WebMIDI does not exist here, and
  // `@strudel/midi` would drag in its own `@strudel/core` and therefore a
  // second Pattern class (the trap web/frontend/lib/strudel.ts documents). But
  // the validator MUST still accept it: the moment a human routes a layer to a
  // synth, every subsequent mutation the mind writes carries `.midi(...)`, and
  // without this the pattern would be rejected as a syntax error — the mind
  // silently unable to touch the set from then on.
  //
  // A no-op that returns the pattern unchanged is exactly right for gating:
  // `queryArc` sees the same events either way, because MIDI changes where the
  // notes GO, not what they are.
  if (typeof core.Pattern?.prototype?.midi !== 'function') {
    core.Pattern.prototype.midi = function midi() {
      return this;
    };
  }

  return transpilerPkg;
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main() {
  // Silenced for the rest of the process, not just around the imports below:
  // @strudel/core logs through console.log on more than just load (e.g. its
  // throttled `E(...)` logger), and the §8.1 contract is ONE line on stdout no
  // matter what the evaluated pattern does. console.error/warn are untouched
  // (they go to stderr, which this tool's contract has no opinion about).
  console.log = () => {};
  console.info = () => {};

  const args = parseArgs(process.argv.slice(2));

  let transpilerPkg;
  try {
    transpilerPkg = await loadStrudel();
  } catch (e) {
    process.stderr.write(
      'validate.mjs: failed to load Strudel (@strudel/core and dependencies). ' +
        `Run "npm install" in scripts/algorave-spike/ and try again.\n` +
        `Original error: ${e && e.message ? e.message : e}\n`,
    );
    process.exitCode = 1;
    return;
  }

  // A missing/corrupt registry is harness breakage (a committed file is gone),
  // not a verdict — same exit-1 path as a broken Strudel install.
  let palette;
  try {
    palette = paletteFor(loadPaletteRegistry(), args.genre);
  } catch (e) {
    process.stderr.write(
      'validate.mjs: failed to load palette.json (the sound registry next to this file). ' +
        `Restore it from git and try again.\nOriginal error: ${e && e.message ? e.message : e}\n`,
    );
    process.exitCode = 1;
    return;
  }
  if (args.genre && !palette.genre) {
    process.stderr.write(
      `validate.mjs: unknown genre ${JSON.stringify(args.genre)} — enforcing the full registry vocabulary\n`,
    );
  }

  let keyPcs = null;
  if (args.key) {
    keyPcs = keyPitchClasses(args.key);
    if (!keyPcs) {
      process.stderr.write(`validate.mjs: ignoring malformed --key value ${JSON.stringify(args.key)}\n`);
    }
  }

  const rawCode = await readStdin();
  const { reason, codeForScreening } = extractReason(rawCode);
  const baseStats = { cyclesChecked: args.cycles };

  if (codeForScreening.trim().length === 0) {
    emit(makeVerdict(false, 'empty input: no code on stdin', reason, baseStats));
    return;
  }

  const bannedTokens = [...new Set([...codeForScreening.matchAll(BANNED_TOKEN_RE)].map((m) => m[1]))].sort();
  if (bannedTokens.length > 0) {
    emit(makeVerdict(false, `code contains disallowed token(s): ${bannedTokens.join(', ')}`, reason, baseStats));
    return;
  }

  let pattern;
  try {
    const result = await transpilerPkg.evaluate(rawCode);
    pattern = result.pattern;
  } catch (e) {
    // "syntax error:" is a deliberately broad label — it covers both a genuine
    // acorn parse failure and a runtime throw (e.g. a hallucinated method
    // name), because both mean the same thing to the caller: this code does
    // not run. It also matches the `invalid_js` bucket in
    // scripts/bench_strudel_mind.py's classify_error(), which greps for the
    // word "syntax" once nothing more specific matches first.
    emit(makeVerdict(false, `syntax error: ${e && e.message ? e.message : String(e)}`, reason, baseStats));
    return;
  }

  if (!pattern || typeof pattern.queryArc !== 'function') {
    emit(
      makeVerdict(
        false,
        `syntax error: expression did not evaluate to a Pattern (got ${typeof pattern})`,
        reason,
        baseStats,
      ),
    );
    return;
  }

  let stats;
  try {
    stats = { ...computeStats(pattern, args.cycles, keyPcs, palette), cyclesChecked: args.cycles };
  } catch (e) {
    emit(
      makeVerdict(
        false,
        `syntax error: querying the pattern threw: ${e && e.message ? e.message : String(e)}`,
        reason,
        baseStats,
      ),
    );
    return;
  }

  if (stats.events === 0) {
    emit(makeVerdict(false, `pattern produced zero events over ${args.cycles} cycle(s)`, reason, stats));
    return;
  }

  if (stats.violations.length > 0 || stats.bankViolations.length > 0) {
    // One error string, "palette violation:" first so the bench keeps
    // bucketing every vocabulary rejection as PALETTE. Sound names lead,
    // bank diagnoses follow — each one coaches (names what DOES exist).
    const parts = [];
    if (stats.violations.length > 0) {
      parts.push(`sound(s) not in the palette — ${stats.violations.join(', ')}`);
    }
    parts.push(...stats.bankViolations);
    emit(makeVerdict(false, `palette violation: ${parts.join('; ')}`, reason, stats));
    return;
  }

  emit(makeVerdict(true, null, reason, stats));
}

function isMain() {
  try {
    return import.meta.url === pathToFileURL(process.argv[1]).href;
  } catch {
    return false;
  }
}

// Guarded so `import { keyPitchClasses, ... } from './validate.mjs'` (the
// in-process unit test) never runs the CLI: it would otherwise block reading
// stdin that no one is going to provide. Everything above this line has no
// side effect on import — no Strudel, no console.log patch, no stdin read.
if (isMain()) {
  await main();
}
