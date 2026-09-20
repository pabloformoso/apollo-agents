"use client";
/**
 * Apollo's reasoning, on screen.
 *
 * Two shapes of the same feed. ``panel`` is the booth's: a bordered list
 * the operator reads while working. ``overlay`` is the audience's and the
 * OBS Browser Source's: a few lines pinned bottom-right, display italic,
 * no chrome, so the stream shows WHY the music is doing what it is doing —
 * which is the whole difference between "an AI directs this" and "a
 * playlist is playing".
 *
 * It renders ``ReasoningEntry`` and nothing else: no socket, no Strudel,
 * no engine. The fold lives in ``lib/reasoning.ts``.
 */
import type { ReasoningEntry, ReasoningKind } from "@/lib/reasoning";
import { Crumb } from "./primitives";

const KIND_LABEL: Record<ReasoningKind, string> = {
  thought: "thinking",
  action: "doing",
  outcome: "result",
  transition: "transition",
  decision: "engine",
  warning: "heads-up",
};

const KIND_TONE: Record<ReasoningKind, string> = {
  thought: "text-cream",
  action: "text-ember",
  outcome: "text-mute",
  transition: "text-warn",
  decision: "text-neon",
  warning: "text-warn",
};

export type ReasoningFeedProps = {
  entries: ReasoningEntry[];
  thinking?: boolean;
  variant?: "panel" | "overlay";
  /** How many entries to show; the tail of the feed. */
  limit?: number;
  className?: string;
};

export function ReasoningFeed({
  entries,
  thinking = false,
  variant = "panel",
  limit = variant === "overlay" ? 4 : 10,
  className = "",
}: ReasoningFeedProps) {
  const tail = entries.slice(-limit);

  if (variant === "overlay") {
    if (tail.length === 0 && !thinking) return null;
    return (
      <aside
        aria-label="apollo reasoning"
        data-testid="reasoning-overlay"
        className={"flex flex-col items-end gap-1.5 pointer-events-none " + className}
      >
        {tail.map((e, i) => {
          const latest = i === tail.length - 1;
          return (
            <div
              key={e.id}
              data-kind={e.kind}
              className={
                "max-w-[44ch] text-right bg-black/35 px-3 py-1.5 backdrop-blur-sm leading-snug " +
                (latest ? "opacity-100" : "opacity-60")
              }
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-faint mr-2">
                {KIND_LABEL[e.kind]}
              </span>
              <span className={"font-display italic text-lg " + KIND_TONE[e.kind]}>
                {e.text}
                {e.open ? <span className="animate-pulse">…</span> : null}
              </span>
              {e.detail && (
                <div className="font-mono text-[10px] uppercase tracking-mono text-faint mt-0.5">{e.detail}</div>
              )}
            </div>
          );
        })}
        {thinking && !tail[tail.length - 1]?.open && (
          <div
            data-testid="reasoning-thinking"
            className="font-mono text-[10px] uppercase tracking-[0.22em] text-ember animate-pulse bg-black/35 px-3 py-1"
          >
            apollo is thinking
          </div>
        )}
      </aside>
    );
  }

  return (
    <section
      aria-label="apollo reasoning"
      data-testid="reasoning-panel"
      className={"border-t border-line pt-[18px] min-w-0 " + className}
    >
      <div className="flex items-baseline justify-between gap-3">
        <Crumb>why apollo does what it does</Crumb>
        {thinking && (
          <span
            data-testid="reasoning-thinking"
            className="font-mono text-[10px] uppercase tracking-[0.22em] text-ember animate-pulse"
          >
            thinking…
          </span>
        )}
      </div>
      {tail.length === 0 ? (
        <p className="mt-2 text-sm text-faint">
          Nothing decided yet — the first thought arrives with the first transition.
        </p>
      ) : (
        <ol className="mt-2 flex flex-col gap-1.5 max-h-[220px] overflow-auto">
          {tail.map((e, i) => {
            const latest = i === tail.length - 1;
            return (
              <li
                key={e.id}
                data-kind={e.kind}
                className={"flex gap-3 items-baseline " + (latest ? "" : "opacity-70")}
              >
                <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-faint w-[8ch] shrink-0 pt-1">
                  {KIND_LABEL[e.kind]}
                </span>
                <div className="min-w-0">
                  <p className={"font-display italic text-base leading-snug " + KIND_TONE[e.kind]}>
                    {e.text}
                    {e.open ? <span className="animate-pulse">…</span> : null}
                  </p>
                  {e.detail && (
                    <p className="font-mono text-[10px] uppercase tracking-mono text-faint mt-0.5">{e.detail}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
