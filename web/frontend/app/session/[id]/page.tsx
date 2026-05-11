"use client";
/**
 * Apollo v2.6.0 — Session detail (legacy phase machine, ember design).
 *
 * This page hosts the v2.5.x 9-phase agent flow (init → genre → planning
 * → checkpoint1 → critique → checkpoint2 → editing → validating →
 * building → rating → complete) until the backend is refactored to the
 * v2.6.0 contract proposed in HANDOFF.md. The flow logic is preserved
 * verbatim from the previous neon implementation; only the visual layer
 * is migrated to the Ember design system.
 *
 * What changed
 * ------------
 *   - Layout wrapped in `<Shell>` so the top nav matches every other v2.6.0
 *     route.
 *   - Phase indicator rendered as a thin segmented row below the nav
 *     (ember tokens, not the legacy pixel font).
 *   - Inputs (genre, checkpoint, editor, rating) reimplemented inline with
 *     ember primitives — no longer rely on the legacy `GenreInput`,
 *     `CheckpointActions`, `EditorInput`, `RatingInput` components.
 *   - Agent stream + playlist + critic rendered inline with ember tokens
 *     (no longer rely on `AgentStream`, `PlaylistPanel`, `CriticPanel`).
 *   - Banner pointing the user to the redesigned `/curate` view appears
 *     once the playlist exists. Clicking it lands on the new flow; the
 *     phase machine keeps running here in parallel until the user is
 *     ready to migrate.
 *
 * Once the backend refactor lands, this whole page is replaced by a
 * Brief → Curate redirect and the file gets deleted.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { getSession, rateSession } from "@/lib/api";
import { useSessionWS } from "@/lib/ws";
import { useAuth } from "@/lib/auth";
import type { Phase, ServerEvent, SessionState } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import { Arrow, Btn, Crumb } from "@/components/ember/primitives";

// ---------------------------------------------------------------------------
// Phase indicator
// ---------------------------------------------------------------------------
const PHASES: Phase[] = [
  "genre",
  "planning",
  "checkpoint1",
  "critique",
  "checkpoint2",
  "editing",
  "validating",
  "rating",
  "complete",
];

function PhaseBar({ current }: { current: Phase }) {
  const idx = PHASES.indexOf(current);
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto py-2 px-9 border-b border-line bg-surf">
      {PHASES.map((p, i) => {
        const passed = i < idx;
        const active = i === idx;
        return (
          <div
            key={p}
            className="flex items-center gap-1.5 flex-shrink-0"
          >
            <span
              // ``data-testid="phase-active"`` on the active span lets the
              // E2E phase fixture match without relying on visual classes
              // (the legacy fixture used ``font-bold`` which the ember
              // redesign doesn't apply).
              data-testid={active ? "phase-active" : undefined}
              data-phase={p}
              className={
                "font-mono text-[10px] uppercase tracking-mono transition-colors " +
                (active
                  ? "text-ember"
                  : passed
                    ? "text-cream/60"
                    : "text-faint")
              }
            >
              {p.replace("checkpoint", "ckpt")}
            </span>
            {i < PHASES.length - 1 && (
              <span className="text-line2 text-[10px]">›</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline log entry type — replaces the legacy `LogEntry` from AgentStream.
// ---------------------------------------------------------------------------
type LogEntry =
  | { type: "text"; content: string }
  | { type: "tool_call"; content: string }
  | { type: "tool_result"; content: string }
  | { type: "progress"; content: string }
  | { type: "system"; content: string }
  | { type: "error"; content: string };

// ---------------------------------------------------------------------------
// Inline AgentStream (ember-styled, replaces components/AgentStream).
// ---------------------------------------------------------------------------
function AgentStream({
  entries,
  isStreaming,
  buildStartedAt,
  buildName,
}: {
  entries: LogEntry[];
  isStreaming: boolean;
  buildStartedAt: number | null;
  buildName: string | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState(0);

  // Auto-scroll to the bottom as new entries land.
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries.length]);

  // Tick the build elapsed counter while a build is in flight.
  useEffect(() => {
    if (buildStartedAt === null) return;
    const id = window.setInterval(() => {
      setElapsed(Date.now() - buildStartedAt);
    }, 250);
    return () => window.clearInterval(id);
  }, [buildStartedAt]);

  function fmt(ms: number) {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  return (
    <div
      ref={ref}
      className="flex-1 overflow-auto px-9 py-6 flex flex-col gap-2.5 font-mono text-[13px]"
    >
      {entries.length === 0 && !isStreaming && (
        <p className="font-mono text-[11px] text-faint uppercase tracking-mono">
          waiting for agent…
        </p>
      )}
      {entries.map((e, i) => {
        switch (e.type) {
          case "text":
            return (
              <p
                key={i}
                className="text-ember-text leading-[1.55] whitespace-pre-wrap font-sans"
              >
                {e.content}
              </p>
            );
          case "tool_call":
            return (
              <p key={i} className="text-mute">
                <span className="text-ember">[tool]</span> {e.content}
              </p>
            );
          case "tool_result":
            return (
              <p
                key={i}
                className="text-ember-text/70 whitespace-pre-wrap"
              >
                <span className="text-faint">→</span> {e.content}
              </p>
            );
          case "progress":
            return (
              <p key={i} className="text-ember-text/80">
                <span className="text-warn">↳</span> {e.content}
              </p>
            );
          case "system":
            return (
              <p
                key={i}
                className="font-mono text-[11px] text-ember uppercase tracking-mono"
              >
                {e.content}
              </p>
            );
          case "error":
            return (
              <p key={i} className="text-ember">
                <span className="text-ember">✗</span> {e.content}
              </p>
            );
          default:
            return null;
        }
      })}
      {buildStartedAt !== null && (
        <p className="text-ember mt-2">
          <span className="animate-blink">▶</span>{" "}
          {buildName ? `Building "${buildName}"` : "Building session"} ·{" "}
          {fmt(elapsed)}
        </p>
      )}
      {isStreaming && entries.length > 0 && (
        <span className="inline-block w-2 h-4 bg-ember/70 animate-blink mt-1" />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline panels (Playlist + Critic).
// ---------------------------------------------------------------------------
function PlaylistPanel({ session }: { session: SessionState }) {
  const tracks = session.playlist ?? [];
  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-4 border-b border-line">
        <Crumb>playlist · {tracks.length} tracks</Crumb>
      </div>
      <div className="flex-1 overflow-auto">
        {tracks.length === 0 ? (
          <p className="px-5 py-6 font-mono text-[11px] text-faint uppercase tracking-mono">
            no playlist yet
          </p>
        ) : (
          <ul className="list-none m-0 p-0">
            {tracks.map((t, i) => (
              <li
                key={t.id}
                className="px-5 py-3 border-b border-line flex items-center gap-3"
              >
                <span className="font-display italic text-lg text-faint w-7 text-right flex-shrink-0">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-display italic text-base text-ember-text leading-[1.15] truncate">
                    {t.display_name}
                  </p>
                  <p className="font-mono text-[10px] text-faint uppercase tracking-mono mt-0.5">
                    {t.bpm ? `${t.bpm} BPM` : "—"} · {t.camelot_key ?? "—"}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function CriticPanel({ session }: { session: SessionState }) {
  const verdict = session.critic_verdict;
  const problems = session.structured_problems ?? [];
  const verdictTone =
    verdict === "APPROVED"
      ? "text-ok"
      : verdict === "NEEDS_FIXES"
        ? "text-warn"
        : verdict === "REJECT"
          ? "text-ember"
          : "text-faint";
  return (
    <div className="flex flex-col h-full">
      <div className="px-5 py-4 border-b border-line flex items-center justify-between">
        <Crumb>critic</Crumb>
        {verdict && (
          <span
            className={
              "font-mono text-[10px] uppercase tracking-mono " + verdictTone
            }
          >
            {verdict}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-auto">
        {problems.length === 0 ? (
          <p className="px-5 py-6 font-mono text-[11px] text-faint uppercase tracking-mono">
            {verdict === "APPROVED"
              ? "no issues found — set is solid."
              : "no critique yet"}
          </p>
        ) : (
          <ul className="list-none m-0 p-0">
            {problems.map((p, i) => (
              <li
                key={i}
                className="px-5 py-3 border-b border-line"
              >
                <span className="font-mono text-[10px] text-warn uppercase tracking-mono">
                  pos {p.pos_from}
                  {p.pos_from !== p.pos_to ? `–${p.pos_to}` : ""} ·{" "}
                  {p.key_pair} · Δ{p.bpm_diff} BPM
                </span>
                <p className="text-xs text-mute mt-1 leading-[1.55]">
                  {p.text}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Phase-specific input components (ember-styled).
// ---------------------------------------------------------------------------
function GenreInputBox({
  onSubmit,
  disabled,
  placeholder,
}: {
  onSubmit: (v: string) => void;
  disabled: boolean;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const [environment, setEnvironment] = useState("");

  const submit = () => {
    if (!value.trim()) return;
    const env = environment.trim();
    const composed = env
      ? `${value.trim()} (environment: ${env})`
      : value.trim();
    onSubmit(composed);
    setValue("");
    setEnvironment("");
  };

  return (
    <div className="flex flex-col gap-3">
      <Crumb>describe your session</Crumb>
      <div className="flex gap-2">
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={
            placeholder ?? "60-minute cyberpunk set, dark and intense…"
          }
          disabled={disabled}
          className="flex-1 bg-transparent border-0 border-b border-line2 px-0 py-2
            font-display italic text-2xl text-cream
            outline-none focus:border-ember transition-colors
            placeholder:text-faint disabled:opacity-50"
        />
        <Btn
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="font-display italic text-base"
        >
          Send <Arrow />
        </Btn>
      </div>
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="environment-input"
          className="font-mono text-[10px] text-faint uppercase tracking-mono"
        >
          Listening environment{" "}
          <span className="text-faint/60">(optional)</span>
        </label>
        <textarea
          id="environment-input"
          aria-label="Listening environment"
          value={environment}
          onChange={(e) => setEnvironment(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="loud crowded bar · intimate listening room · outdoor cafe morning"
          disabled={disabled}
          rows={2}
          className="w-full bg-transparent border border-line2 px-3 py-2
            font-sans text-sm text-ember-text
            outline-none focus:border-ember transition-colors
            placeholder:text-faint disabled:opacity-50 resize-none"
        />
      </div>
    </div>
  );
}

function CheckpointBox({
  phase,
  onApprove,
  onFeedback,
  disabled,
}: {
  phase: "checkpoint1" | "checkpoint2";
  onApprove: () => void;
  onFeedback: (msg: string) => void;
  disabled: boolean;
}) {
  const [feedback, setFeedback] = useState("");
  const label =
    phase === "checkpoint1"
      ? "Playlist looks good — run the Critic"
      : "Continue to Editor";
  return (
    <div className="flex flex-col gap-3">
      <Crumb>
        {phase === "checkpoint1"
          ? "approve to run critic, or send feedback to planner"
          : "approve to open editor, or send fixes to planner"}
      </Crumb>
      <div className="flex gap-2">
        <input
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && feedback.trim()) {
              onFeedback(feedback.trim());
              setFeedback("");
            }
          }}
          placeholder="Optional feedback…"
          disabled={disabled}
          className="flex-1 bg-transparent border-0 border-b border-line2 px-0 py-2
            font-display italic text-xl text-cream
            outline-none focus:border-ember transition-colors
            placeholder:text-faint disabled:opacity-50"
        />
        <Btn
          onClick={onApprove}
          disabled={disabled}
          className="font-display italic text-base whitespace-nowrap"
        >
          {label} <Arrow />
        </Btn>
      </div>
    </div>
  );
}

function EditorBox({
  onSubmit,
  disabled,
}: {
  onSubmit: (v: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");
  const submit = () => {
    if (value.trim()) {
      onSubmit(value.trim());
      setValue("");
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <Crumb>
        edit · type{" "}
        <span className="text-ember">build &lt;name&gt;</span> to render
      </Crumb>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex gap-2 items-center border border-line2 bg-surf px-4 py-2.5"
      >
        <span className="font-mono text-[11px] text-ember">›</span>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder='swap track 3 with deep-house--midnight-groove · build my-set'
          disabled={disabled}
          className="flex-1 bg-transparent border-0 text-ember-text font-mono text-[13px] outline-none placeholder:text-faint disabled:opacity-50"
        />
        <Btn
          kind="cream"
          type="submit"
          disabled={disabled || !value.trim()}
          className="px-4 py-1.5 text-[11px]"
        >
          Run
        </Btn>
      </form>
    </div>
  );
}

function RatingBox({
  onSubmit,
  sessionName,
}: {
  onSubmit: (r: number, n: string) => void;
  sessionName: string | null;
}) {
  const [rating, setRating] = useState(0);
  const [notes, setNotes] = useState("");
  return (
    <div className="flex flex-col gap-3">
      {sessionName && (
        <p className="text-ember text-xs">
          ✓ Built ·{" "}
          <span className="font-mono">output/{sessionName}/</span>
        </p>
      )}
      <Crumb>rate this session (1–5)</Crumb>
      <div className="flex gap-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            onClick={() => setRating(n)}
            className={
              "w-10 h-10 font-display italic text-lg transition-colors " +
              (n <= rating
                ? "bg-ember text-cream"
                : "bg-transparent border border-line2 text-faint hover:text-ember-text")
            }
          >
            {n}
          </button>
        ))}
      </div>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes (optional)…"
        className="w-full bg-transparent border-0 border-b border-line2 px-0 py-2
          font-display italic text-lg text-cream
          outline-none focus:border-ember transition-colors
          placeholder:text-faint"
      />
      <Btn
        onClick={() => rating > 0 && onSubmit(rating, notes)}
        disabled={rating === 0}
        className="self-start"
      >
        Save &amp; finish <Arrow />
      </Btn>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main session page
// ---------------------------------------------------------------------------
export default function SessionPage() {
  const params = useParams();
  const router = useRouter();
  const { user, hydrated } = useAuth();
  const sessionId = params.id as string;

  const [session, setSession] = useState<SessionState | null>(null);
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [wsReady, setWsReady] = useState(false);
  const [buildStartedAt, setBuildStartedAt] = useState<number | null>(null);
  const [buildName, setBuildName] = useState<string | null>(null);
  const pendingTextRef = useRef("");

  const flushText = useCallback(() => {
    if (pendingTextRef.current) {
      setLogEntries((prev) => [
        ...prev,
        { type: "text", content: pendingTextRef.current },
      ]);
      pendingTextRef.current = "";
    }
  }, []);

  const appendLog = useCallback(
    (entry: LogEntry) => {
      flushText();
      setLogEntries((prev) => [...prev, entry]);
    },
    [flushText],
  );

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case "text_delta":
          pendingTextRef.current += event.content;
          setStreaming(true);
          break;
        case "tool_call":
          flushText();
          setStreaming(false);
          if (event.name === "build_session") {
            const name =
              typeof event.input.session_name === "string"
                ? event.input.session_name
                : null;
            setBuildStartedAt(Date.now());
            setBuildName(name);
            setLogEntries((prev) => [
              ...prev,
              {
                type: "tool_call",
                content: name
                  ? `Building session "${name}"`
                  : "Building session",
              },
            ]);
          } else {
            setLogEntries((prev) => [
              ...prev,
              {
                type: "tool_call",
                content: `${event.name}(${JSON.stringify(event.input)})`,
              },
            ]);
          }
          break;
        case "tool_progress":
          setLogEntries((prev) => [
            ...prev,
            { type: "progress", content: event.message },
          ]);
          break;
        case "tool_result":
          if (event.name === "build_session") {
            setBuildStartedAt(null);
            setBuildName(null);
          }
          setLogEntries((prev) => [
            ...prev,
            { type: "tool_result", content: event.result },
          ]);
          break;
        case "phase_start":
          flushText();
          setStreaming(false);
          setLogEntries((prev) => [
            ...prev,
            {
              type: "system",
              content: `── ${event.phase.replace(/_/g, " ").toUpperCase()} ──`,
            },
          ]);
          break;
        case "phase_complete":
          flushText();
          setStreaming(false);
          setSession(event.data as SessionState);
          if (event.phase === "genre") {
            const envValue = (event.data as SessionState).environment;
            if (envValue && envValue.toLowerCase() !== "unspecified") {
              setLogEntries((prev) => [
                ...prev,
                {
                  type: "system",
                  content: `environment: ${envValue}`,
                },
              ]);
            }
          }
          break;
        case "state":
          setSession(event.data);
          setWsReady(true);
          break;
        case "error":
          flushText();
          setStreaming(false);
          appendLog({ type: "error", content: event.message });
          break;
      }
    },
    [flushText, appendLog],
  );

  const [sessionLoaded, setSessionLoaded] = useState(false);
  const { send } = useSessionWS(
    sessionLoaded ? sessionId : null,
    handleEvent,
  );

  useEffect(() => {
    // Wait for ``useAuth`` to hydrate from localStorage before deciding
    // whether to redirect. Without this guard the first render observes
    // ``user = null`` (the initial state of ``useAuth``) and pushes the
    // user to /login even when they're signed in. The redesign-flow E2E
    // test pinned this regression — see
    // ``e2e/redesign-flow.spec.ts:: Legacy /session/[id] does NOT bounce``.
    if (!hydrated) return;
    if (!user) {
      router.push("/login");
      return;
    }
    getSession(sessionId)
      .then((s) => {
        setSession(s);
        setSessionLoaded(true);
      })
      .catch(() => router.push("/dashboard"));
  }, [sessionId, router, user, hydrated]);

  const sendMsg = useCallback(
    (type: string, content?: string) => {
      flushText();
      setStreaming(true);
      send({ type, ...(content !== undefined ? { content } : {}) });
    },
    [send, flushText],
  );

  async function handleRate(rating: number, notes: string) {
    await rateSession(sessionId, rating, notes);
    setSession((prev) => (prev ? { ...prev, phase: "complete" } : prev));
    appendLog({
      type: "system",
      content: "Session saved to memory. Thanks!",
    });
  }

  if (!session) {
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex items-center justify-center">
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            loading session…
          </p>
        </section>
      </Shell>
    );
  }

  const phase = session.phase as Phase;
  const hasPlaylist = (session.playlist?.length ?? 0) > 0;

  return (
    <Shell
      username={user?.username ?? null}
      sessionLabel={session.session_name ?? session.genre ?? null}
    >
      <PhaseBar current={phase} />

      {/* When the legacy phase machine has produced a playlist, surface
          the v2.6.0 redesign routes so the user can switch over without
          going back to the dashboard. */}
      {hasPlaylist && (
        <div className="border-b border-line bg-surf2 px-9 py-2.5 flex items-center justify-between flex-shrink-0">
          <span className="text-xs text-ember-text/70">
            Playlist ready — the new{" "}
            <span className="text-ember">Curate</span> view has critic notes
            integrated as actionable cards.
          </span>
          <div className="flex gap-2">
            <Link
              href={`/curate?session=${sessionId}`}
              className="bg-ember text-cream px-3 py-1 text-[11px] font-sans hover:brightness-110 transition-all"
            >
              Open Curate →
            </Link>
            <Link
              href={`/editor?session=${sessionId}`}
              className="border border-line2 text-ember-text/70 px-3 py-1 text-[11px] font-sans hover:border-ember hover:text-ember transition-colors"
            >
              Editor
            </Link>
            <Link
              href={`/live?session=${sessionId}`}
              className="border border-line2 text-ember-text/70 px-3 py-1 text-[11px] font-sans hover:border-ember hover:text-ember transition-colors"
            >
              Live
            </Link>
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Left: agent stream + phase input */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-line">
          <AgentStream
            entries={logEntries}
            isStreaming={streaming}
            buildStartedAt={buildStartedAt}
            buildName={buildName}
          />

          <div className="border-t border-line px-9 py-5 bg-surf flex-shrink-0">
            {!wsReady && phase === "init" && (
              <p className="font-mono text-[11px] text-faint uppercase tracking-mono animate-pulse">
                connecting…
              </p>
            )}

            {wsReady && phase === "init" && (
              <GenreInputBox
                onSubmit={(v) => sendMsg("genre_intent", v)}
                disabled={false}
              />
            )}

            {phase === "genre" && (
              <GenreInputBox
                onSubmit={(v) => sendMsg("genre_intent", v)}
                disabled={streaming}
              />
            )}

            {phase === "checkpoint1" && (
              <CheckpointBox
                phase="checkpoint1"
                onApprove={() => sendMsg("checkpoint_approve")}
                onFeedback={(v) => sendMsg("genre_intent", v)}
                disabled={streaming}
              />
            )}

            {phase === "checkpoint2" && (
              <CheckpointBox
                phase="checkpoint2"
                onApprove={() => sendMsg("checkpoint2_approve")}
                onFeedback={(v) => sendMsg("genre_intent", v)}
                disabled={streaming}
              />
            )}

            {phase === "editing" && (
              <div className="flex flex-col gap-3">
                <EditorBox
                  onSubmit={(v) => sendMsg("editor_command", v)}
                  disabled={streaming}
                />
                <Btn
                  data-testid="go-live-button"
                  onClick={() => router.push(`/session/${sessionId}/live`)}
                  className="self-start font-display italic text-base"
                >
                  ▶ Go live
                </Btn>
              </div>
            )}

            {(phase === "planning" ||
              phase === "critique" ||
              phase === "validating") && (
              <p className="font-mono text-[11px] text-faint uppercase tracking-mono animate-pulse">
                agent working…
              </p>
            )}

            {phase === "rating" && (
              <div className="flex flex-col gap-4">
                <RatingBox
                  onSubmit={handleRate}
                  sessionName={session.session_name}
                />
                <Btn
                  data-testid="go-live-button"
                  onClick={() => router.push(`/session/${sessionId}/live`)}
                  className="self-start font-display italic text-base"
                >
                  ▶ Go live
                </Btn>
              </div>
            )}

            {phase === "complete" && (
              <div className="flex flex-col gap-3">
                <p className="text-ember text-sm">
                  ✓ Session complete · output saved to{" "}
                  <span className="font-mono">
                    output/{session.session_name}/
                  </span>
                </p>
                <Btn
                  data-testid="go-live-button"
                  onClick={() => router.push(`/session/${sessionId}/live`)}
                  className="self-start font-display italic text-base"
                >
                  ▶ Go live
                </Btn>
              </div>
            )}
          </div>
        </div>

        {/* Right: playlist + critic stacked */}
        <div className="w-80 flex flex-col flex-shrink-0">
          <div className="flex-1 border-b border-line overflow-hidden">
            <PlaylistPanel session={session} />
          </div>
          <div className="h-72 overflow-hidden">
            <CriticPanel session={session} />
          </div>
        </div>
      </div>
    </Shell>
  );
}
