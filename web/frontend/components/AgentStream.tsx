"use client";
import { useEffect, useRef, useSyncExternalStore } from "react";

interface LogEntry {
  type: "text" | "tool_call" | "tool_result" | "system" | "error" | "progress";
  content: string;
}

interface AgentStreamProps {
  entries: LogEntry[];
  isStreaming: boolean;
  buildStartedAt?: number | null;
  buildName?: string | null;
}

export type { LogEntry };

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// External "wall-clock" store — `useSyncExternalStore` is the canonical
// React 19 way to subscribe to a ticking external value without
// `setState`-in-`useEffect` (flagged by `react-hooks/set-state-in-effect`).
//
// CRITICAL: `getSnapshot` MUST return a referentially stable value between
// React render passes — React calls it during every render to check whether
// the store changed, and if it returns a *new* number on every call (e.g.
// raw `Date.now()`), React thinks the store keeps changing and re-renders
// forever. We cache the result at 1 s resolution and only invalidate the
// cache when ``subscribeSecond``'s interval fires — that gives the UI a
// 1 Hz update for the elapsed counter without risking an infinite loop.
let _cachedSecondMs: number | null = null;

function _refreshCachedSecondMs(): number {
  const ms = Math.floor(Date.now() / 1000) * 1000;
  _cachedSecondMs = ms;
  return ms;
}

function subscribeSecond(onChange: () => void): () => void {
  const id = setInterval(() => {
    _refreshCachedSecondMs();
    onChange();
  }, 1000);
  return () => clearInterval(id);
}
function subscribeNoop(): () => void {
  // Even when there's no subscription we MUST keep the snapshot stable:
  // initialise the cache once (lazily on first read) so re-renders of
  // ``AgentStream`` while idle don't churn.
  return () => {};
}
function getSecondNow(): number {
  if (_cachedSecondMs === null) {
    return _refreshCachedSecondMs();
  }
  return _cachedSecondMs;
}
function getServerSecondNow(): number {
  // Server-render snapshot must also be stable across calls. 0 is a safe
  // sentinel — the elapsed counter only renders when buildStartedAt is set
  // (client-only path).
  return 0;
}

export default function AgentStream({
  entries,
  isStreaming,
  buildStartedAt = null,
  buildName = null,
}: AgentStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  // Subscribe to the global 1 s tick only when a build is in flight; the
  // empty subscriber is a no-op so React doesn't re-render in idle.
  const now = useSyncExternalStore(
    buildStartedAt ? subscribeSecond : subscribeNoop,
    getSecondNow,
    getServerSecondNow,
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  function entryColor(type: LogEntry["type"]) {
    switch (type) {
      case "tool_call":   return "text-purple";
      case "tool_result": return "text-[#e2e2ff]/60";
      case "progress":    return "text-[#e2e2ff]/80";
      case "system":      return "text-neon";
      case "error":       return "text-danger";
      default:            return "text-[#e2e2ff]";
    }
  }

  function entryPrefix(type: LogEntry["type"]) {
    switch (type) {
      case "tool_call":   return "  [tool] ";
      case "tool_result": return "  → ";
      case "progress":    return "    ↳ ";
      case "system":      return "── ";
      case "error":       return "✗ ";
      default:            return "";
    }
  }

  const elapsed = buildStartedAt ? formatElapsed(now - buildStartedAt) : null;

  return (
    <div className="bg-[#0a0a0f] border border-border rounded h-full overflow-y-auto p-4 font-mono text-xs leading-relaxed">
      {entries.length === 0 && (
        <p className="text-muted">Waiting for agent...</p>
      )}
      {entries.map((e, i) => (
        <div key={i} className={`whitespace-pre-wrap ${entryColor(e.type)} animate-fade-in`}>
          <span className="opacity-50">{entryPrefix(e.type)}</span>
          {e.content}
        </div>
      ))}
      {buildStartedAt && (
        <div className="mt-2 flex items-center gap-2 text-neon animate-fade-in">
          <span className="animate-blink">▶</span>
          <span>
            Building{buildName ? ` "${buildName}"` : ""} — {elapsed} elapsed
          </span>
        </div>
      )}
      {isStreaming && !buildStartedAt && (
        <span className="text-neon animate-blink">█</span>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
