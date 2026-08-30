/*
 * pen.js — who holds the pen (plan §9.1, iteration 2; §9.2, iteration 3).
 *
 * The pen is ONE control token, `pen ∈ {mind, human}`, and everything that
 * follows from it: when the phrase scheduler is allowed to ask the mind for a
 * mutation, how many bars have gone by, and what a human edit looks like once
 * it becomes state the mind is told about. §9.2 adds a SECOND token beside it,
 * `mode ∈ {free, b2b}`, and the scheduler that flips the first one every
 * `b2bBars` — a back-to-back set is two turns of §9.1, alternating.
 *
 * Why this is a module and not fifty more lines inside playground.html:
 * §9.1 asks for exactly that split. The interesting failure modes here are
 * decisions, not pixels — "did it fire twice in the same bar", "did a boundary
 * reached mid-request get queued instead of skipped", "is 15.7 s eight bars or
 * seven" — and none of them need a DOM, a clock, or a network to reproduce.
 * So this file is pure: no `document`, no `fetch`, no timers, no module-level
 * mutable state. Everything is a function of its arguments, which is what lets
 * test/pen.test.mjs drive a whole jam in a millisecond and the page wire the
 * same functions to a real `setInterval`.
 *
 * Served to the browser by serve.mjs's `/patterns/` mount (a plain `.js` file,
 * imported as a module by playground.html) and imported directly by vitest.
 * One copy, two consumers — the reason the page no longer carries its own
 * line-diff.
 */

// The two holders. Strings rather than a boolean because "who holds the pen"
// is displayed, logged and sent — `pen === 'mind'` reads the same in all three.
export const PEN_HUMAN = 'human';
export const PEN_MIND = 'mind';

/** §9.1: the page starts at `human`. Loading a page must never fire LLM calls
 *  by itself — the first mind call is always something a person asked for. */
export const INITIAL_PEN = PEN_HUMAN;

/** Phrase length in bars. 8 is the default the contract names; 2 is the floor
 *  because a 1-bar phrase would ask the mind roughly twice a second at 122 BPM,
 *  which is not a phrase, it is a denial-of-service on your own model. */
export const DEFAULT_PHRASE_BARS = 8;
export const MIN_PHRASE_BARS = 2;

/** §9.2's second token: `mode ∈ {free, b2b}`. In `free` the pen only moves when
 *  someone clicks it (§9.1); in `b2b` a scheduler flips it every `b2bBars`.
 *  Strings for the same reason the pen is one — displayed, logged and sent. */
export const MODE_FREE = 'free';
export const MODE_B2B = 'b2b';

/** §9.2: a page wakes up FREE, and the mode is never persisted — same principle
 *  as the pen. Restoring "b2b" from localStorage would mean a reloaded tab
 *  starts handing the editor to the mind on a timer nobody armed. */
export const INITIAL_MODE = MODE_FREE;

/** Bars per turn in a back-to-back. 16 is the contract's default (a real turn:
 *  two 8-bar phrases at the default phrase length). 4 is the floor because a
 *  turn shorter than that is a stutter, not a turn — at 122 BPM it is under 8
 *  seconds, less than one round trip to the mind on the slow models. */
export const DEFAULT_B2B_BARS = 16;
export const MIN_B2B_BARS = 4;

/** How many reasons the mind is told about. §9.1 pins 5 — the ring is the
 *  page's job because `strudel_mind` serialises whatever state it is handed. */
export const MAX_RECENT_REASONS = 5;

/** Truncation budget for the quoted line in a human-edit summary. Long enough
 *  for `s("[~ oh]*4").bank("RolandTR909").gain(0.55).pan(0.52)` to survive
 *  almost whole, short enough that five of them do not crowd the prompt. */
export const SUMMARY_LINE_MAX = 60;

// ---------------------------------------------------------------------------
// The pen token
// ---------------------------------------------------------------------------

/** The whole state machine: two states, one edge, no history.
 *  Anything that is not `mind` is treated as `human` — the fail-safe direction,
 *  since a corrupt token must never hand the mind an unattended editor. */
export function togglePen(pen) {
  return pen === PEN_MIND ? PEN_HUMAN : PEN_MIND;
}

/** True when the scheduler is allowed to exist at all. */
export function penHoldsMind(pen) {
  return pen === PEN_MIND;
}

// ---------------------------------------------------------------------------
// Bars — derived from the audio clock, never counted by hand
// ---------------------------------------------------------------------------

/** `bars_elapsed = floor(elapsed_since_play × cps)` (§9.1).
 *
 * One cycle is one bar in this spike (the page sets `cps = BPM/60/4`), so the
 * cycle count IS the bar count. Precision beyond ±1 bar is explicitly not
 * required: application happens through `evaluate()`, which hot-swaps at the
 * next cycle boundary anyway, so sub-bar drift is unobservable.
 *
 * Garbage in (NaN elapsed before the first play, a zero cps before the REPL
 * booted) yields 0 rather than NaN: bar 0 is never a phrase boundary, so a
 * not-yet-started clock cannot trigger anything.
 */
export function barsElapsed(elapsedSeconds, cps) {
  if (!Number.isFinite(elapsedSeconds) || !Number.isFinite(cps)) return 0;
  if (elapsedSeconds <= 0 || cps <= 0) return 0;
  return Math.floor(elapsedSeconds * cps);
}

/** Seconds one bar lasts at this cps — for the "next call in ~Ns" readout. */
export function secondsPerBar(cps) {
  return Number.isFinite(cps) && cps > 0 ? 1 / cps : Number.POSITIVE_INFINITY;
}

function normalizeBars(bars) {
  if (!Number.isFinite(bars) || bars <= 0) return 0;
  return Math.floor(bars);
}

/**
 * Clamp a UI number box into a usable bar count, or fall back.
 *
 * ONE copy for both controls (§9.1's `phrase`, §9.2's `b2bBars`) because the
 * trap they share cost a debugging session: an EMPTY box is the fallback, not
 * the minimum. `Number('')` is 0, so clamping it would quietly drop the control
 * to its floor for as long as the box is blank — i.e. every time someone clears
 * it to type "16", which at 122 BPM is a mind call every four seconds (or a pen
 * flip every eight) until they finish typing.
 */
function clampBarsControl(value, min, fallback) {
  if (value == null || (typeof value === 'string' && value.trim() === '')) return fallback;
  const n = Number(typeof value === 'string' ? value.trim() : value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.floor(n));
}

/** Clamp a UI number into a usable phrase length. An empty or nonsense input
 *  falls back rather than throwing — the scheduler must keep running while
 *  someone is halfway through typing "16" into the box. */
export function normalizePhraseBars(value, fallback = DEFAULT_PHRASE_BARS) {
  return clampBarsControl(value, MIN_PHRASE_BARS, fallback);
}

/** The same clamp for §9.2's turn length: default 16, floor 4, empty box falls
 *  back to the default rather than to the floor. */
export function normalizeB2bBars(value, fallback = DEFAULT_B2B_BARS) {
  return clampBarsControl(value, MIN_B2B_BARS, fallback);
}

function nextMultiple(bars, every) {
  return (Math.floor(bars / every) + 1) * every;
}

/** The bar the next call is due at — display only, but it is the number that
 *  makes the scheduler legible on stream ("next mind call at bar 16"). */
export function nextBoundaryBar(barsNow, phraseBars) {
  return nextMultiple(normalizeBars(barsNow), normalizePhraseBars(phraseBars));
}

/** The bar the pen changes hands at. Standing ON a flip bar, the next one is a
 *  full turn ahead — which is what makes the countdown below read 16, not 0,
 *  in the tick immediately after a flip. */
export function nextFlipBar(barsNow, b2bBars) {
  return nextMultiple(normalizeBars(barsNow), normalizeB2bBars(b2bBars));
}

/** §9.2's on-screen countdown: "pen flips in N bars". Always ≥ 1 while the
 *  clock runs, so the strip never sits on a stale "in 0 bars". */
export function barsUntilFlip(barsNow, b2bBars) {
  const bars = normalizeBars(barsNow);
  return nextFlipBar(bars, b2bBars) - bars;
}

// ---------------------------------------------------------------------------
// The scheduler decision
// ---------------------------------------------------------------------------

/** Why a tick did or did not fire. Distinct strings because they are four
 *  different situations on screen and three of them are not problems. */
export const WHY = {
  FIRE: 'phrase-boundary',
  BETWEEN: 'between-boundaries',
  HANDLED: 'boundary-already-handled',
  STOPPED: 'not-playing',
  HUMAN: 'human-holds-the-pen',
  IN_FLIGHT: 'request-in-flight',
};

/**
 * One tick's decision (§9.1's phrase scheduler), as a pure function.
 *
 * Boundaries are the multiples of `phraseBars` — bar 8, 16, 24 at the default —
 * and they are *events*, not a backlog. That is the whole reason this is
 * modulo arithmetic on the absolute bar count rather than `barsNow -
 * lastFired >= phraseBars`: with the subtraction, a boundary missed because a
 * request was still in flight stays true forever after, so the skipped call
 * would fire the instant the previous one landed. §9.1 says *skipped, not
 * queued*, and modulo gives exactly that — miss bar 8 and the next chance is
 * bar 16.
 *
 * `lastBoundaryBar` is the bar of the last boundary the scheduler HANDLED,
 * which includes the ones it deliberately skipped: consuming a skipped
 * boundary is what stops a late tick inside the same bar from firing it after
 * the in-flight request lands. The caller stores `at` whenever `consume` is
 * true; the ~8 ticks per bar that follow then read as `boundary-already-handled`.
 *
 * @param {object} tick
 * @param {number} tick.barsNow          bars since play started (see barsElapsed)
 * @param {number|null} tick.lastBoundaryBar  last boundary fired OR skipped
 * @param {number} tick.phraseBars       bars per phrase (UI control, default 8)
 * @param {boolean} tick.inFlight        is a /mind request already open?
 * @param {string} tick.pen              'mind' | 'human'
 * @param {boolean} tick.playing         is audio running?
 * @returns {{fire: boolean, at: number|null, why: string, consume: boolean}}
 */
export function decide({ barsNow, lastBoundaryBar, phraseBars, inFlight, pen, playing }) {
  const bars = normalizeBars(barsNow);
  const phrase = normalizePhraseBars(phraseBars);

  // Bar 0 is not a boundary. Handing the pen over on a stopped page, or one
  // second into a set, must not fire — the first call is due a phrase in.
  const atBoundary = bars > 0 && bars % phrase === 0;
  if (!atBoundary) return { fire: false, at: null, why: WHY.BETWEEN, consume: false };
  if (bars === lastBoundaryBar) return { fire: false, at: bars, why: WHY.HANDLED, consume: false };

  // Order matters below: `playing` and `pen` are checked BEFORE `inFlight`
  // because only the in-flight case is a boundary the scheduler owned and
  // burned. A boundary that goes by while the human holds the pen is not
  // consumed — nothing was scheduled, so there is nothing to skip.
  if (!playing) return { fire: false, at: bars, why: WHY.STOPPED, consume: false };
  if (!penHoldsMind(pen)) return { fire: false, at: bars, why: WHY.HUMAN, consume: false };
  if (inFlight) return { fire: false, at: bars, why: WHY.IN_FLIGHT, consume: true };

  return { fire: true, at: bars, why: WHY.FIRE, consume: true };
}

/** `decide(...).fire`, for callers that only want the yes/no. */
export function shouldFire(tick) {
  return decide(tick).fire;
}

// ---------------------------------------------------------------------------
// B2B — the alternation scheduler (§9.2)
// ---------------------------------------------------------------------------

/** The mode toggle. Anything that is not `b2b` reads as `free`, which is the
 *  fail-safe direction: a corrupt token must never arm an automatic handover. */
export function toggleMode(mode) {
  return mode === MODE_B2B ? MODE_FREE : MODE_B2B;
}

/** True when the flip scheduler is allowed to exist at all. */
export function modeIsB2b(mode) {
  return mode === MODE_B2B;
}

/** Why a tick did or did not flip the pen. Separate from `WHY` because these
 *  are a different set of situations about a different scheduler — sharing one
 *  object would make `not-playing` mean two things in the same log line. */
export const B2B_WHY = {
  FLIP: 'b2b-boundary',
  BETWEEN: 'between-flips',
  HANDLED: 'flip-already-handled',
  STOPPED: 'not-playing',
  FREE: 'free-mode',
};

/**
 * One tick's B2B decision (§9.2): does the pen change hands on this bar?
 *
 * Deliberately the SAME shape of arithmetic as `decide()` — boundaries are the
 * multiples of `b2bBars`, they are events rather than a backlog, and the bar of
 * the last flip HANDLED is what stops the other ~7 ticks inside that bar from
 * flipping it again. Two schedulers with one rule is the whole reason a flip
 * and a phrase fire landing on the same bar behave predictably.
 *
 * That coincidence is §9.2's one real hazard, and it is resolved by ORDER at
 * the call site rather than by a special case here: the page runs this decision
 * BEFORE `decide()`, and the flip goes through §9.1's handoff path, which
 * consumes the current bar whenever the pen lands on the mind
 * (`lastBoundaryBar = barsNow`). So on a shared boundary the flip wins and the
 * mind's first fire is its NEXT phrase boundary — no double-act, no new
 * mechanism. See test/b2b.test.mjs, which composes the two exactly that way.
 *
 * `pen` is NOT a gate — a flip is a flip whoever is holding it. It is only what
 * `to` is computed from, and it is the one field beyond §9.2's named five
 * (`{barsNow, lastFlipBar, b2bBars, mode, playing}`) that a `{flip, to}` answer
 * needs: `to` is a destination, and a destination needs an origin.
 *
 * @param {object} tick
 * @param {number} tick.barsNow      bars since play started (see barsElapsed)
 * @param {number|null} tick.lastFlipBar  the last flip boundary handled
 * @param {number} tick.b2bBars      bars per turn (UI control, default 16)
 * @param {string} tick.mode         'free' | 'b2b'
 * @param {boolean} tick.playing     is audio running?
 * @param {string} [tick.pen]        'mind' | 'human' — only to compute `to`
 * @returns {{flip: boolean, to: string|null, at: number|null, why: string, consume: boolean}}
 */
export function b2bDecide({ barsNow, lastFlipBar, b2bBars, mode, playing, pen }) {
  const bars = normalizeBars(barsNow);
  const every = normalizeB2bBars(b2bBars);

  // Bar 0 is not a boundary: switching to B2B on a stopped page, or one second
  // into a set, must not flip. The first turn is a full turn.
  const atBoundary = bars > 0 && bars % every === 0;
  if (!atBoundary) return { flip: false, to: null, at: null, why: B2B_WHY.BETWEEN, consume: false };
  if (bars === lastFlipBar) return { flip: false, to: null, at: bars, why: B2B_WHY.HANDLED, consume: false };

  // Neither gate consumes: nothing was scheduled, so there is nothing to burn.
  // A boundary that goes by while the set is stopped or the mode is free must
  // leave the next one intact — otherwise arming B2B just after one would
  // silently cost the performer their first turn.
  if (!playing) return { flip: false, to: null, at: bars, why: B2B_WHY.STOPPED, consume: false };
  if (!modeIsB2b(mode)) return { flip: false, to: null, at: bars, why: B2B_WHY.FREE, consume: false };

  return { flip: true, to: togglePen(pen), at: bars, why: B2B_WHY.FLIP, consume: true };
}

/** `b2bDecide(...).flip`, for callers that only want the yes/no. */
export function shouldFlip(tick) {
  return b2bDecide(tick).flip;
}

// ---------------------------------------------------------------------------
// Line diff — one copy, used by the page's renderer AND the summarizer
// ---------------------------------------------------------------------------

/**
 * Longest-common-subsequence diff over lines: `[{type:'same'|'add'|'del', text}]`.
 *
 * Hand-rolled because a dependency for this would be heavier than the
 * algorithm, and it lives here rather than in the page because §9.1 wants the
 * human-edit summary tested — and the summary is a reading of this diff.
 * `lcs[i][j]` is the LCS length of `a[i:]` and `b[j:]`.
 */
export function diffLines(before, after) {
  const a = String(before ?? '').split('\n');
  const b = String(after ?? '').split('\n');
  const lcs = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j]
        ? lcs[i + 1][j + 1] + 1
        : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ type: 'same', text: b[j++] });
      i++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ type: 'del', text: a[i++] });
    } else {
      out.push({ type: 'add', text: b[j++] });
    }
  }
  while (i < a.length) out.push({ type: 'del', text: a[i++] });
  while (j < b.length) out.push({ type: 'add', text: b[j++] });
  return out;
}

/** Cut a line down to `max` characters, ellipsis included in the budget. */
export function truncateLine(text, max = SUMMARY_LINE_MAX) {
  const line = String(text ?? '').trim();
  if (max <= 1) return line.slice(0, Math.max(0, max));
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

/**
 * `"human: ±N lines — \"<first changed line>\""` — or null when nothing changed.
 *
 * §9.1: human edits become state automatically, "never typed". Nobody
 * livecoding is going to narrate their own edits into a text box mid-phrase,
 * so the ring gets a mechanical summary instead: the NET line delta plus the
 * first line that differs, which together are enough for the mind's "do not
 * repeat the recent reasons" rule to notice that a human just moved something.
 *
 * The delta is net rather than `+2/-1` because the interesting signal is
 * direction (did the human add a layer or strip one), and an in-place edit —
 * the common case, one gain nudged — is `±0`, with the quoted line carrying
 * what actually happened.
 */
export function summarizeHumanEdit(before, after, { max = SUMMARY_LINE_MAX } = {}) {
  const a = String(before ?? '');
  const b = String(after ?? '');
  if (a === b) return null; // no change is not an event

  const rows = diffLines(a, b);
  const added = rows.filter((r) => r.type === 'add').length;
  const removed = rows.filter((r) => r.type === 'del').length;
  const net = added - removed;

  const sign = net > 0 ? '+' : net < 0 ? '-' : '±';
  const n = Math.abs(net);
  const delta = `${sign}${n} ${n === 1 ? 'line' : 'lines'}`;

  // The first changed line — ADDED text where there is any, because the useful
  // half of "they nudged a gain" is what the line says NOW, and an LCS diff
  // always emits the `del` of a changed line before its `add`. A pure deletion
  // has no added text, so it quotes what went away; the `-N` prefix says which
  // of the two you are looking at. Blank lines are skipped over: a diff that
  // opens by adding an empty line would otherwise quote nothing at all.
  const filled = (type) => rows.find((r) => r.type === type && r.text.trim().length > 0);
  const changed = rows.filter((r) => r.type !== 'same');
  const first = filled('add') ?? filled('del') ?? changed[0];
  const quoted = truncateLine(first ? first.text : '', max) || '(blank line)';

  return `human: ${delta} — "${quoted}"`;
}

// ---------------------------------------------------------------------------
// The recent-reasons ring
// ---------------------------------------------------------------------------

/**
 * Append to the ring, keeping the last `cap` (FIFO), and return a NEW array.
 *
 * Non-mutating on purpose: the ring is read while a request is in flight, and
 * a pure `push` makes "what did that call actually carry" answerable after the
 * fact instead of being overwritten under it. Empty reasons are dropped — a
 * mutation with no `// reason:` line has nothing to tell the next one.
 */
export function pushReason(ring, reason, cap = MAX_RECENT_REASONS) {
  const list = Array.isArray(ring) ? ring : [];
  const text = String(reason ?? '').trim();
  if (!text) return list;
  const limit = Number.isFinite(cap) && cap > 0 ? Math.floor(cap) : MAX_RECENT_REASONS;
  return [...list, text].slice(-limit);
}

// ---------------------------------------------------------------------------
// The request body
// ---------------------------------------------------------------------------

/**
 * The `POST /mind` body, snake_case for the Python side (`parse_request`).
 *
 * Built here so the manual button and the scheduler cannot drift apart — the
 * handoff in §9.1 only works because a scheduled call is *the same call*, with
 * `current_code` being whatever is in the editor, human-written or not.
 *
 * `b2b` is emitted ONLY when it is true (§9.2). Sending `b2b: false` would be
 * the same request semantically and a different one on the wire: the free-mode
 * body stays byte-identical to iteration 2's, which is what keeps a free-mode
 * jam comparable to the bench — the same reason §9.2 puts the duet line in the
 * user message and leaves the system prompt alone.
 */
export function mindRequest({
  code,
  intent,
  genre,
  key,
  barsElapsed: bars,
  recentReasons,
  b2b,
  cap = MAX_RECENT_REASONS,
}) {
  const limit = Number.isFinite(cap) && cap > 0 ? Math.floor(cap) : MAX_RECENT_REASONS;
  return {
    code: String(code ?? ''),
    intent: String(intent ?? '').trim(),
    genre: String(genre ?? ''),
    key: String(key ?? ''),
    bars_elapsed: normalizeBars(bars),
    recent_reasons: (Array.isArray(recentReasons) ? recentReasons : []).slice(-limit),
    ...(b2b ? { b2b: true } : {}),
  };
}

/**
 * §9.1 addendum (2026-08-30, from the first real practice session): may a
 * SCHEDULED proposal still be auto-applied?
 *
 * The mind's mutation was computed against the buffer as it was when the
 * request fired, and the model takes 10-30 s to answer — plenty of time for
 * the human to edit meanwhile. Auto-applying over those keystrokes turns the
 * duet into a fight (the practice report: "me pongo a editar y la mente
 * vuelve a cambiarlo encima"), so the HUMAN wins ties: the proposal lands
 * only when the buffer is still byte-identical to what the mind was shown.
 * Exact equality on purpose — even a whitespace tweak is a human at the
 * keyboard, and dropping one proposal costs a phrase, not the jam.
 *
 * This gates the SCHEDULER's auto-apply only. A hand-clicked Apply is a human
 * decision made while looking at the diff, and is never blocked here.
 */
export function autoApplyDecision({ askedWith, current }) {
  if (String(askedWith ?? '') === String(current ?? '')) {
    return { apply: true, why: 'buffer unchanged since the request fired' };
  }
  return {
    apply: false,
    why: 'the buffer changed while the mind was thinking — your edit wins, proposal dropped',
  };
}
