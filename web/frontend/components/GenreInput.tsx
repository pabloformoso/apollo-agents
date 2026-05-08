"use client";
import { useState } from "react";

/**
 * Genre + environment input pair for the session intake screen.
 *
 * The textarea is decorative: its value is concatenated as a
 * "(environment: <text>)" suffix to the genre message. The Genre Guard
 * prompt extracts environment from the message on either side, so a user
 * can describe everything in the main field OR split it across the two —
 * both flows hydrate ctx.environment correctly.
 *
 * Mock pipeline's `fake_genre` echoes whatever appears between the parens
 * so E2E specs can round-trip the value end-to-end.
 *
 * Lives as a dedicated component (rather than inline in the page) so the
 * concatenation logic can be unit-tested in isolation.
 */
export default function GenreInput({
  onSubmit,
  disabled,
}: {
  onSubmit: (v: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  const [environment, setEnvironment] = useState("");

  const submit = () => {
    if (!value.trim()) return;
    const env = environment.trim();
    const composed = env ? `${value.trim()} (environment: ${env})` : value.trim();
    onSubmit(composed);
    setValue("");
    setEnvironment("");
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">Describe your session — genre, duration, mood.</p>
      <p className="text-xs text-muted/60">Example: &quot;Build a 60-minute deep house set, late night vibes&quot;</p>
      <div className="flex gap-2">
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          placeholder="60-minute cyberpunk set, dark and intense..."
          disabled={disabled}
          className="flex-1 bg-[#0a0a0f] border border-border rounded px-3 py-2 text-sm text-[#e2e2ff] focus:outline-none focus:border-neon transition-colors disabled:opacity-40"
          autoFocus
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="bg-neon text-[#0a0a0f] px-4 py-2 rounded text-xs font-bold uppercase tracking-widest hover:bg-neon-dim transition-colors disabled:opacity-40"
        >
          Send
        </button>
      </div>
      <div className="space-y-1">
        <label
          htmlFor="environment-input"
          className="text-xs text-muted/80 block"
        >
          Listening environment <span className="text-muted/40">(optional)</span>
        </label>
        <textarea
          id="environment-input"
          aria-label="Listening environment"
          value={environment}
          onChange={e => setEnvironment(e.target.value)}
          onKeyDown={e => {
            // Cmd/Ctrl+Enter from the textarea submits; bare Enter inserts a
            // newline so the user can describe a multi-line scene if they
            // really want to.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="loud crowded bar  |  intimate listening room  |  outdoor cafe morning"
          disabled={disabled}
          rows={2}
          className="w-full bg-[#0a0a0f] border border-border rounded px-3 py-2 text-xs text-[#e2e2ff] focus:outline-none focus:border-neon transition-colors disabled:opacity-40 resize-none"
        />
      </div>
    </div>
  );
}
