/*
 * pen.js tests — plan §9.1, "the pen".
 *
 * §9.1 puts the scheduler/diff/ring logic in a pure module precisely so this
 * file can exist: every decision the pen makes is reproduced here without a
 * browser, a clock, an audio context or the /mind server. What is NOT covered
 * here — by the same contract — is the DOM wiring, which is browser-verified
 * the way the playground's was.
 *
 * The scheduler tests do not poke `decide()` at isolated bar numbers and call
 * it a day; they run a `runTicks()` simulation that walks the bar clock the way
 * the page's 250 ms interval does, carrying the same `lastBoundaryBar`
 * bookkeeping. That is the only way the property that matters — *skipped, not
 * queued* — is actually observable, since it is a statement about what happens
 * on the ticks AFTER the missed boundary.
 */
import { describe, expect, it } from 'vitest';

import {
  DEFAULT_PHRASE_BARS,
  INITIAL_PEN,
  MAX_RECENT_REASONS,
  MIN_PHRASE_BARS,
  PEN_HUMAN,
  PEN_MIND,
  WHY,
  barsElapsed,
  decide,
  diffLines,
  mindRequest,
  nextBoundaryBar,
  normalizePhraseBars,
  penHoldsMind,
  pushReason,
  secondsPerBar,
  shouldFire,
  summarizeHumanEdit,
  togglePen,
  truncateLine,
} from '../patterns/pen.js';

// The page's real tempo: 122 BPM, one cycle per bar of 4/4.
const CPS = 122 / 60 / 4; // 0.5083333…

/**
 * Walks bars `0..lastBar` inclusive, one call per bar, exactly as the page's
 * tick does — including storing `at` whenever the decision says `consume`.
 * `hooks.inFlight(bar)` decides whether a request is open at that bar, which is
 * how the in-flight tests hold one across a boundary.
 */
function runTicks(lastBar, { phraseBars = DEFAULT_PHRASE_BARS, pen = PEN_MIND, playing = true, inFlight = () => false } = {}) {
  let lastBoundaryBar = null;
  const fired = [];
  const skipped = [];
  for (let bar = 0; bar <= lastBar; bar++) {
    const d = decide({ barsNow: bar, lastBoundaryBar, phraseBars, inFlight: inFlight(bar), pen, playing });
    if (d.consume) lastBoundaryBar = d.at;
    if (d.fire) fired.push(bar);
    else if (d.why === WHY.IN_FLIGHT) skipped.push(bar);
  }
  return { fired, skipped, lastBoundaryBar };
}

// ---------------------------------------------------------------------------
// The pen token
// ---------------------------------------------------------------------------

describe('the pen token', () => {
  it('starts with the human — loading a page fires no LLM calls', () => {
    expect(INITIAL_PEN).toBe(PEN_HUMAN);
    expect(penHoldsMind(INITIAL_PEN)).toBe(false);
  });

  it('toggles both ways, and anything unrecognised falls back to the mind side being off', () => {
    expect(togglePen(PEN_HUMAN)).toBe(PEN_MIND);
    expect(togglePen(PEN_MIND)).toBe(PEN_HUMAN);
    // A corrupt token must never read as "the mind may edit unattended".
    expect(penHoldsMind(undefined)).toBe(false);
    expect(togglePen('nonsense')).toBe(PEN_MIND);
  });
});

// ---------------------------------------------------------------------------
// Bars from the clock
// ---------------------------------------------------------------------------

describe('bars derivation — floor(elapsed × cps)', () => {
  it('counts one bar per cycle at the page tempo', () => {
    expect(barsElapsed(0, CPS)).toBe(0);
    expect(barsElapsed(1.9, CPS)).toBe(0); // a bar is 1.9672 s
    expect(barsElapsed(1.97, CPS)).toBe(1);
    expect(barsElapsed(3.94, CPS)).toBe(2);
    expect(barsElapsed(60, CPS)).toBe(30);
  });

  it('pins the 8-bar edge near 15.7 s (cps 0.50833)', () => {
    // 8 bars need 8 / 0.50833 = 15.7378 s, so 15.7 s is still SEVEN bars —
    // the boundary lands just after it. Both sides are asserted because this
    // is the arithmetic the whole scheduler hangs off; a rounding change that
    // moved the edge would silently shift every phrase.
    const cps = 0.50833;
    expect(barsElapsed(15.7, cps)).toBe(7);
    expect(barsElapsed(15.73, cps)).toBe(7);
    expect(barsElapsed(15.74, cps)).toBe(8);
    expect(barsElapsed(15.75, cps)).toBe(8);
    // Same edge at the page's exact cps (8 / 0.5083333 = 15.7377 s).
    expect(barsElapsed(15.73, CPS)).toBe(7);
    expect(barsElapsed(15.74, CPS)).toBe(8);
  });

  it('answers 0 for a clock that has not started, rather than NaN', () => {
    expect(barsElapsed(NaN, CPS)).toBe(0);
    expect(barsElapsed(undefined, CPS)).toBe(0);
    expect(barsElapsed(-5, CPS)).toBe(0);
    expect(barsElapsed(30, 0)).toBe(0); // cps before the REPL booted
    expect(barsElapsed(30, NaN)).toBe(0);
  });

  it('reports the bar length and the next boundary for the readout', () => {
    expect(secondsPerBar(CPS)).toBeCloseTo(1.9672, 4);
    expect(secondsPerBar(0)).toBe(Number.POSITIVE_INFINITY);
    expect(nextBoundaryBar(0, 8)).toBe(8);
    expect(nextBoundaryBar(7, 8)).toBe(8);
    expect(nextBoundaryBar(8, 8)).toBe(16); // standing ON a boundary, the next one is ahead
    expect(nextBoundaryBar(11, 8)).toBe(16);
    expect(nextBoundaryBar(3, 2)).toBe(4);
  });

  it('clamps the phrase control instead of trusting the input box', () => {
    expect(normalizePhraseBars(8)).toBe(8);
    expect(normalizePhraseBars('16')).toBe(16);
    expect(normalizePhraseBars(1)).toBe(MIN_PHRASE_BARS);
    expect(normalizePhraseBars(0)).toBe(MIN_PHRASE_BARS);
    expect(normalizePhraseBars(-4)).toBe(MIN_PHRASE_BARS);
    expect(normalizePhraseBars(8.9)).toBe(8);
    expect(normalizePhraseBars('')).toBe(DEFAULT_PHRASE_BARS); // mid-typing
    expect(normalizePhraseBars('abc')).toBe(DEFAULT_PHRASE_BARS);
  });
});

// ---------------------------------------------------------------------------
// The scheduler
// ---------------------------------------------------------------------------

describe('the phrase scheduler — when the mind gets to speak', () => {
  it('fires at every phrase boundary and at no bar between them', () => {
    const { fired } = runTicks(40, { phraseBars: 8 });
    expect(fired).toEqual([8, 16, 24, 32, 40]);
    // bar 0 is not a boundary: handing the pen over on a fresh page waits a phrase
    expect(fired).not.toContain(0);
  });

  it('honours a changed phrase length', () => {
    expect(runTicks(12, { phraseBars: 2 }).fired).toEqual([2, 4, 6, 8, 10, 12]);
    expect(runTicks(48, { phraseBars: 16 }).fired).toEqual([16, 32, 48]);
  });

  it('fires once per boundary however many ticks land inside that bar', () => {
    // The page ticks ~8× per bar at 250 ms; the bar number does not change
    // between those ticks, and only the first of them may fire.
    let lastBoundaryBar = null;
    const decisions = [];
    for (let tick = 0; tick < 8; tick++) {
      const d = decide({ barsNow: 8, lastBoundaryBar, phraseBars: 8, inFlight: false, pen: PEN_MIND, playing: true });
      if (d.consume) lastBoundaryBar = d.at;
      decisions.push(d);
    }
    expect(decisions.filter((d) => d.fire)).toHaveLength(1);
    expect(decisions[0].fire).toBe(true);
    expect(decisions[1].why).toBe(WHY.HANDLED);
    expect(decisions.at(-1).why).toBe(WHY.HANDLED);
  });

  it('never fires while the human holds the pen', () => {
    const { fired } = runTicks(40, { phraseBars: 8, pen: PEN_HUMAN });
    expect(fired).toEqual([]);
    const d = decide({ barsNow: 8, lastBoundaryBar: null, phraseBars: 8, inFlight: false, pen: PEN_HUMAN, playing: true });
    expect(d).toMatchObject({ fire: false, at: 8, why: WHY.HUMAN, consume: false });
  });

  it('never fires while stopped', () => {
    expect(runTicks(40, { phraseBars: 8, playing: false }).fired).toEqual([]);
    const d = decide({ barsNow: 16, lastBoundaryBar: null, phraseBars: 8, inFlight: false, pen: PEN_MIND, playing: false });
    expect(d).toMatchObject({ fire: false, at: 16, why: WHY.STOPPED, consume: false });
  });

  it('never fires while a request is already in flight', () => {
    const d = decide({ barsNow: 8, lastBoundaryBar: null, phraseBars: 8, inFlight: true, pen: PEN_MIND, playing: true });
    expect(d).toMatchObject({ fire: false, at: 8, why: WHY.IN_FLIGHT });
    expect(shouldFire({ barsNow: 8, lastBoundaryBar: null, phraseBars: 8, inFlight: true, pen: PEN_MIND, playing: true })).toBe(false);
  });

  it('SKIPS a boundary reached in flight — it is never queued for later', () => {
    // A slow request opened at bar 8 and still open through bar 12: the bar-16
    // boundary is missed. What must NOT happen is a call at bar 17 (or 13, or
    // the moment the request lands) — the next one is due at bar 24.
    const { fired, skipped } = runTicks(32, {
      phraseBars: 8,
      inFlight: (bar) => bar >= 16 && bar <= 19,
    });
    expect(skipped).toEqual([16]);
    expect(fired).toEqual([8, 24, 32]);
    expect(fired).not.toContain(16);
    expect(fired).not.toContain(20); // the bar the request landed on
  });

  it('burns the skipped boundary so a later tick in the SAME bar cannot fire it', () => {
    // The request lands mid-bar-16. Ticks 0-3 of that bar are in flight, ticks
    // 4-7 are not — and none of them may fire, because bar 16 was consumed.
    let lastBoundaryBar = 8;
    const fired = [];
    for (let tick = 0; tick < 8; tick++) {
      const d = decide({
        barsNow: 16,
        lastBoundaryBar,
        phraseBars: 8,
        inFlight: tick < 4,
        pen: PEN_MIND,
        playing: true,
      });
      if (d.consume) lastBoundaryBar = d.at;
      if (d.fire) fired.push(tick);
    }
    expect(fired).toEqual([]);
    expect(lastBoundaryBar).toBe(16);
  });

  it('does not consume boundaries that pass while the human holds the pen', () => {
    // Bar 8 goes by with the human editing; the pen comes back at bar 9.
    // Nothing was scheduled at 8, so nothing was skipped — and 16 is next.
    let lastBoundaryBar = null;
    let pen = PEN_HUMAN;
    const fired = [];
    for (let bar = 0; bar <= 24; bar++) {
      if (bar === 9) pen = PEN_MIND;
      const d = decide({ barsNow: bar, lastBoundaryBar, phraseBars: 8, inFlight: false, pen, playing: true });
      if (d.consume) lastBoundaryBar = d.at;
      if (d.fire) fired.push(bar);
    }
    expect(fired).toEqual([16, 24]);
  });

  it('reports why it stayed quiet between boundaries', () => {
    const d = decide({ barsNow: 11, lastBoundaryBar: 8, phraseBars: 8, inFlight: false, pen: PEN_MIND, playing: true });
    expect(d).toEqual({ fire: false, at: null, why: WHY.BETWEEN, consume: false });
  });
});

// ---------------------------------------------------------------------------
// Human edits as state
// ---------------------------------------------------------------------------

const SEED = [
  'stack(',
  '  s("bd*4").bank("RolandTR909").gain(0.92),',
  '  s("[~ oh]*4").bank("RolandTR909").gain(0.55),',
  '  s("~ cp ~ cp").bank("RolandTR909").gain(0.62)',
  ').mul(gain(0.55))',
].join('\n');

describe('the human-edit summarizer', () => {
  it('returns null when the buffer did not change', () => {
    expect(summarizeHumanEdit(SEED, SEED)).toBeNull();
    expect(summarizeHumanEdit('', '')).toBeNull();
    expect(summarizeHumanEdit(undefined, '')).toBeNull();
  });

  it('summarises an in-place edit as ±0 lines plus the line as it now reads', () => {
    // The NEW text, not the old: an LCS diff emits the `del` of a changed line
    // before its `add`, and "gain(0.92)" is precisely the thing that is no
    // longer true. Nudging one gain is the commonest human edit there is.
    const after = SEED.replace('gain(0.92)', 'gain(0.70)');
    expect(summarizeHumanEdit(SEED, after)).toBe(
      'human: ±0 lines — "s("bd*4").bank("RolandTR909").gain(0.70),"',
    );
  });

  it('counts added lines with a + and quotes the first one', () => {
    const after = SEED.replace(
      ').mul(gain(0.55))',
      '  s("hh*16").bank("RolandTR909").gain(0.4)\n).mul(gain(0.55))',
    );
    const summary = summarizeHumanEdit(SEED, after);
    expect(summary).toMatch(/^human: \+1 line — "/);
    expect(summary).toContain('hh*16');
  });

  it('counts removed lines with a -', () => {
    const after = SEED.split('\n').filter((l) => !l.includes('cp')).join('\n')
      .replace('gain(0.55),', 'gain(0.55)');
    const summary = summarizeHumanEdit(SEED, after);
    expect(summary).toMatch(/^human: -1 line — "/);
  });

  it('pluralises, and nets adds against removes', () => {
    const after = `${SEED}\n// one\n// two\n// three`;
    expect(summarizeHumanEdit(SEED, after)).toMatch(/^human: \+3 lines — /);
    expect(summarizeHumanEdit(after, SEED)).toMatch(/^human: -3 lines — /);
  });

  it('truncates a long first line, ellipsis inside the budget', () => {
    const long = `  n("0 2 4 7 9 11 12 14").scale("A1:minor").s("sawtooth").lpf(800).lpq(6).gain(0.72),`;
    const after = SEED.replace('  s("[~ oh]*4").bank("RolandTR909").gain(0.55),', long);
    const summary = summarizeHumanEdit(SEED, after);
    const quoted = summary.slice(summary.indexOf('"') + 1, summary.lastIndexOf('"'));
    expect(quoted).toHaveLength(60);
    expect(quoted.endsWith('…')).toBe(true);
    expect(long.trim().startsWith(quoted.slice(0, -1))).toBe(true);
  });

  it('respects a custom truncation budget', () => {
    const after = SEED.replace('gain(0.92)', 'gain(0.70)');
    expect(summarizeHumanEdit(SEED, after, { max: 12 })).toBe('human: ±0 lines — "s("bd*4").b…"');
  });

  it('quotes a real line when the first change is a blank one', () => {
    const after = SEED.replace('stack(', 'stack(\n');
    const summary = summarizeHumanEdit(SEED, after);
    expect(summary).toMatch(/^human: \+1 line — /);
    expect(summary).not.toContain('""');
  });

  it('is built on the same line diff the page renders', () => {
    const rows = diffLines('a\nb', 'a\nc');
    expect(rows.map((r) => r.type)).toEqual(['same', 'del', 'add']);
    expect(rows.map((r) => r.text)).toEqual(['a', 'b', 'c']);
    expect(diffLines('x', 'x').every((r) => r.type === 'same')).toBe(true);
  });

  it('truncateLine trims first, then cuts', () => {
    expect(truncateLine('   padded   ', 60)).toBe('padded');
    expect(truncateLine('abcdef', 4)).toBe('abc…');
    expect(truncateLine('abc', 4)).toBe('abc');
  });
});

// ---------------------------------------------------------------------------
// The ring
// ---------------------------------------------------------------------------

describe('the recent-reasons ring', () => {
  it('keeps the last 5, FIFO', () => {
    expect(MAX_RECENT_REASONS).toBe(5);
    let ring = [];
    for (let i = 1; i <= 7; i++) ring = pushReason(ring, `reason ${i}`);
    expect(ring).toEqual(['reason 3', 'reason 4', 'reason 5', 'reason 6', 'reason 7']);
    expect(ring).toHaveLength(MAX_RECENT_REASONS);
  });

  it('does not mutate the array it was given', () => {
    const before = ['one'];
    const after = pushReason(before, 'two');
    expect(before).toEqual(['one']);
    expect(after).toEqual(['one', 'two']);
  });

  it('drops empty reasons — a mutation with nothing to say adds nothing', () => {
    expect(pushReason(['one'], '')).toEqual(['one']);
    expect(pushReason(['one'], '   ')).toEqual(['one']);
    expect(pushReason(['one'], null)).toEqual(['one']);
    expect(pushReason(['one'], ' trimmed ')).toEqual(['one', 'trimmed']);
  });

  it('mixes mind reasons and human summaries in one ring, in order', () => {
    let ring = pushReason([], 'opened the bass filter');
    ring = pushReason(ring, 'human: ±0 lines — "gain(0.70)"');
    ring = pushReason(ring, 'dropped the stabs for a bar');
    expect(ring).toEqual([
      'opened the bass filter',
      'human: ±0 lines — "gain(0.70)"',
      'dropped the stabs for a bar',
    ]);
  });
});

// ---------------------------------------------------------------------------
// The request body
// ---------------------------------------------------------------------------

describe('mindRequest — the body both paths send', () => {
  it('is snake_case for the Python parser and trims the ring to the cap', () => {
    const body = mindRequest({
      code: 's("bd*4")',
      intent: '  darker  ',
      genre: 'deep',
      key: 'A:minor',
      barsElapsed: 24,
      recentReasons: ['a', 'b', 'c', 'd', 'e', 'f'],
    });
    expect(body).toEqual({
      code: 's("bd*4")',
      intent: 'darker',
      genre: 'deep',
      key: 'A:minor',
      bars_elapsed: 24,
      recent_reasons: ['b', 'c', 'd', 'e', 'f'],
    });
  });

  it('sends a non-negative integer bar count whatever the clock said', () => {
    expect(mindRequest({ barsElapsed: -3 }).bars_elapsed).toBe(0);
    expect(mindRequest({ barsElapsed: NaN }).bars_elapsed).toBe(0);
    expect(mindRequest({ barsElapsed: 7.9 }).bars_elapsed).toBe(7);
    expect(mindRequest({}).recent_reasons).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// The handoff — the sequence §9.1 exists for
// ---------------------------------------------------------------------------

describe('handoff: the human edits, hands over, and the mind answers THAT code', () => {
  it('carries the human buffer and the human: reason into the first scheduled call', () => {
    // 1. The human is holding the pen and edits the buffer.
    let pen = PEN_HUMAN;
    let ring = ['opened with the seed groove'];
    let lastEvaluated = SEED;

    const edited = SEED
      .replace('gain(0.92)', 'gain(0.99)')
      .replace(').mul(gain(0.55))', '  s("hh*16").bank("RolandTR909").gain(0.42)\n).mul(gain(0.55))');

    // 2. They evaluate it. The summary is mechanical — nobody typed it.
    const summary = summarizeHumanEdit(lastEvaluated, edited);
    expect(summary).not.toBeNull();
    expect(summary.startsWith('human: ')).toBe(true);
    ring = pushReason(ring, summary);
    lastEvaluated = edited;

    // Nothing is scheduled while they hold it, boundary or not.
    expect(shouldFire({ barsNow: 8, lastBoundaryBar: null, phraseBars: 8, inFlight: false, pen, playing: true })).toBe(false);

    // 3. They hand the pen to the mind mid-phrase (bar 11).
    pen = togglePen(pen);
    expect(pen).toBe(PEN_MIND);
    expect(shouldFire({ barsNow: 11, lastBoundaryBar: null, phraseBars: 8, inFlight: false, pen, playing: true })).toBe(false);

    // 4. The next boundary is the first scheduled call.
    const at = nextBoundaryBar(11, 8);
    expect(at).toBe(16);
    const decision = decide({ barsNow: at, lastBoundaryBar: null, phraseBars: 8, inFlight: false, pen, playing: true });
    expect(decision.fire).toBe(true);

    // 5. And it carries the human's code plus the human's summary — this is
    //    the whole of §9.1's "handoff is free": same call, different author.
    const body = mindRequest({
      code: lastEvaluated,
      intent: 'build to a peak',
      genre: 'deep',
      key: 'A:minor',
      barsElapsed: decision.at,
      recentReasons: ring,
    });
    expect(body.code).toBe(edited);
    expect(body.code).toContain('gain(0.99)');
    expect(body.bars_elapsed).toBe(16);
    expect(body.recent_reasons.at(-1)).toBe(summary);
    expect(body.recent_reasons.at(-1)).toMatch(/^human: \+1 line — /);
    expect(body.recent_reasons).toContain('opened with the seed groove');
  });

  it('handing over ON a boundary waits for the next one, not this one', () => {
    // The page consumes the current bar when the pen changes hands
    // (`lastBoundaryBar = currentBars()`), so the mind always comes in at the
    // top of the next phrase. Without it, a handoff at bar 8 fires inside bar
    // 8 — musically harmless, but it contradicts what the page just announced.
    const handedOverAt = 8;
    const onHandover = { phraseBars: 8, inFlight: false, pen: PEN_MIND, playing: true };
    expect(decide({ barsNow: 8, lastBoundaryBar: handedOverAt, ...onHandover }).fire).toBe(false);
    expect(decide({ barsNow: 12, lastBoundaryBar: handedOverAt, ...onHandover }).fire).toBe(false);
    expect(decide({ barsNow: 16, lastBoundaryBar: handedOverAt, ...onHandover }).fire).toBe(true);
    // Handing over mid-phrase consumes a bar that is not a boundary, which
    // must not swallow the boundary that follows it.
    expect(decide({ barsNow: 16, lastBoundaryBar: 11, ...onHandover }).fire).toBe(true);
  });

  it('taking the pen back mid-phrase silences the scheduler from the next tick', () => {
    let pen = PEN_MIND;
    let lastBoundaryBar = null;
    const fired = [];
    for (let bar = 0; bar <= 32; bar++) {
      if (bar === 17) pen = togglePen(pen); // the human grabs the code
      const d = decide({ barsNow: bar, lastBoundaryBar, phraseBars: 8, inFlight: false, pen, playing: true });
      if (d.consume) lastBoundaryBar = d.at;
      if (d.fire) fired.push(bar);
    }
    expect(fired).toEqual([8, 16]); // 24 and 32 never happen
    expect(pen).toBe(PEN_HUMAN);
  });
});
