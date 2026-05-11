"use client";
/**
 * Apollo v2.6.0 — Curate.
 *
 * Direct port of the prototype `Curate` from
 * docs/design/apollo-claude-design/apollo/project/prototype-screens.jsx.
 *
 * Three-column layout:
 *   - Left rail: cover stripe + set stats + version pills.
 *   - Center: arc strip (energy curve) + the playlist as track rows.
 *   - Right: critic notes as cards with Apply / Edit / Ignore actions.
 *
 * Wiring (v2.6.0):
 *   - Reads ``GET /api/sessions/:id`` for the full session including the
 *     server-mapped ``notes`` (CriticNote[]), ``handled`` (note ids the
 *     user has acted on), ``arc`` (energy points), ``set_health``.
 *   - Subscribes to ``/ws/sessions/:id`` to surface streaming planning +
 *     critique progress when the user lands here from Brief.
 *   - Apply fires ``POST .../notes/:id/apply`` (a bounded editor turn);
 *     Ignore fires ``POST .../notes/:id/ignore`` (no agent, just sets
 *     the note's status). Both are optimistic with rollback on failure.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { applyNote, getSession, ignoreNote } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAutoSession } from "@/lib/auto-session";
import { useSessionWS } from "@/lib/ws";
import type { CriticNote, ServerEvent, SessionState, Track } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import {
  Arrow,
  Btn,
  Crumb,
  Stripe,
} from "@/components/ember/primitives";
import { Banner, Spinner, toast } from "@/components/ember/feedback";

// ── Stats helpers ────────────────────────────────────────────────────────
function avg(xs: number[]): number {
  if (!xs.length) return 0;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

/** Best-effort energy estimate — falls back from BPM when the server arc
 * isn't present (legacy sessions or pre-planning state). Same coefficients
 * as `web/backend/arc.py`. */
function energyFor(t: Track): number {
  const bpm = t.bpm ?? 60;
  return Math.max(1, Math.min(10, (bpm - 50) / 12));
}

/** Phases where Curate shows the streaming "Apollo is curating" view
 *  instead of the final UI. */
const STREAMING_PHASES = new Set(["init", "genre", "planning", "checkpoint1"]);

export default function CuratePage() {
  const router = useRouter();
  const { user } = useAuth();
  const auto = useAutoSession("playlist");
  const sessionId = auto.status === "ready" ? auto.sessionId : null;

  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Optimistic per-note in-flight set — keyed by note id, value is the
  // pending status. Cleared as soon as the server response merges in.
  const [pending, setPending] = useState<Map<string, "applied" | "ignored">>(
    new Map(),
  );
  // Latest critic thought (last `text_delta` content) — surfaced as a
  // single-line ticker while phase === "critique". Reset on phase change.
  const [critTicker, setCritTicker] = useState<string>("");

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true);
    getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSession(s);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // WS subscription — picks up streaming planning + critique progress
  // when the user lands here from /brief. Merges `phase_complete` and
  // `state` events into the local session; keeps the full agent
  // question (up to ~1000 chars) so phase=genre confirmations stay
  // readable instead of being truncated.
  const onEvent = useCallback((ev: ServerEvent) => {
    if (ev.type === "state" || ev.type === "phase_complete") {
      // Server-authoritative — replace local session wholesale.
      setSession(ev.data as SessionState);
      // A successful refresh clears optimistic pending entries since the
      // server's `handled` list is now the source of truth.
      setPending(new Map());
    } else if (ev.type === "text_delta") {
      setCritTicker((prev) => (prev + ev.content).slice(-1000));
    } else if (ev.type === "phase_start") {
      setCritTicker("");
    } else if (ev.type === "error") {
      toast.error(ev.message);
    }
  }, []);
  const { send } = useSessionWS(sessionId, onEvent);

  const [reply, setReply] = useState("");
  const [replyBusy, setReplyBusy] = useState(false);

  // Send the user's reply to the genre_guard. The backend dispatches on
  // ``type: "genre_intent"`` (see `web/backend/app.py:1126`) — same wire
  // protocol the legacy session page used, so the planner picks up
  // exactly where it paused.
  const submitReply = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const t = reply.trim();
      if (!t || replyBusy) return;
      send({ type: "genre_intent", content: t });
      setReply("");
      setCritTicker("");
      setReplyBusy(true);
      // Clear busy after a short window so the input re-enables once the
      // next text_delta starts streaming. The phase_start event also
      // clears critTicker, so a phase change naturally drops the gate.
      window.setTimeout(() => setReplyBusy(false), 1500);
    },
    [reply, replyBusy, send],
  );

  const tracks = session?.playlist ?? [];

  // Server provides ready-mapped CriticNote[]. Fall back to empty for
  // legacy sessions whose to_dict pre-dates v2.6.0.
  const notes = session?.notes ?? [];

  const handledStatus = useMemo<Map<string, "applied" | "ignored">>(() => {
    const m = new Map<string, "applied" | "ignored">();
    // Server's `handled` list doesn't carry status — the per-note
    // `status` field on the CriticNote does. Walk notes, merge with
    // optimistic pending.
    for (const n of notes) {
      if (n.status === "applied" || n.status === "ignored") {
        m.set(n.id, n.status);
      }
    }
    for (const [id, st] of pending) m.set(id, st);
    return m;
  }, [notes, pending]);

  const stats = useMemo(() => {
    const tBpm = tracks.map((t) => t.bpm ?? 0).filter(Boolean);
    return {
      tracks: tracks.length,
      length: `${Math.floor(tracks.length * 6.8)}m`, // ~6.8 min/track avg
      avgBpm: avg(tBpm).toFixed(1),
      keyFlow:
        tracks.length > 0
          ? `${tracks[0].camelot_key ?? "?"}→${tracks[tracks.length - 1].camelot_key ?? "?"}`
          : "—",
      arcLabel: session?.arc?.flat ? "flat" : "shaped",
    };
  }, [tracks, session?.arc]);

  // Server arc points → energy curve. Fall back to BPM-derived per-track.
  const energyAt = useCallback(
    (i: number): number => {
      const p = session?.arc?.points?.[i];
      if (typeof p === "number") return p;
      const t = tracks[i];
      return t ? energyFor(t) : 0;
    },
    [session?.arc, tracks],
  );

  const handleApply = useCallback(
    async (noteId: string) => {
      if (!sessionId) return;
      setPending((m) => new Map(m).set(noteId, "applied"));
      try {
        const updated = await applyNote(sessionId, noteId);
        setSession(updated);
      } catch (e) {
        setPending((m) => {
          const next = new Map(m);
          next.delete(noteId);
          return next;
        });
        toast.error((e as Error).message || "Apply failed — try again.");
      }
    },
    [sessionId],
  );

  const handleIgnore = useCallback(
    async (noteId: string) => {
      if (!sessionId) return;
      setPending((m) => new Map(m).set(noteId, "ignored"));
      try {
        await ignoreNote(sessionId, noteId);
        // Cheap re-fetch keeps `handled` + per-note status in sync without
        // waiting for the WS phase_complete echo.
        const fresh = await getSession(sessionId);
        setSession(fresh);
      } catch (e) {
        setPending((m) => {
          const next = new Map(m);
          next.delete(noteId);
          return next;
        });
        toast.error((e as Error).message || "Ignore failed — try again.");
      }
    },
    [sessionId],
  );

  // ── Loading / error / empty states ────────────────────────────────────
  if (auto.status !== "ready" || loading) {
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex items-center justify-center">
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            {auto.status === "redirect" ? "Redirecting…" : "Loading session…"}
          </p>
        </section>
      </Shell>
    );
  }
  if (error || !session) {
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex flex-col items-center justify-center gap-4">
          <Crumb tone="ember">error</Crumb>
          <p className="text-mute">{error ?? "Session not found"}</p>
          <Btn kind="ghost" onClick={() => router.push("/dashboard")}>
            Back to library
          </Btn>
        </section>
      </Shell>
    );
  }

  // (a) Session has no brief AND no playlist — direct the user back to
  //     /brief instead of showing a half-formed Curate. The Brief POST
  //     transitions phase to "planning" optimistically, so init + no
  //     playlist means the session was created via the legacy
  //     no-body POST (e.g. dashboard "New session" link).
  if (session.phase === "init" && tracks.length === 0) {
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex flex-col items-center justify-center gap-6 px-[60px]">
          <Crumb>02 · curate</Crumb>
          <h1 className="font-display italic font-normal text-5xl tracking-display-snug text-center max-w-[600px]">
            No brief yet<span className="text-ember">.</span>
          </h1>
          <p className="text-mute text-base max-w-[420px] text-center leading-[1.55]">
            Start from Brief and Apollo will curate while you watch.
          </p>
          <Btn onClick={() => router.push(`/brief?session=${session.id}`)}>
            Open Brief <Arrow />
          </Btn>
        </section>
      </Shell>
    );
  }

  // Streaming view — planning hasn't finished yet. Show a single-row
  // status + an optional critic ticker so the wait feels intentional
  // rather than empty. When phase=genre, the agent is asking the user
  // to confirm details — render an inline reply input so they can
  // continue without leaving the screen.
  if (STREAMING_PHASES.has(session.phase) && tracks.length === 0) {
    const isAskingGenre = session.phase === "genre";
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex flex-col items-center justify-center gap-6 px-[60px]">
          <Crumb tone="ember">02 · curate</Crumb>
          <h1 className="font-display italic font-normal text-5xl tracking-display-snug text-center max-w-[600px]">
            {isAskingGenre ? (
              <>Apollo has a question<span className="text-ember">.</span></>
            ) : (
              <>Apollo is curating<span className="text-ember">…</span></>
            )}
          </h1>
          <div className="flex items-center gap-2.5 text-mute font-mono text-[11px] uppercase tracking-mono">
            <Spinner />
            {isAskingGenre
              ? "confirming the brief"
              : session.phase === "planning"
                ? "building the playlist"
                : "starting up"}
          </div>
          {critTicker && (
            <p className="text-ember-text text-sm max-w-[640px] text-center font-display italic leading-[1.45] whitespace-pre-wrap">
              {critTicker}
            </p>
          )}
          {isAskingGenre && (
            <form
              onSubmit={submitReply}
              className="w-full max-w-[640px] flex items-center gap-2 border border-line2 px-3.5 py-2.5 focus-within:border-ember transition-colors"
            >
              <span className="text-ember mr-1.5 font-display italic">›</span>
              <input
                autoFocus
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder='Reply to Apollo — e.g. "yes, sounds good" or "make it deep house"'
                className="flex-1 bg-transparent border-0 text-ember-text font-sans text-sm outline-none placeholder:text-faint"
                disabled={replyBusy}
              />
              <Btn
                type="submit"
                disabled={replyBusy || !reply.trim()}
                className="px-4 py-1.5 text-[11px]"
              >
                {replyBusy ? "…" : "Send"}
              </Btn>
            </form>
          )}
        </section>
      </Shell>
    );
  }

  const fixCount = notes.filter(
    (n) => n.severity === "fix" && !handledStatus.has(n.id),
  ).length;
  const okCount = notes.filter((n) => n.severity === "ok").length || 1;

  return (
    <Shell
      username={user?.username ?? null}
      sessionLabel={session.session_name ?? session.genre ?? null}
    >
      <div className="flex-1 grid grid-cols-[220px_1fr_380px]">
        {/* ── Left rail ── */}
        <aside className="border-r border-line px-[22px] py-7 flex flex-col gap-[18px]">
          <Stripe
            alpha={0.18}
            className="aspect-square p-3.5 flex flex-col justify-between"
          >
            <Crumb tone="ember">apollo · 010</Crumb>
            <div className="font-display italic text-2xl leading-[0.95] text-cream">
              {session.genre ?? "untitled"}
            </div>
          </Stripe>

          <div className="flex flex-col gap-2.5 text-xs">
            {([
              ["Tracks", String(stats.tracks)],
              ["Length", stats.length],
              ["Avg BPM", stats.avgBpm],
              ["Key flow", stats.keyFlow],
              ["Energy", stats.arcLabel],
            ] as const).map(([k, v]) => (
              <div
                key={k}
                className="flex justify-between text-mute"
              >
                <span>{k}</span>
                <span
                  className={
                    "font-mono " +
                    (k === "Energy" && stats.arcLabel === "flat"
                      ? "text-warn"
                      : "text-ember-text")
                  }
                >
                  {v}
                </span>
              </div>
            ))}
            {typeof session.set_health === "number" && (
              <div className="flex justify-between text-mute pt-1.5 border-t border-line">
                <span>Set health</span>
                <span className="font-mono text-ember">
                  {session.set_health}/100
                </span>
              </div>
            )}
          </div>

          <div className="mt-auto">
            <Crumb>versions</Crumb>
            <div className="flex flex-col gap-1 mt-2">
              {/* Versions branching is out of scope for v2.6.0 — kept
                  decoratively but disabled so users don't expect it to
                  work. */}
              <button
                disabled
                title="Versions are decorative in v2.6.0 — coming in v2.7."
                className="bg-surf2 text-ember-text border border-line2 px-2.5 py-1.5 font-mono text-[11px] text-left opacity-70 cursor-not-allowed"
              >
                v1
              </button>
              <button
                disabled
                title="Versions are decorative in v2.6.0 — coming in v2.7."
                className="bg-transparent text-mute border border-transparent px-2.5 py-1.5 font-mono text-[11px] text-left opacity-70 cursor-not-allowed"
              >
                v2 (peakier)
              </button>
              <button
                disabled
                title="Versions are decorative in v2.6.0 — coming in v2.7."
                className="bg-transparent text-faint border border-dashed border-line2 px-2.5 py-1.5 font-mono text-[11px] text-left opacity-70 cursor-not-allowed"
              >
                + branch
              </button>
            </div>
          </div>
        </aside>

        {/* ── Center: playlist + arc ── */}
        <section className="px-9 py-7 flex flex-col gap-[18px] overflow-hidden">
          <div className="flex justify-between items-baseline">
            <div>
              <Crumb>02 · curate</Crumb>
              <h2 className="font-display italic font-normal text-4xl tracking-display-snug m-0 mt-1">
                The set
              </h2>
            </div>
            <Btn
              kind="ghost"
              onClick={() => router.push(`/editor?session=${session.id}`)}
            >
              Edit by hand
            </Btn>
          </div>

          {session.phase === "critique" && (
            <Banner tone="info">
              <Spinner />
              Apollo is reviewing the set…
            </Banner>
          )}

          {/* arc strip */}
          <div className="relative py-3 border-y border-line">
            <Crumb>
              arc · {stats.arcLabel === "flat" ? "! flat" : "shaped"}
            </Crumb>
            <svg
              viewBox="0 0 600 60"
              preserveAspectRatio="none"
              className="w-full h-[50px] mt-1.5"
            >
              <line
                x1="0"
                y1="40"
                x2="600"
                y2="40"
                stroke="var(--line2)"
                strokeDasharray="2 4"
              />
              {tracks.map((t, i) => {
                const x = (i + 0.5) * (600 / tracks.length);
                const y = 50 - energyAt(i) * 5;
                return (
                  <g key={i}>
                    <line
                      x1={x}
                      y1="50"
                      x2={x}
                      y2={y}
                      stroke="var(--ember)"
                      strokeWidth="1.5"
                      opacity="0.5"
                    />
                    <circle cx={x} cy={y} r="4" fill="var(--ember)" />
                  </g>
                );
              })}
              <path
                d={tracks
                  .map((t, i) => {
                    const x = (i + 0.5) * (600 / tracks.length);
                    const y = 50 - energyAt(i) * 5;
                    return `${i === 0 ? "M" : "L"}${x} ${y}`;
                  })
                  .join(" ")}
                stroke="var(--ember)"
                strokeWidth="1"
                fill="none"
                opacity="0.6"
              />
            </svg>
          </div>

          <ul className="list-none m-0 p-0 flex flex-col overflow-auto">
            {tracks.map((t, i) => (
              <li
                key={t.id}
                className="grid grid-cols-[32px_60px_1fr_70px_50px_90px_28px] gap-4 items-center py-3.5 border-b border-line"
              >
                <span className="font-display italic text-2xl text-faint">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <Stripe
                  alpha={0.16 + i * 0.04}
                  className="w-[50px] h-[50px]"
                />
                <div>
                  <div className="font-display italic text-[22px] leading-[1.1]">
                    {t.display_name}
                  </div>
                  <div className="text-xs text-mute mt-1">
                    {t.genre ?? "—"} ·{" "}
                    <span className="font-mono text-[10px] text-faint">
                      {t.id}
                    </span>
                  </div>
                </div>
                <span className="font-mono text-xs text-mute">
                  {t.bpm ? `${t.bpm} BPM` : "—"}
                </span>
                <span className="font-mono text-[11px] text-ember px-2 py-0.5 border border-line2 text-center">
                  {t.camelot_key ?? "—"}
                </span>
                <div className="flex gap-0.5">
                  {Array.from({ length: 10 }).map((_, k) => (
                    <span
                      key={k}
                      className={
                        "flex-1 h-3 " +
                        (k < energyFor(t) ? "bg-ember" : "bg-line2")
                      }
                    />
                  ))}
                </div>
                <span className="text-faint cursor-default text-sm" />
              </li>
            ))}
          </ul>
        </section>

        {/* ── Right: critic ── */}
        <aside className="border-l border-line bg-surf px-7 py-7 flex flex-col gap-[18px]">
          <div>
            <Crumb tone="ember">note from the critic</Crumb>
            <h3 className="font-display italic font-normal text-3xl tracking-display-snug m-0 mt-1.5 leading-[1.05]">
              &ldquo;{fixCount} fix{fixCount === 1 ? "" : "es"},
              <br />
              {okCount} win.&rdquo;
            </h3>
          </div>
          <div className="flex flex-col gap-3.5 flex-1 overflow-auto">
            {notes.length === 0 ? (
              session.phase === "checkpoint2" || session.phase === "complete" ? (
                <p className="text-ok text-sm leading-[1.55] font-display italic text-base">
                  Apollo found nothing to fix.
                </p>
              ) : (
                <p className="text-mute text-sm leading-[1.55]">
                  No critic notes yet. The agent may still be analysing the
                  set — refresh once the planning phase has finished.
                </p>
              )
            ) : (
              notes.map((n: CriticNote, i) => {
                const tone =
                  n.severity === "fix"
                    ? "text-ember"
                    : n.severity === "tip"
                      ? "text-warn"
                      : "text-ok";
                const status = handledStatus.get(n.id);
                const isHandled = Boolean(status);
                const isPending = pending.has(n.id);
                return (
                  <article
                    key={n.id}
                    className={
                      "flex flex-col gap-1.5 pb-3.5 " +
                      (i < notes.length - 1 ? "border-b border-line " : "") +
                      (isHandled ? "opacity-50" : "")
                    }
                  >
                    <div className="flex justify-between items-baseline">
                      <span
                        className={
                          "font-mono text-[10px] uppercase tracking-mono " +
                          tone
                        }
                      >
                        {n.severity} · pos {n.target}
                      </span>
                      {(n.severity === "ok" || isHandled) && (
                        <span className="font-mono text-[10px] text-ok">
                          ✓{" "}
                          {status === "applied"
                            ? "applied"
                            : status === "ignored"
                              ? "ignored"
                              : "kept"}
                        </span>
                      )}
                    </div>
                    <div className="font-display italic text-[19px] leading-[1.2]">
                      {n.headline}
                    </div>
                    {n.body && (
                      <div className="text-xs text-mute leading-[1.55]">
                        {n.body}
                      </div>
                    )}
                    {n.suggestion && (
                      <div className="font-mono text-[11px] text-warn pt-1.5">
                        → {n.suggestion}
                      </div>
                    )}
                    {!isHandled && n.severity !== "ok" && (
                      <div className="flex gap-2 mt-2">
                        <Btn
                          className="px-3 py-[7px] text-[11px]"
                          onClick={() => handleApply(n.id)}
                          disabled={isPending}
                          aria-busy={isPending}
                        >
                          {isPending ? (
                            <>
                              <Spinner /> Applying
                            </>
                          ) : (
                            "Apply"
                          )}
                        </Btn>
                        <Btn
                          kind="ghost"
                          className="px-3 py-[7px] text-[11px]"
                          onClick={() =>
                            router.push(`/editor?session=${session.id}`)
                          }
                          disabled={isPending}
                        >
                          Edit
                        </Btn>
                        <Btn
                          kind="quiet"
                          className="px-1 py-[7px] text-[11px]"
                          onClick={() => handleIgnore(n.id)}
                          disabled={isPending}
                        >
                          ignore
                        </Btn>
                      </div>
                    )}
                  </article>
                );
              })
            )}
          </div>
          <div className="flex flex-col gap-2.5 pt-2 border-t border-line">
            <Crumb>then</Crumb>
            <button
              onClick={() => router.push(`/live?session=${session.id}`)}
              className="bg-ember text-cream border-0 px-4 py-3.5 flex flex-col items-start gap-0.5 cursor-pointer text-left font-sans hover:brightness-110"
            >
              <span className="font-mono text-[10px] uppercase tracking-mono text-[rgba(255,255,255,0.7)]">
                route b · live
              </span>
              <span className="font-display italic text-[20px] leading-tight">
                Apollo, take the booth →
              </span>
            </button>
            <button
              onClick={() => router.push(`/render?session=${session.id}`)}
              className="bg-cream text-ink border-0 px-4 py-3.5 flex flex-col items-start gap-0.5 cursor-pointer text-left font-sans hover:brightness-95"
            >
              <span className="font-mono text-[10px] uppercase tracking-mono text-ember-dark">
                route a · async
              </span>
              <span className="font-display italic text-[20px] leading-tight">
                Render to YouTube →
              </span>
            </button>
            <button
              onClick={() => router.push(`/editor?session=${session.id}`)}
              className="bg-transparent text-mute border border-line2 px-4 py-2.5 cursor-pointer text-center font-sans text-xs hover:text-ember-text"
            >
              Edit by hand first
            </button>
          </div>
        </aside>
      </div>
    </Shell>
  );
}
