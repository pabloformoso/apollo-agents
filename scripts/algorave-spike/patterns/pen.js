/*
 * pen.js — who holds the pen (plan §9.1, iteration 2).
 *
 * The pen is ONE control token, `pen ∈ {mind, human}`, and everything that
 * follows from it: when the phrase scheduler is allowed to ask the mind for a
 * mutation, how many bars have gone by, and what a human edit looks like once
 * it becomes state the mind is told about.
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

/** Clamp a UI number into a usable phrase length. An empty or nonsense input
 *  falls back rather than throwing — the scheduler must keep running while
 *  someone is halfway through typing "16" into the box. */
export function normalizePhraseBars(value, fallback = DEFAULT_PHRASE_BARS) {
  // An EMPTY box is the fallback, not the minimum: `Number('')` is 0, so
  // clamping it would quietly drop the phrase to 2 bars for as long as the box
  // is blank — i.e. every time someone clears it to type "16", which at 122 BPM
  // is a mind call every four seconds until they finish typing.
  if (value == null || (typeof value === 'string' && value.trim() === '')) return fallback;
  const n = Number(typeof value === 'string' ? value.trim() : value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(MIN_PHRASE_BARS, Math.floor(n));
}

/** The bar the next call is due at — display only, but it is the number that
 *  makes the scheduler legible on stream ("next mind call at bar 16"). */
export function nextBoundaryBar(barsNow, phraseBars) {
  const bars = normalizeBars(barsNow);
  const phrase = normalizePhraseBars(phraseBars);
  return (Math.floor(bars / phrase) + 1) * phrase;
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
 */
export function mindRequest({
  code,
  intent,
  genre,
  key,
  barsElapsed: bars,
  recentReasons,
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
  };
}
