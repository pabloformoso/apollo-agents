/*
 * Deterministic pattern tests — spec §5.1.
 *
 * No audio, no DOM, no network. Everything here is `queryArc` against the pure
 * module, so this suite is a CI candidate as-is.
 *
 * Assertions are written against the event shape VERIFIED on the pinned
 * packages (@strudel/core 1.2.6, @strudel/mini 1.2.6, @strudel/tonal 1.2.6),
 * not against what the docs imply:
 *   - hap.value is a plain object, e.g. {s:'bd', bank:'RolandTR909', gain:0.92}
 *   - .lpf() writes `cutoff`, .lpq() writes `resonance`
 *   - .note() values stay STRINGS ('a3'); .scale() emits capitalised names ('A1')
 *   - hap.whole.begin is a Fraction -> .valueOf() for a number
 */
import { describe, expect, it } from 'vitest';
import { pattern, roles, description, BPM, CPS, BARS, MASTER_TRIM } from '../patterns/deephouse.js';

const onsets = (pat, from, to) => pat.queryArc(from, to).filter((h) => h.hasOnset());
const begins = (pat, from, to) => onsets(pat, from, to).map((h) => h.whole.begin.valueOf());
/** Onset positions inside one bar, sorted, deduped, rounded away from float noise. */
const positionsInBar = (pat, bar) =>
  [...new Set(begins(pat, bar, bar + 1).map((t) => Number((t - bar).toFixed(6))))].sort((a, b) => a - b);

// A natural minor. Everything the bass and the chords play must live in here.
const A_MINOR = new Set(['A', 'B', 'C', 'D', 'E', 'F', 'G']);
const pitchClass = (noteName) => {
  const m = String(noteName).match(/^([a-gA-G])([#bs]*)(-?\d+)?$/);
  expect(m, `unparseable note name: ${noteName}`).not.toBeNull();
  expect(m[2], `unexpected accidental in ${noteName} — A natural minor has none`).toBe('');
  return m[1].toUpperCase();
};

describe('deephouse pattern module', () => {
  it('imports purely — no browser globals were needed', () => {
    // The module is loaded by the import at the top of this file. If it had
    // reached for an AudioContext or the DOM, that import would have thrown.
    expect(typeof globalThis.window).toBe('undefined');
    expect(typeof globalThis.AudioContext).toBe('undefined');
    expect(pattern).toBeDefined();
    expect(typeof pattern.queryArc).toBe('function');
  });

  it('describes itself as 122 BPM / A minor / 16 bars', () => {
    expect(BPM).toBe(122);
    expect(BARS).toBe(16);
    expect(CPS).toBeCloseTo(122 / 60 / 4, 12);
    expect(description.bpm).toBe(122);
    expect(description.key).toBe('A minor');
    expect(description.camelot).toBe('8A');
    expect(description.bars).toBe(16);
    expect(description.chords).toEqual(['Am7', 'Fmaj7']);
    // 16 bars at 122 BPM is comfortably longer than the 30 s deliverable.
    expect(BARS / CPS).toBeGreaterThan(30);
    expect(BARS / CPS).toBeLessThan(33);
  });

  it('the description is plain data, not code', () => {
    expect(JSON.parse(JSON.stringify(description))).toEqual(description);
    expect(description.roles.map((r) => r.name)).toEqual(Object.keys(roles));
    for (const r of description.roles) {
      expect(r.fromBar).toBeGreaterThanOrEqual(0);
      expect(r.toBar).toBeLessThanOrEqual(BARS);
      expect(r.toBar).toBeGreaterThan(r.fromBar);
    }
    const names = description.sections.map((s) => s.name);
    expect(names).toEqual(['intro', 'groove', 'lift', 'peak']);
    // Sections tile [0,16) with no gap and no overlap.
    let cursor = 0;
    for (const sec of description.sections) {
      expect(sec.fromBar).toBe(cursor);
      cursor = sec.toBar;
    }
    expect(cursor).toBe(BARS);
  });

  it('produces events for queryArc(0,1) and queryArc(0,16)', () => {
    expect(onsets(pattern, 0, 1).length).toBeGreaterThan(0);
    const long = onsets(pattern, 0, BARS);
    expect(long.length).toBeGreaterThan(500);
    for (const hap of long) {
      expect(typeof hap.value).toBe('object');
      expect(hap.value).not.toBeNull();
      // Every event must carry a sound, or superdough has nothing to trigger.
      expect(typeof hap.value.s).toBe('string');
    }
  });

  it('kick is four-on-the-floor in every one of the 16 bars', () => {
    for (let bar = 0; bar < BARS; bar++) {
      expect(positionsInBar(roles.kick, bar), `bar ${bar}`).toEqual([0, 0.25, 0.5, 0.75]);
    }
    const v = onsets(roles.kick, 0, 1)[0].value;
    expect(v.s).toBe('bd');
    expect(v.bank).toBe('RolandTR909');
  });

  it('open hats are on the offbeat 8ths — the deep house signature', () => {
    for (let bar = 0; bar < BARS; bar++) {
      expect(positionsInBar(roles.openHat, bar), `bar ${bar}`).toEqual([0.125, 0.375, 0.625, 0.875]);
    }
    expect(onsets(roles.openHat, 0, 1)[0].value.s).toBe('oh');
  });

  it('closed hats are quiet swung 16ths with gain variation', () => {
    const bar0 = onsets(roles.closedHat, 0, 1);
    expect(bar0).toHaveLength(16);
    expect(bar0.every((h) => h.value.s === 'hh')).toBe(true);

    // Exact (unrounded) onset positions, so the swing offset survives the check.
    const pos = begins(roles.closedHat, 0, 1).sort((a, b) => a - b);
    expect(pos).toHaveLength(16);
    // The on-8th hats stay exactly on the grid...
    const onGrid = pos.filter((p) => Math.abs(p * 8 - Math.round(p * 8)) < 1e-12);
    expect(onGrid).toEqual([0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]);
    // ...and the off-16ths are pushed late by exactly swingBy(1/8, 8) = 1/128 bar.
    const swung = pos.filter((p) => !onGrid.includes(p));
    expect(swung).toHaveLength(8);
    for (const p of swung) {
      const grid = Math.round((p - 1 / 128) * 16) / 16;
      expect(p - grid).toBeCloseTo(1 / 128, 12);
    }

    // Quiet, and not all the same — velocity variation is part of the spec.
    const gains = bar0.map((h) => h.value.gain);
    expect(Math.max(...gains)).toBeLessThan(0.4);
    expect(new Set(gains.map((g) => g.toFixed(4))).size).toBeGreaterThan(1);
  });

  it('clap sits on beats 2 and 4 and enters at bar 4', () => {
    for (let bar = 0; bar < 4; bar++) {
      expect(onsets(roles.clap, bar, bar + 1), `bar ${bar}`).toHaveLength(0);
    }
    for (let bar = 4; bar < BARS; bar++) {
      expect(positionsInBar(roles.clap, bar), `bar ${bar}`).toEqual([0.25, 0.75]);
    }
    const v = onsets(roles.clap, 4, 5)[0].value;
    expect(v.s).toBe('cp');
    expect(v.bank).toBe('RolandTR909');
    // Low in the mix relative to the kick.
    expect(v.gain).toBeLessThan(onsets(roles.kick, 4, 5)[0].value.gain);
  });

  it('bass is a rolling syncopated line, always inside A natural minor', () => {
    for (let bar = 0; bar < BARS; bar++) {
      const pos = positionsInBar(roles.bass, bar);
      expect(pos.length, `bar ${bar}`).toBe(9);
      // Syncopation: more than half the onsets are off the 8th-note grid.
      const offGrid = pos.filter((p) => Math.abs(p * 8 - Math.round(p * 8)) > 1e-9);
      expect(offGrid.length, `bar ${bar}`).toBeGreaterThanOrEqual(4);
    }
    const all = onsets(roles.bass, 0, BARS);
    const classes = new Set();
    for (const h of all) {
      expect(h.value.s).toBe('sawtooth');
      const pc = pitchClass(h.value.note);
      expect(A_MINOR.has(pc), `${h.value.note} is outside A natural minor`).toBe(true);
      classes.add(pc);
    }
    // Roots move A -> F with the chords.
    expect([...classes].sort()).toEqual(['A', 'F']);
    // Octave movement is in the spec.
    const octaves = new Set(all.map((h) => h.value.note.slice(-1)));
    expect(octaves.size).toBeGreaterThan(1);
  });

  it('bass filter is inside 400-800 Hz and opens at bar 8', () => {
    const cutoffAt = (bar) => {
      const cs = [...new Set(onsets(roles.bass, bar, bar + 1).map((h) => h.value.cutoff))];
      expect(cs, `bar ${bar} should hold one cutoff`).toHaveLength(1);
      return cs[0];
    };
    for (let bar = 0; bar < BARS; bar++) {
      const c = cutoffAt(bar);
      expect(c).toBeGreaterThanOrEqual(400);
      expect(c).toBeLessThanOrEqual(800);
    }
    expect(cutoffAt(3)).toBe(400);
    expect(cutoffAt(7)).toBe(400);
    expect(cutoffAt(8)).toBeGreaterThan(cutoffAt(7)); // the lift
    expect(cutoffAt(12)).toBeGreaterThan(cutoffAt(8)); // and again into the peak
    expect(onsets(roles.bass, 0, 1)[0].value.resonance).toBeGreaterThan(0);
  });

  it('hat energy rises across the arrangement', () => {
    const peakGain = (bar) => Math.max(...onsets(roles.closedHat, bar, bar + 1).map((h) => h.value.gain));
    expect(peakGain(5)).toBeGreaterThan(peakGain(1));
    expect(peakGain(9)).toBeGreaterThan(peakGain(5));
    expect(peakGain(13)).toBeGreaterThan(peakGain(9));
  });

  it('section map is honoured: stabs are absent before bar 4 and present after', () => {
    for (let bar = 0; bar < 4; bar++) {
      expect(onsets(roles.stabs, bar, bar + 1), `bar ${bar}`).toHaveLength(0);
    }
    for (let bar = 4; bar < BARS; bar++) {
      expect(onsets(roles.stabs, bar, bar + 1).length, `bar ${bar}`).toBe(8);
    }
    // ...and the same holds when queried through the full stack, not just the role.
    const stabSounds = (bar) =>
      onsets(pattern, bar, bar + 1).filter((h) => h.value.s === 'triangle').length;
    expect(stabSounds(3)).toBe(0);
    expect(stabSounds(4)).toBe(8);

    // Every role's declared window matches what it actually plays.
    for (const r of description.roles) {
      const pat = roles[r.name];
      for (let bar = 0; bar < BARS; bar++) {
        const played = onsets(pat, bar, bar + 1).length;
        const inWindow = bar >= r.fromBar && bar < r.toBar;
        expect(played > 0, `${r.name} bar ${bar}`).toBe(inWindow);
        if (inWindow) expect(played, `${r.name} bar ${bar}`).toBe(r.onsetsPerBar);
      }
    }
  });

  it('stabs are Am7 then Fmaj7, offbeat, with delay and reverb', () => {
    const bar4 = onsets(roles.stabs, 4, 5);
    expect(positionsInBar(roles.stabs, 4)).toEqual([0.375, 0.875]);
    const chord = [...new Set(bar4.map((h) => pitchClass(h.value.note)))].sort();
    expect(chord).toEqual(['A', 'C', 'E', 'G']); // Am7
    const bar5 = onsets(roles.stabs, 5, 6);
    expect([...new Set(bar5.map((h) => pitchClass(h.value.note)))].sort()).toEqual(['A', 'C', 'E', 'F']); // Fmaj7
    for (const h of [...bar4, ...bar5]) {
      expect(A_MINOR.has(pitchClass(h.value.note))).toBe(true);
      expect(h.value.delay).toBeGreaterThan(0);
      expect(h.value.room).toBeGreaterThan(0);
    }
    // On their own effect bus, so the delay tail does not smear the drums.
    expect(bar4[0].value.orbit).not.toBe(onsets(roles.kick, 4, 5)[0].value.orbit ?? 0);
  });

  it('the fill only fires in the last bar', () => {
    for (let bar = 0; bar < 15; bar++) {
      expect(onsets(roles.fill, bar, bar + 1), `bar ${bar}`).toHaveLength(0);
    }
    const last = onsets(roles.fill, 15, 16);
    expect(last).toHaveLength(8);
    expect(last.every((h) => h.value.s === 'sd')).toBe(true);
    // Rising roll.
    const gains = last.map((h) => h.value.gain);
    expect(gains[gains.length - 1]).toBeGreaterThan(gains[0]);
  });

  it('every layer is present in the final bar', () => {
    const sounds = new Set(onsets(pattern, 15, 16).map((h) => h.value.s));
    expect([...sounds].sort()).toEqual(['bd', 'cp', 'hh', 'oh', 'sawtooth', 'sd', 'triangle']);
  });

  it('no event asks for a gain that would clip on its own', () => {
    for (const h of onsets(pattern, 0, BARS)) {
      if (h.value.gain != null) {
        expect(h.value.gain).toBeGreaterThan(0);
        expect(h.value.gain).toBeLessThanOrEqual(1);
      }
    }
  });

  it('the master trim scales gains without flattening them', () => {
    expect(MASTER_TRIM).toBeGreaterThan(0);
    expect(MASTER_TRIM).toBeLessThanOrEqual(1);
    // `.mul(gain(x))` must MULTIPLY. A plain `.gain(x)` would overwrite every
    // event with the same number and silently kill the hat accents and the fill's
    // ramp — the sound of that mistake is a flat, lifeless loop.
    const inStack = onsets(pattern, 15, 16);
    const bare = [...onsets(roles.kick, 15, 16), ...onsets(roles.closedHat, 15, 16)];
    for (const h of bare) {
      const match = inStack.find(
        (x) => x.value.s === h.value.s && x.whole.begin.equals(h.whole.begin),
      );
      expect(match, `${h.value.s} at ${h.whole.begin.valueOf()}`).toBeDefined();
      expect(match.value.gain).toBeCloseTo(h.value.gain * MASTER_TRIM, 10);
    }
    // Variation survives the trim.
    expect(new Set(inStack.map((h) => h.value.gain?.toFixed(6))).size).toBeGreaterThan(3);
  });

  it('is deterministic — two queries of the same arc are identical', () => {
    const shape = (pat, from, to) =>
      onsets(pat, from, to)
        .map((h) => `${h.whole.begin.valueOf()}|${h.whole.end.valueOf()}|${JSON.stringify(h.value)}`)
        .sort();
    for (const [from, to] of [[0, 1], [0, 16], [12, 16]]) {
      const a = shape(pattern, from, to);
      const b = shape(pattern, from, to);
      expect(a).toEqual(b);
      expect(a.length).toBeGreaterThan(0);
    }
    // The loop really loops: bar 4 and bar 6 are the same musical position
    // in the 2-bar harmonic cycle and both sit in the same section.
    const rel = (bar) =>
      shape(pattern, bar, bar + 1).map((line) => {
        const [begin, end, value] = line.split('|');
        return `${Number(begin) - bar}|${Number(end) - bar}|${value}`;
      });
    expect(rel(4)).toEqual(rel(6));
  });
});
