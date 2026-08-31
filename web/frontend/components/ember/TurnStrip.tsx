"use client";
/**
 * §11 S4–S6 — the turn-taking strip (§11.3 seam 4).
 *
 * Who holds the pen, how many bars to the next boundary, how many to the next
 * B2B flip, and what the other party is working on. This is the single most
 * reusable thing in the rave, because **a crossfade IS a phrase boundary**:
 * the same strip can later sit over the DJ lane's decks with nothing changed
 * but its props.
 *
 * That is why it takes plain numbers and strings and imports nothing from the
 * algorave. The pen module does the deciding; this only shows the decision.
 * Keep it that way — the moment it reaches for a Strudel buffer it stops being
 * mountable over decks and the seam closes.
 */
import { Crumb } from "./primitives";

export type PenHolder = "human" | "mind";

export type TurnStripProps = {
  /** Who may write right now. */
  pen: PenHolder;
  /** Bars since the transport started. */
  barsNow: number;
  /** Bars per phrase — the grid the other party is allowed to act on. */
  phraseBars: number;
  /** Absolute bar of the next boundary, or null when nothing is running. */
  nextBoundaryBar: number | null;
  /** Bars until the pen changes hands, or null when not alternating. */
  barsToFlip: number | null;
  /** What the pen-holder is working on right now, if anything. */
  working?: string | null;
  /** Why the scheduler last did or did not act — observability, not decoration. */
  why?: string | null;
  onTogglePen?: () => void;
  onToggleB2b?: () => void;
  b2b?: boolean;
};

export function TurnStrip({
  pen,
  barsNow,
  phraseBars,
  nextBoundaryBar,
  barsToFlip,
  working,
  why,
  onTogglePen,
  onToggleB2b,
  b2b = false,
}: TurnStripProps) {
  const mindHasIt = pen === "mind";

  return (
    <div
      data-testid="turn-strip"
      data-pen={pen}
      className={
        "flex items-center justify-between gap-4 flex-wrap border rounded-md px-4 py-3 " +
        (mindHasIt
          ? "border-ember bg-[color-mix(in_srgb,var(--color-ember)_9%,transparent)]"
          : "border-line2 bg-surf")
      }
    >
      <div className="flex items-baseline gap-3 flex-wrap">
        <span
          data-testid="pen-holder"
          className={
            "font-display italic text-2xl tracking-display-snug " +
            (mindHasIt ? "text-ember" : "text-ember-text")
          }
        >
          {mindHasIt ? "Mind" : "You"}
        </span>
        <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
          holds the pen
        </span>
        {working && (
          <span
            data-testid="turn-working"
            className="text-mute text-sm italic font-display"
          >
            — “{working}”
          </span>
        )}
      </div>

      <div className="flex items-center gap-4 flex-wrap">
        <Crumb>
          bar {barsNow} · phrase {phraseBars}
        </Crumb>
        <span
          data-testid="next-boundary"
          className="font-mono uppercase tracking-mono text-[10.5px] text-faint"
        >
          {nextBoundaryBar === null
            ? "not running"
            : `next boundary at bar ${nextBoundaryBar}`}
        </span>
        {barsToFlip !== null && (
          <span
            data-testid="bars-to-flip"
            className="font-mono uppercase tracking-mono text-[10.5px] text-warn"
          >
            pen flips in {barsToFlip}
          </span>
        )}
        {why && (
          // The WHY is shown, not just logged: when the mind does nothing at a
          // boundary, "a call was still in flight" and "you hold the pen" are
          // very different silences.
          <span
            data-testid="turn-why"
            className="font-mono text-[10.5px] text-faint"
          >
            {why}
          </span>
        )}

        {onTogglePen && (
          <button
            type="button"
            onClick={onTogglePen}
            data-testid="toggle-pen"
            className="font-mono uppercase tracking-mono text-[10.5px] px-3 py-1.5 rounded border border-line2 text-ember-text cursor-pointer hover:border-ember"
          >
            {mindHasIt ? "take the pen back" : "give the mind the pen"}
          </button>
        )}
        {onToggleB2b && (
          <button
            type="button"
            onClick={onToggleB2b}
            data-testid="toggle-b2b"
            className={
              "font-mono uppercase tracking-mono text-[10.5px] px-3 py-1.5 rounded border cursor-pointer " +
              (b2b
                ? "border-warn text-warn"
                : "border-line2 text-ember-text hover:border-ember")
            }
          >
            {b2b ? "stop b2b" : "start b2b"}
          </button>
        )}
      </div>
    </div>
  );
}
