/*
 * validate.mjs tests — spec §8.1.
 *
 * Two layers, deliberately kept apart:
 *
 *   1. CLI contract tests (most of this file): `execFileSync('node',
 *      ['validate.mjs', ...])` with the code piped over stdin, exactly the way
 *      agent/generative/strudel_mind.py's `validate_code()` invokes it. This is
 *      the thing §8.1 actually specifies — stdin in, one JSON line out, exit
 *      code semantics — so it is exercised as a real child process rather than
 *      by calling internals, the same choice test/wav.test.mjs makes for the
 *      recorded artefact.
 *   2. One in-process unit test of the pure scale/out_of_key helpers
 *      (`keyPitchClasses`, `notePitchClass`, `pcName`), imported directly.
 *      These have no @strudel dependency and no side effect on import — see
 *      the `isMain()` guard at the bottom of validate.mjs — so importing them
 *      here does not spawn Strudel or read stdin.
 *
 * No audio, no browser, no network: the validator's whole point is judging
 * Strudel code without ever reaching webaudio (§8.1: "no webaudio, no network,
 * no audio").
 */
import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  DEFAULT_CYCLES,
  keyPitchClasses,
  loadPaletteRegistry,
  notePitchClass,
  paletteFor,
  pcName,
} from '../validate.mjs';

const SPIKE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** Invokes `node validate.mjs [...args]` with `code` on stdin, exactly like
 * agent/generative/strudel_mind.py's `validate_code()` does, and parses the
 * one stdout line as the verdict. Throws (failing the test) if the process
 * exits nonzero — every case in this file is a computed verdict, which §8.1
 * guarantees exits 0; a nonzero exit here means the harness broke, not that a
 * test scenario worked. */
function runValidator(code, args = []) {
  const stdout = execFileSync('node', ['validate.mjs', ...args], {
    cwd: SPIKE_DIR,
    input: code,
    encoding: 'utf8',
  });
  const lines = stdout.split('\n').filter((l) => l.trim().length > 0);
  expect(lines, `expected exactly one stdout line, got: ${JSON.stringify(stdout)}`).toHaveLength(1);
  return JSON.parse(lines[0]);
}

const VALID_STACK = 's("bd*4").bank("RolandTR909")';

describe('validate.mjs CLI — §8.1 verdicts', () => {
  it('1. a valid deep-house stack -> valid:true with stats', () => {
    const code = [
      'stack(',
      '  s("bd*4").bank("RolandTR909").gain(0.92),',
      '  s("[~ oh]*4").bank("RolandTR909").gain(0.55),',
      '  s("~ cp ~ cp").bank("RolandTR909").gain(0.62),',
      '  n("0 2 4 <0 5>").scale("A1:minor").s("sawtooth").gain(0.72)',
      ').mul(gain(0.55))',
    ].join('\n');
    const verdict = runValidator(code, ['--cycles', '4', '--key', 'A:minor']);

    expect(verdict.valid).toBe(true);
    expect(verdict.error).toBeNull();
    expect(verdict.reason).toBeNull();
    expect(verdict.stats.events).toBeGreaterThan(0);
    expect(verdict.stats.cycles_checked).toBe(4);
    expect(verdict.stats.sounds).toEqual(['bd', 'cp', 'oh', 'sawtooth']);
    expect(verdict.stats.kick_four_on_floor).toBe(true);
    // The bass is scale-degrees through A1:minor, so nothing should read as
    // out of key against the A:minor the pattern was actually written for.
    expect(verdict.stats.out_of_key).toEqual([]);
  });

  it('2. a syntax error -> valid:false + error', () => {
    const verdict = runValidator('stack(s("bd*4"', []); // unterminated call
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toMatch(/^syntax error:/);
    expect(verdict.reason).toBeNull();
    // The schema is still the full shape, just at its zero defaults.
    expect(verdict.stats).toEqual({
      events: 0,
      cycles_checked: DEFAULT_CYCLES,
      sounds: [],
      kick_four_on_floor: false,
      out_of_key: [],
    });
  });

  it('3. zero events -> valid:false + error', () => {
    const verdict = runValidator('silence', []);
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toMatch(/zero events/);
    expect(verdict.stats.events).toBe(0);

    // A Pattern that queries clean but has nothing switched on (masked to
    // never fire) is the same verdict for the same reason, not a different
    // bug: both are "evaluated fine, nothing to play".
    const masked = runValidator('s("bd*4").mask("<0>")', []);
    expect(masked.valid).toBe(false);
    expect(masked.error).toMatch(/zero events/);
  });

  it('4. a palette violation (s("gm_epiano1")) -> valid:false + error naming the sound', () => {
    const verdict = runValidator('s("gm_epiano1")', []);
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toContain('gm_epiano1');
    expect(verdict.error).toMatch(/palette/i);
    // Stats still report what was actually seen, even though the gate failed.
    expect(verdict.stats.events).toBeGreaterThan(0);
    expect(verdict.stats.sounds).toEqual(['gm_epiano1']);
  });

  it('5. the token screen rejects import/require/fetch/eval/process -> valid:false + error', () => {
    for (const token of ['import', 'require', 'fetch', 'eval', 'process']) {
      const verdict = runValidator(`${token}("x")`, []);
      expect(verdict.valid, token).toBe(false);
      expect(verdict.error, token).toContain(token);
      expect(verdict.error, token).toMatch(/disallowed token/);
    }
    // Multiple tokens in one input are all named, sorted, deduped.
    const multi = runValidator('eval(fetch(process))', []);
    expect(multi.error).toBe('code contains disallowed token(s): eval, fetch, process');

    // Word-boundary, not substring: text that merely CONTAINS a banned word
    // must not trip the screen. "preprocessedKit" is an unknown bank under
    // the registry, so the rejection it gets must be the PALETTE's, never the
    // token screen's — that difference is exactly the word-boundary proof.
    const notBanned = runValidator('s("bd*4").bank("preprocessedKit")', []);
    expect(notBanned.valid).toBe(false);
    expect(notBanned.error).not.toMatch(/disallowed token/);
    expect(notBanned.error).toMatch(/unknown bank 'preprocessedKit'/);

    // And a registered bank in otherwise-clean code sails through, proving
    // the screen has no substring false positives on real input either.
    const clean = runValidator('s("bd*4").bank("RolandTR909")', []);
    expect(clean.valid).toBe(true);
    expect(clean.error).toBeNull();
  });

  it('6. // reason: is extracted, and its prose is exempt from the token screen', () => {
    const withReason = runValidator('// reason: build tension into the drop\nstack(s("bd*4"))', []);
    expect(withReason.valid).toBe(true);
    expect(withReason.reason).toBe('build tension into the drop');

    // The exemption that actually matters: reason prose that HAPPENS to
    // contain a banned word must not reject otherwise-valid code.
    const reasonWithBannedWord = runValidator(
      '// reason: fetch a darker bassline, then eval how it sits\nstack(s("bd*4"))',
      [],
    );
    expect(reasonWithBannedWord.valid).toBe(true);
    expect(reasonWithBannedWord.reason).toBe('fetch a darker bassline, then eval how it sits');

    // No reason line at all -> null, not "".
    const noReason = runValidator('stack(s("bd*4"))', []);
    expect(noReason.reason).toBeNull();

    // A reason line that is NOT on line 1 does not count (§8.1: "optional
    // FIRST line") — agent/generative/strudel_mind.py's own `_leading_reason`
    // is the documented fallback for this case, not this validator.
    const notFirstLine = runValidator('stack(\n  // reason: too late\n  s("bd*4")\n)', []);
    expect(notFirstLine.valid).toBe(true);
    expect(notFirstLine.reason).toBeNull();
  });

  it('7. --cycles controls how many cycles are queried', () => {
    const two = runValidator(VALID_STACK, ['--cycles', '2']);
    const eight = runValidator(VALID_STACK, ['--cycles', '8']);
    expect(two.stats.cycles_checked).toBe(2);
    expect(eight.stats.cycles_checked).toBe(8);
    // s("bd*4") fires 4 times a cycle regardless of how many cycles are
    // queried, so the count must scale exactly with --cycles.
    expect(two.stats.events).toBe(4 * 2);
    expect(eight.stats.events).toBe(4 * 8);

    // Omitting the flag uses the documented default.
    const omitted = runValidator(VALID_STACK, []);
    expect(omitted.stats.cycles_checked).toBe(DEFAULT_CYCLES);

    // A malformed value degrades to the default rather than crashing the
    // harness — a CLI-usage mistake is not the kind of failure §8.1's
    // exit-code contract is about.
    const malformed = runValidator(VALID_STACK, ['--cycles', 'not-a-number']);
    expect(malformed.stats.cycles_checked).toBe(DEFAULT_CYCLES);
  });

  // ---------------------------------------------------------------------
  // Beyond the required seven: validity rules §8.1 lists explicitly, plus
  // the properties the mind/bench in agent/generative/strudel_mind.py and
  // scripts/bench_strudel_mind.py actually depend on.
  // ---------------------------------------------------------------------

  it('malformed/empty stdin -> valid:false with a precise error, not a crash', () => {
    const empty = runValidator('', []);
    expect(empty.valid).toBe(false);
    expect(empty.error).toMatch(/empty input/);

    const whitespace = runValidator('   \n  \n', []);
    expect(whitespace.valid).toBe(false);
    expect(whitespace.error).toMatch(/empty input/);
  });

  it('a value that is not a Pattern -> valid:false, not a thrown exception', () => {
    const number = runValidator('42', []);
    expect(number.valid).toBe(false);
    expect(number.error).toMatch(/did not evaluate to a Pattern/);

    const str = runValidator("'not mini-notation, not transpiled'", []);
    expect(str.valid).toBe(false);
    expect(str.error).toMatch(/did not evaluate to a Pattern/);
  });

  it('out_of_key lists notes outside --key, sorted and deduped, and never gates valid', () => {
    // c#/cs is outside A natural minor and outside its raised 7th (G#).
    const verdict = runValidator('note("cs4 e4 cs5 a3").s("sawtooth")', ['--key', 'A:minor']);
    expect(verdict.valid).toBe(true); // §8.1: advisory only, never affects valid
    expect(verdict.stats.out_of_key).toEqual(['C#']); // deduped: cs4 and cs5 are one pitch class

    // Without --key there is nothing to compare against.
    const noKey = runValidator('note("cs4 e4").s("sawtooth")', []);
    expect(noKey.stats.out_of_key).toEqual([]);

    // A malformed --key degrades the same way a malformed --cycles does:
    // silently skip the advisory check rather than fail the run.
    const badKey = runValidator('note("cs4 e4").s("sawtooth")', ['--key', 'not-a-real-key']);
    expect(badKey.valid).toBe(true);
    expect(badKey.stats.out_of_key).toEqual([]);
  });

  it('kick_four_on_floor is false when the kick is not on every quarter', () => {
    const notFour = runValidator('s("bd*2")', []); // only 2 hits/cycle: 0, .5
    expect(notFour.valid).toBe(true);
    expect(notFour.stats.kick_four_on_floor).toBe(false);

    const four = runValidator('s("bd*4")', []);
    expect(four.stats.kick_four_on_floor).toBe(true);
  });

  it('exits 0 for every computed verdict, valid or not', () => {
    // execFileSync above already throws on a nonzero exit, so simply
    // reaching an assertion on the parsed verdict for both a valid and an
    // invalid case IS the exit-code proof. Spelled out once here for clarity.
    expect(() => runValidator('s("bd*4")', [])).not.toThrow();
    expect(() => runValidator('s("not-in-the-palette")', [])).not.toThrow();
  });

  it('is deterministic: identical input produces byte-identical stdout', () => {
    const run = () =>
      execFileSync('node', ['validate.mjs', '--cycles', '4', '--key', 'A:minor'], {
        cwd: SPIKE_DIR,
        input: VALID_STACK,
        encoding: 'utf8',
      });
    expect(run()).toBe(run());
  });
});

describe('the palette registry (palette.json) — banks by data, silence gate', () => {
  it('a (sound, bank) pair the matrix lacks is rejected, and the error coaches', () => {
    // The TR909 sample set has no shaker — live, this layer would be SILENT.
    const verdict = runValidator('s("sh*8").bank("RolandTR909")', []);
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toMatch(/palette violation/);
    expect(verdict.error).toContain("'sh' is not in bank RolandTR909");
    // Coaching, not a bare no: the banks that DO carry a shaker are named.
    expect(verdict.error).toContain('RolandTR808');
    expect(verdict.error).toContain('RolandTR727');

    // The same sound through a bank that has it is simply valid.
    const ok = runValidator('s("sh*8").bank("RolandTR808")', []);
    expect(ok.valid).toBe(true);
  });

  it('an unknown bank is rejected, naming the banks that exist', () => {
    const verdict = runValidator('s("bd*4").bank("RolandTR0909")', []); // typo'd
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toContain("unknown bank 'RolandTR0909'");
    expect(verdict.error).toContain('RolandTR909');
  });

  it('.bank() on a synth voice is rejected — it resolves to no sample', () => {
    const verdict = runValidator('note("a3 c4").s("sawtooth").bank("RolandTR909")', []);
    expect(verdict.valid).toBe(false);
    expect(verdict.error).toMatch(/synth voice 'sawtooth' plays silence/);
  });

  it('a patterned bank is checked per event, not per layer', () => {
    // TR727 is Latin percussion only — it has no bd, so alternating the kick
    // into it every other bar is a silent bar 2, and must be caught.
    const bad = runValidator('s("bd*4").bank("<RolandTR909 RolandTR727>")', []);
    expect(bad.valid).toBe(false);
    expect(bad.error).toContain("'bd' is not in bank RolandTR727");

    const good = runValidator('s("bd*4").bank("<RolandTR909 RolandTR808>")', []);
    expect(good.valid).toBe(true);
  });

  it('--genre narrows the vocabulary to that genre; unknown genre falls back whole', () => {
    // "misc" is registry vocabulary but fenced out of the deep entry.
    const bare = runValidator('s("misc*4").bank("EmuSP12")', []);
    expect(bare.valid).toBe(true);

    const fenced = runValidator('s("misc*4").bank("EmuSP12")', ['--genre', 'deep']);
    expect(fenced.valid).toBe(false);
    expect(fenced.error).toContain('misc');

    // An unknown genre degrades like a malformed --key: full vocabulary, no crash.
    const unknown = runValidator(VALID_STACK, ['--genre', 'gabber']);
    expect(unknown.valid).toBe(true);
  });

  it('the widened kit actually plays: toms, ride, shaker and perc in one stack', () => {
    const code = [
      'stack(',
      '  s("bd*4").bank("RolandTR909"),',
      '  s("[~ oh]*4").bank("RolandTR909"),',
      '  s("sh*16").bank("RolandTR727").gain(0.3),',
      '  s("~ ~ ~ [ht mt lt]").bank("RolandTR909").gain(0.5),',
      '  s("rd*4").bank("LinnDrum").gain(0.35),',
      '  s("~ perc ~ ~").bank("RolandTR808").gain(0.4)',
      ')',
    ].join('\n');
    const verdict = runValidator(code, ['--genre', 'deep', '--key', 'A:minor']);
    expect(verdict.valid).toBe(true);
    expect(verdict.stats.sounds).toEqual(['bd', 'ht', 'lt', 'mt', 'oh', 'perc', 'rd', 'sh']);
  });
});

describe('registry file + paletteFor (in-process, no subprocess)', () => {
  const registry = loadPaletteRegistry();

  it('loadPaletteRegistry returns the committed registry with every field', () => {
    for (const field of ['sources', 'drums', 'synths', 'banks', 'genres']) {
      expect(registry).toHaveProperty(field);
    }
    expect(registry.sources.length).toBeGreaterThan(0);
    for (const src of registry.sources) {
      expect(typeof src.json).toBe('string');
      expect(typeof src.base).toBe('string');
    }
  });

  it('the registry is self-consistent — every genre reference resolves', () => {
    // The GENRE_THEMES lesson (tests/test_genre_healing.py): an entry that
    // points at nothing degrades silently in prod, so the pointing is a test.
    const drums = new Set(registry.drums);
    const synths = new Set(registry.synths);
    const bankNames = new Set(Object.keys(registry.banks));
    for (const [genre, entry] of Object.entries(registry.genres)) {
      for (const d of entry.drums) expect(drums.has(d), `${genre}: drum ${d}`).toBe(true);
      for (const s of entry.synths) expect(synths.has(s), `${genre}: synth ${s}`).toBe(true);
      for (const b of entry.banks) expect(bankNames.has(b), `${genre}: bank ${b}`).toBe(true);
    }
    // And every matrix role is lane vocabulary — a row can't smuggle a sound in.
    for (const [bank, roles] of Object.entries(registry.banks)) {
      for (const r of roles) expect(drums.has(r), `${bank}: role ${r}`).toBe(true);
    }
    // The genre the playground page ships with must exist by this exact name.
    expect(registry.genres).toHaveProperty('deep');
  });

  it('paletteFor narrows to a known genre and falls back whole otherwise', () => {
    const deep = paletteFor(registry, 'deep');
    expect(deep.genre).toBe('deep');
    expect(deep.sounds.has('bd')).toBe(true);
    expect(deep.sounds.has('misc')).toBe(false); // fenced out of deep
    expect([...deep.banks.keys()]).toEqual(registry.genres.deep.banks);

    const fallback = paletteFor(registry, 'gabber');
    expect(fallback.genre).toBeNull();
    expect(fallback.sounds.has('misc')).toBe(true);
    expect(fallback.banks.size).toBe(Object.keys(registry.banks).length);

    const none = paletteFor(registry, null);
    expect(none.genre).toBeNull();
    expect(none.sounds.has('bd')).toBe(true);
  });
});

describe('scale / out_of_key helpers (in-process, no subprocess)', () => {
  it('keyPitchClasses("A:minor") is A natural minor plus the raised 7th (G#)', () => {
    // Same convention as agent/generative/scales.py's camelot_scale(): A-side
    // (minor) = natural minor + the harmonic-minor leading tone.
    const pcs = keyPitchClasses('A:minor');
    const names = [...pcs].map(pcName).sort();
    expect(names).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'G#'].sort((a, b) => a.localeCompare(b)));
    // Spelled out: A,B,C,D,E,F,G natural minor, plus G# (raised 7th) — NOT G#
    // twice and NOT a plain A major scale (which would read C# not C, F# not F).
    expect(names).toContain('G#');
    expect(names).not.toContain('C#');
    expect(names).not.toContain('F#');
  });

  it('keyPitchClasses("C:major") is the seven natural pitch classes, no alteration', () => {
    const pcs = keyPitchClasses('C:major');
    expect(pcs.size).toBe(7);
    expect([...pcs].map(pcName).sort()).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G'].sort());
  });

  it('keyPitchClasses rejects anything not in "<letter>[#b]:<minor|major>" form', () => {
    for (const bad of ['A', 'A:', ':minor', 'H:minor', 'A:dorian', '8A', '', null, undefined, 42]) {
      expect(keyPitchClasses(bad), JSON.stringify(bad)).toBeNull();
    }
    // Case and a sharp/flat tonic are both accepted.
    expect(keyPitchClasses('a:minor')).not.toBeNull();
    expect(keyPitchClasses('A#:MINOR')).not.toBeNull();
    expect(keyPitchClasses('Bb:major')).not.toBeNull();
  });

  it('notePitchClass parses letters, both accidental alphabets, and numbers', () => {
    expect(notePitchClass('a3')).toBe(9);
    expect(notePitchClass('A3')).toBe(9); // case-insensitive letter
    expect(notePitchClass('cs4')).toBe(1); // sharp spelled "s" (Strudel's own alphabet)
    expect(notePitchClass('c#4')).toBe(1); // sharp spelled "#"
    expect(notePitchClass('df4')).toBe(1); // flat spelled "f" -> same pitch class as C#
    expect(notePitchClass('bb3')).toBe(10); // leading letter B + flat "b" is NOT ambiguous
    expect(notePitchClass('G1')).toBe(7); // .scale()'s capitalised output shape
    expect(notePitchClass(0)).toBe(0); // note("0 3 7") stays numeric — verified against the real evaluator
    expect(notePitchClass(15)).toBe(3); // wraps mod 12
    expect(notePitchClass(-1)).toBe(11); // negative wraps up, not to a negative index
    expect(notePitchClass('not a note')).toBeNull();
    expect(notePitchClass(undefined)).toBeNull();
  });

  it('pcName is the canonical sharp spelling used throughout, round-tripping notePitchClass', () => {
    expect(pcName(0)).toBe('C');
    expect(pcName(8)).toBe('G#');
    expect(pcName(11)).toBe('B');
    expect(pcName(notePitchClass('df4'))).toBe('C#'); // flat in, canonical sharp out
  });
});
