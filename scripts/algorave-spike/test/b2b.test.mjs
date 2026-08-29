/*
 * b2b.test.mjs — the alternation scheduler (plan §9.2, iteration 3).
 *
 * Separate from pen.test.mjs because it tests a different claim. That file
 * asks "when may the mind speak"; this one asks "whose turn is it", and the
 * interesting half of the answer is what happens when those two questions land
 * on the SAME bar — which is a property of the two functions composed, not of
 * either one.
 *
 * So the tests here do not stop at poking `b2bDecide()`: the composition tests
 * run both schedulers in the order the page runs them (flip first, then the
 * phrase decision, with §9.1's handoff consuming the bar in between) and assert
 * on the whole timeline. That order IS the contract's "the flip wins, the
 * mind's first fire is its next boundary" — asserting it anywhere else would be
 * asserting a comment.
 */
import { describe, expect, it } from 'vitest';

import {
  B2B_WHY,
  DEFAULT_B2B_BARS,
  DEFAULT_PHRASE_BARS,
  INITIAL_MODE,
  MIN_B2B_BARS,
  MODE_B2B,
  MODE_FREE,
  PEN_HUMAN,
  PEN_MIND,
  WHY,
  b2bDecide,
  barsUntilFlip,
  decide,
  mindRequest,
  modeIsB2b,
  nextFlipBar,
  normalizeB2bBars,
  shouldFlip,
  toggleMode,
  togglePen,
} from '../patterns/pen.js';

/**
 * Walks bars `0..lastBar`, one call per bar, carrying `lastFlipBar` exactly as
 * the page's tick does. `hooks.mode(bar)` / `hooks.playing(bar)` let a test
 * arm B2B or stop the audio partway through, which is the only way to observe
 * that a boundary passed in `free` is NOT consumed.
 */
function runFlips(lastBar, {
  b2bBars = DEFAULT_B2B_BARS,
  mode = () => MODE_B2B,
  playing = () => true,
  startPen = PEN_HUMAN,
} = {}) {
  let lastFlipBar = null;
  let pen = startPen;
  const flips = [];
  for (let bar = 0; bar <= lastBar; bar++) {
    const d = b2bDecide({
      barsNow: bar,
      lastFlipBar,
      b2bBars,
      mode: mode(bar),
      playing: playing(bar),
      pen,
    });
    if (d.consume) lastFlipBar = d.at;
    if (d.flip) {
      pen = d.to;
      flips.push({ bar, to: d.to });
    }
  }
  return { flips, bars: flips.map((f) => f.bar), pen, lastFlipBar };
}

/**
 * Both schedulers, in the page's order, over `0..lastBar`.
 *
 * This is `playground.html`'s tick with the DOM taken out: the B2B decision
 * runs FIRST, a flip goes through §9.1's handoff (which consumes the current
 * bar when the pen lands on the mind), and only then does the phrase scheduler
 * get to look at the same bar. Returns the timeline of both.
 */
function runJam(lastBar, {
  b2bBars = 4,
  phraseBars = 2,
  mode = MODE_B2B,
  playing = true,
  startPen = PEN_HUMAN,
} = {}) {
  let pen = startPen;
  let lastFlipBar = null;
  let lastBoundaryBar = null;
  const flips = [];
  const fires = [];

  for (let bar = 0; bar <= lastBar; bar++) {
    const flip = b2bDecide({ barsNow: bar, lastFlipBar, b2bBars, mode, playing, pen });
    if (flip.consume) lastFlipBar = flip.at;
    if (flip.flip) {
      pen = togglePen(pen);                              // the page's own toggle path
      if (pen === PEN_MIND) lastBoundaryBar = bar;       // §9.1: the handoff consumes the bar
      flips.push({ bar, to: pen });
    }

    const call = decide({ barsNow: bar, lastBoundaryBar, phraseBars, inFlight: false, pen, playing });
    if (call.consume) lastBoundaryBar = call.at;
    if (call.fire) fires.push(bar);
  }
  return { flips, flipBars: flips.map((f) => f.bar), fires, pen };
}

// ---------------------------------------------------------------------------
// The mode token
// ---------------------------------------------------------------------------

describe('the mode token', () => {
  it('starts free — a page never wakes up alternating', () => {
    expect(INITIAL_MODE).toBe(MODE_FREE);
    expect(modeIsB2b(INITIAL_MODE)).toBe(false);
  });

  it('toggles both ways, and anything unrecognised reads as free', () => {
    expect(toggleMode(MODE_FREE)).toBe(MODE_B2B);
    expect(toggleMode(MODE_B2B)).toBe(MODE_FREE);
    expect(modeIsB2b(undefined)).toBe(false);
    expect(modeIsB2b('B2B')).toBe(false); // exact token or nothing
    expect(toggleMode('nonsense')).toBe(MODE_B2B);
  });
});

// ---------------------------------------------------------------------------
// The turn-length control
// ---------------------------------------------------------------------------

describe('the b2bBars control', () => {
  it('defaults to 16 with a floor of 4', () => {
    expect(DEFAULT_B2B_BARS).toBe(16);
    expect(MIN_B2B_BARS).toBe(4);
    expect(normalizeB2bBars(16)).toBe(16);
    expect(normalizeB2bBars('8')).toBe(8);
    expect(normalizeB2bBars(1)).toBe(MIN_B2B_BARS);
    expect(normalizeB2bBars(0)).toBe(MIN_B2B_BARS);
    expect(normalizeB2bBars(-8)).toBe(MIN_B2B_BARS);
    expect(normalizeB2bBars(16.9)).toBe(16);
  });

  it('falls back to the DEFAULT, not the floor, on an empty box', () => {
    // `Number('') === 0`: the trap §9.1 paid for on the phrase control. Clamping
    // a blank box would flip the pen every 4 bars while someone types "16".
    expect(normalizeB2bBars('')).toBe(DEFAULT_B2B_BARS);
    expect(normalizeB2bBars('   ')).toBe(DEFAULT_B2B_BARS);
    expect(normalizeB2bBars(null)).toBe(DEFAULT_B2B_BARS);
    expect(normalizeB2bBars(undefined)).toBe(DEFAULT_B2B_BARS);
    expect(normalizeB2bBars('abc')).toBe(DEFAULT_B2B_BARS);
    expect(normalizeB2bBars(NaN)).toBe(DEFAULT_B2B_BARS);
  });

  it('reports the next flip bar and the countdown beside the indicator', () => {
    expect(nextFlipBar(0, 16)).toBe(16);
    expect(nextFlipBar(15, 16)).toBe(16);
    expect(nextFlipBar(16, 16)).toBe(32); // standing ON a flip, the next is a turn away
    expect(barsUntilFlip(0, 16)).toBe(16);
    expect(barsUntilFlip(15, 16)).toBe(1);
    expect(barsUntilFlip(16, 16)).toBe(16); // the tick right after a flip reads a full turn
    expect(barsUntilFlip(5, 4)).toBe(3);
    // Never 0: the strip must not sit on "flips in 0 bars" between ticks.
    for (let bar = 0; bar <= 40; bar++) expect(barsUntilFlip(bar, 4)).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// The flip cadence
// ---------------------------------------------------------------------------

describe('b2bDecide — the flip cadence', () => {
  it('flips at every b2b boundary and at no bar between them', () => {
    expect(runFlips(64, { b2bBars: 16 }).bars).toEqual([16, 32, 48, 64]);
    expect(runFlips(12, { b2bBars: 4 }).bars).toEqual([4, 8, 12]);
    expect(runFlips(64, { b2bBars: 16 }).bars).not.toContain(0);
  });

  it('alternates the holder — HUMAN, MIND, HUMAN, MIND', () => {
    const { flips, pen } = runFlips(16, { b2bBars: 4, startPen: PEN_HUMAN });
    expect(flips).toEqual([
      { bar: 4, to: PEN_MIND },
      { bar: 8, to: PEN_HUMAN },
      { bar: 12, to: PEN_MIND },
      { bar: 16, to: PEN_HUMAN },
    ]);
    expect(pen).toBe(PEN_HUMAN); // four flips from human is back to human
  });

  it('names the destination from whoever is holding it, and only when it flips', () => {
    const at = { barsNow: 16, lastFlipBar: null, b2bBars: 16, mode: MODE_B2B, playing: true };
    expect(b2bDecide({ ...at, pen: PEN_HUMAN }).to).toBe(PEN_MIND);
    expect(b2bDecide({ ...at, pen: PEN_MIND }).to).toBe(PEN_HUMAN);
    // Between boundaries there is no destination — `to` is null, never a guess.
    expect(b2bDecide({ ...at, barsNow: 17, pen: PEN_MIND }).to).toBeNull();
    expect(b2bDecide({ ...at, playing: false, pen: PEN_MIND }).to).toBeNull();
  });

  it('flips once per boundary however many ticks land inside that bar', () => {
    // The page ticks ~8× per bar at 250 ms; only the first of them may flip, or
    // the pen would change hands eight times in two seconds.
    let lastFlipBar = null;
    const decisions = [];
    for (let tick = 0; tick < 8; tick++) {
      const d = b2bDecide({ barsNow: 16, lastFlipBar, b2bBars: 16, mode: MODE_B2B, playing: true, pen: PEN_HUMAN });
      if (d.consume) lastFlipBar = d.at;
      decisions.push(d);
    }
    expect(decisions.filter((d) => d.flip)).toHaveLength(1);
    expect(decisions[0]).toMatchObject({ flip: true, at: 16, why: B2B_WHY.FLIP, consume: true });
    expect(decisions[1].why).toBe(B2B_WHY.HANDLED);
    expect(decisions.at(-1).why).toBe(B2B_WHY.HANDLED);
  });

  it('reports why it stayed quiet between boundaries', () => {
    const d = b2bDecide({ barsNow: 11, lastFlipBar: 8, b2bBars: 4, mode: MODE_B2B, playing: true, pen: PEN_MIND });
    expect(d).toEqual({ flip: false, to: null, at: null, why: B2B_WHY.BETWEEN, consume: false });
  });

  it('answers a clock that has not started with no flip, not NaN', () => {
    const stopped = { lastFlipBar: null, b2bBars: 16, mode: MODE_B2B, playing: true, pen: PEN_HUMAN };
    expect(shouldFlip({ ...stopped, barsNow: 0 })).toBe(false);
    expect(shouldFlip({ ...stopped, barsNow: NaN })).toBe(false);
    expect(shouldFlip({ ...stopped, barsNow: -16 })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// The gates
// ---------------------------------------------------------------------------

describe('b2bDecide — the gates', () => {
  it('never flips in free mode', () => {
    expect(runFlips(64, { b2bBars: 16, mode: () => MODE_FREE }).bars).toEqual([]);
    const d = b2bDecide({ barsNow: 16, lastFlipBar: null, b2bBars: 16, mode: MODE_FREE, playing: true, pen: PEN_HUMAN });
    expect(d).toMatchObject({ flip: false, to: null, at: 16, why: B2B_WHY.FREE, consume: false });
  });

  it('never flips while stopped', () => {
    expect(runFlips(64, { b2bBars: 16, playing: () => false }).bars).toEqual([]);
    const d = b2bDecide({ barsNow: 32, lastFlipBar: null, b2bBars: 16, mode: MODE_B2B, playing: false, pen: PEN_MIND });
    expect(d).toMatchObject({ flip: false, to: null, at: 32, why: B2B_WHY.STOPPED, consume: false });
  });

  it('does not consume a boundary that passed in free mode', () => {
    // Bar 16 goes by in `free`; B2B is armed at bar 17. Nothing was scheduled at
    // 16, so nothing was burned — and the performer's first turn is a full one,
    // ending at 32 rather than being cut short.
    const { bars } = runFlips(48, { b2bBars: 16, mode: (bar) => (bar >= 17 ? MODE_B2B : MODE_FREE) });
    expect(bars).toEqual([32, 48]);
  });

  it('does not consume a boundary that passed while stopped', () => {
    const { bars } = runFlips(48, { b2bBars: 16, playing: (bar) => bar >= 17 });
    expect(bars).toEqual([32, 48]);
  });

  it('stops flipping the moment the mode goes back to free', () => {
    const { bars } = runFlips(64, { b2bBars: 16, mode: (bar) => (bar >= 33 ? MODE_FREE : MODE_B2B) });
    expect(bars).toEqual([16, 32]); // 48 and 64 never happen
  });

  it('arming B2B on a boundary bar waits for the next turn, not this one', () => {
    // The page consumes the current bar when B2B is armed (`lastFlipBar =
    // currentBars()`), the same rule §9.1 applies to a manual handoff. Without
    // it, clicking b2b at bar 16 flips inside bar 16 and the countdown the page
    // just announced is a lie.
    const armedAt = 16;
    const armed = { b2bBars: 16, mode: MODE_B2B, playing: true, pen: PEN_HUMAN };
    expect(b2bDecide({ barsNow: 16, lastFlipBar: armedAt, ...armed }).flip).toBe(false);
    expect(b2bDecide({ barsNow: 24, lastFlipBar: armedAt, ...armed }).flip).toBe(false);
    expect(b2bDecide({ barsNow: 32, lastFlipBar: armedAt, ...armed }).flip).toBe(true);
    // Arming mid-turn consumes a bar that is not a boundary, which must not
    // swallow the boundary that follows it.
    expect(b2bDecide({ barsNow: 32, lastFlipBar: 21, ...armed }).flip).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The composition — §9.2's one real hazard
// ---------------------------------------------------------------------------

describe('a flip and a phrase fire on the same bar', () => {
  it('lets the flip win: no mind call on the flip bar, one at its next boundary', () => {
    // b2b 4 / phrase 2 — every flip bar is also a phrase boundary, which is the
    // worst case on purpose. Bars 0..8 with the human opening:
    //   4  flip -> MIND   (the handoff consumes bar 4, so no fire at 4)
    //   6  the mind's FIRST fire — its next phrase boundary
    //   8  flip -> HUMAN  (no fire: the human holds it now)
    const { flipBars, fires } = runJam(8, { b2bBars: 4, phraseBars: 2, startPen: PEN_HUMAN });
    expect(flipBars).toEqual([4, 8]);
    expect(fires).toEqual([6]);
    expect(fires).not.toContain(4);
    expect(fires).not.toContain(8);
  });

  it('holds across several turns: the mind speaks only inside its own', () => {
    // 0-4 human · 4-8 mind (fires at 6) · 8-12 human · 12-16 mind (fires at 14).
    const { flipBars, fires, pen } = runJam(16, { b2bBars: 4, phraseBars: 2, startPen: PEN_HUMAN });
    expect(flipBars).toEqual([4, 8, 12, 16]);
    expect(fires).toEqual([6, 14]);
    expect(pen).toBe(PEN_HUMAN);
    // Every fire sits strictly inside a mind turn — never on a flip bar.
    for (const bar of fires) expect(flipBars).not.toContain(bar);
  });

  it('is the handoff rule doing the work, not a special case in b2bDecide', () => {
    // The proof that nothing new was invented: with the SAME timeline but the
    // handoff's bar-consume removed, the mind fires on the flip bar — the
    // double-act §9.2 forbids. b2bDecide is identical in both runs.
    let pen = PEN_HUMAN;
    let lastFlipBar = null;
    let lastBoundaryBar = null;
    const firesWithoutTheRule = [];
    for (let bar = 0; bar <= 8; bar++) {
      const flip = b2bDecide({ barsNow: bar, lastFlipBar, b2bBars: 4, mode: MODE_B2B, playing: true, pen });
      if (flip.consume) lastFlipBar = flip.at;
      if (flip.flip) pen = togglePen(pen); // ...and NOT the lastBoundaryBar line
      const call = decide({ barsNow: bar, lastBoundaryBar, phraseBars: 2, inFlight: false, pen, playing: true });
      if (call.consume) lastBoundaryBar = call.at;
      if (call.fire) firesWithoutTheRule.push(bar);
    }
    expect(firesWithoutTheRule).toContain(4); // the bug, reproduced
    expect(runJam(8, { b2bBars: 4, phraseBars: 2 }).fires).not.toContain(4); // the page, fixed
  });

  it('leaves an unaligned phrase alone — a fire between flips still happens', () => {
    // b2b 8 / phrase 3: the boundaries only coincide at 24. The mind's turn runs
    // 8-16, and its phrase boundaries inside that window are 9, 12 and 15.
    const { flipBars, fires } = runJam(16, { b2bBars: 8, phraseBars: 3, startPen: PEN_HUMAN });
    expect(flipBars).toEqual([8, 16]);
    expect(fires).toEqual([9, 12, 15]);
  });

  it('a mind turn shorter than one phrase produces no call at all — silence is a move', () => {
    // b2b 4 / phrase 8: the mind never reaches a phrase boundary inside its own
    // turn. §9.2 asks for no special casing, and there is none — the timeline
    // simply has no fires, which is a legible (if useless) configuration.
    const { flipBars, fires } = runJam(24, { b2bBars: 4, phraseBars: 8, startPen: PEN_HUMAN });
    expect(flipBars).toEqual([4, 8, 12, 16, 20, 24]);
    expect(fires).toEqual([]);
  });

  it('never fires while the human holds the pen, whatever the mode', () => {
    const { fires } = runJam(24, { b2bBars: 4, phraseBars: 2, startPen: PEN_HUMAN });
    // Human turns are [0,4) [8,12) [16,20): no fire may land in any of them.
    for (const bar of fires) {
      const turn = Math.floor(bar / 4) % 2; // 0 = human's turn, 1 = the mind's
      expect(turn).toBe(1);
    }
    expect(fires.length).toBeGreaterThan(0); // ...and the test is not vacuous
  });

  it('a stopped set flips nothing and fires nothing', () => {
    const { flipBars, fires } = runJam(32, { b2bBars: 4, phraseBars: 2, playing: false });
    expect(flipBars).toEqual([]);
    expect(fires).toEqual([]);
  });

  it('free mode is iteration 2 unchanged: the pen never moves on its own', () => {
    const started = runJam(32, { b2bBars: 4, phraseBars: 8, mode: MODE_FREE, startPen: PEN_MIND });
    expect(started.flipBars).toEqual([]);
    expect(started.pen).toBe(PEN_MIND);
    expect(started.fires).toEqual([8, 16, 24, 32]); // §9.1's cadence, untouched
  });
});

// ---------------------------------------------------------------------------
// What the mind is told
// ---------------------------------------------------------------------------

describe('the request body in a duet', () => {
  it('carries b2b: true while alternating', () => {
    const body = mindRequest({
      code: 'stack(s("bd*4"))',
      intent: 'answer the human',
      genre: 'deep',
      key: 'A:minor',
      barsElapsed: 8,
      recentReasons: ['human: ±0 lines — "gain(0.70)"'],
      b2b: true,
    });
    expect(body.b2b).toBe(true);
    expect(body.recent_reasons.at(-1)).toMatch(/^human: /); // the partner's last move
  });

  it('omits the key entirely in free mode — the body stays iteration 2 byte for byte', () => {
    const free = mindRequest({ code: 'stack()', intent: 'darker', genre: 'deep', key: 'A:minor', barsElapsed: 4 });
    expect('b2b' in free).toBe(false);
    expect(Object.keys(free)).toEqual(['code', 'intent', 'genre', 'key', 'bars_elapsed', 'recent_reasons']);
    // Explicitly falsy is the same as absent — the page sends `mode === 'b2b'`.
    expect('b2b' in mindRequest({ code: '', intent: 'x', b2b: false })).toBe(false);
  });

  it('is the mind turn of a real alternation, carrying the human turn that preceded it', () => {
    // The §9.2 sequence, end to end: the human is handed the pen at bar 8, edits
    // and evaluates (their summary lands in the ring), and at bar 16 the pen
    // flips back — the mind's first call of its turn is at its next phrase
    // boundary and carries BOTH the human's code and the human's reason.
    const b2bBars = 8;
    const phraseBars = 4;
    let pen = PEN_MIND;
    let lastFlipBar = null;
    let lastBoundaryBar = null;
    const ring = ['opened the bass filter'];
    let buffer = 'stack(s("bd*4").gain(0.92))';
    const calls = [];

    for (let bar = 0; bar <= 20; bar++) {
      const flip = b2bDecide({ barsNow: bar, lastFlipBar, b2bBars, mode: MODE_B2B, playing: true, pen });
      if (flip.consume) lastFlipBar = flip.at;
      if (flip.flip) {
        pen = togglePen(pen);
        if (pen === PEN_MIND) lastBoundaryBar = bar;
      }
      // The human's move, mid-turn, on their own keyboard.
      if (bar === 10 && pen === PEN_HUMAN) {
        buffer = 'stack(s("bd*4").gain(0.92), s("hh*16").gain(0.4))';
        ring.push('human: +1 line — "s("hh*16").gain(0.4)"');
      }
      const call = decide({ barsNow: bar, lastBoundaryBar, phraseBars, inFlight: false, pen, playing: true });
      if (call.consume) lastBoundaryBar = call.at;
      if (call.fire) {
        calls.push(mindRequest({
          code: buffer,
          intent: 'answer your partner',
          barsElapsed: call.at,
          recentReasons: ring,
          b2b: true,
        }));
      }
    }

    // The mind opened the set (fires at 4 and 8 are its own turn — 8 is the
    // flip bar itself, so it is silent there), the human held 8-16, and the
    // mind's first call back is at bar 20.
    expect(calls.map((c) => c.bars_elapsed)).toEqual([4, 20]);
    const answering = calls.at(-1);
    expect(answering.b2b).toBe(true);
    expect(answering.code).toContain('hh*16');                       // the human's code
    expect(answering.recent_reasons.at(-1)).toMatch(/^human: \+1 line/); // the human's move
  });
});

// ---------------------------------------------------------------------------
// Nothing in §9.1 moved
// ---------------------------------------------------------------------------

describe('the §9.1 controls are untouched', () => {
  it('keeps its own default and floor, separate from the turn length', () => {
    expect(DEFAULT_PHRASE_BARS).toBe(8);
    expect(DEFAULT_B2B_BARS).toBe(16);
    expect(WHY.FIRE).not.toBe(B2B_WHY.FLIP); // two schedulers, two vocabularies
  });
});
