"use client";
import { useEffect, useRef, useState } from "react";

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

export default function AgentStream({
  entries,
  isStreaming,
  buildStartedAt = null,
  buildName = null,
}: AgentStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  // Tick every second while a build is running so the elapsed timer updates.
  useEffect(() => {
    if (!buildStartedAt) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [buildStartedAt]);

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
