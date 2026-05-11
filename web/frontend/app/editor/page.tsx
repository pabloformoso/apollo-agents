"use client";
/**
 * Apollo v2.6.0 — Editor.
 *
 * Two-column layout:
 *   - Left: scrollable row of track cards (drag-reorder, trash on hover,
 *     "add a track" → TrackPicker), arc + transitions panel, command form.
 *   - Right rail: "Materialize" CTA + set-health bar.
 *
 * Wiring (v2.6.0):
 *   - Deterministic gestures (drag, trash, add) → REST endpoints under
 *     ``/api/sessions/:id/tracks/*``.
 *   - LLM command line → SSE ``POST /api/sessions/:id/editor_command``.
 *   - Set-health read from ``session.set_health`` (server-recomputed).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import {
  deleteSessionTrack,
  getSession,
  insertSessionTrack,
  reorderSessionTracks,
  streamEditorCommand,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAutoSession } from "@/lib/auto-session";
import type { SessionState, Track } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import {
  Btn,
  Crumb,
  Plus,
  Stripe,
} from "@/components/ember/primitives";
import { Spinner, toast } from "@/components/ember/feedback";
import { TrackPicker } from "@/components/ember/TrackPicker";

// Same coefficients as `web/backend/arc.py`. Pure UI fallback for legacy
// sessions whose to_dict pre-dates v2.6.0.
function energyFor(t: Track): number {
  const bpm = t.bpm ?? 60;
  return Math.max(1, Math.min(10, (bpm - 50) / 12));
}

type EditorEvent = {
  kind: "user" | "tool_call" | "tool_progress" | "tool_result" | "info" | "error";
  text: string;
};

interface CardProps {
  track: Track;
  index: number;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function TrackCard({ track, index, selected, onSelect, onDelete }: CardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: track.id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      onClick={onSelect}
      {...attributes}
      {...listeners}
      className={
        "group flex-[0_0_200px] p-4 flex flex-col gap-2.5 relative cursor-grab text-left text-ember-text " +
        (selected
          ? "border border-ember bg-[rgba(232,85,58,0.08)]"
          : "border border-line bg-surf hover:border-line2") +
        (isDragging ? " cursor-grabbing" : "")
      }
    >
      <div className="flex justify-between">
        <span className="font-display italic text-[22px] text-faint">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="font-mono text-[10px] text-mute">
          {track.bpm ?? "?"}·{track.camelot_key ?? "?"}
        </span>
      </div>
      <Stripe alpha={0.18} className="aspect-square" />
      <div className="font-display italic text-lg leading-[1.1]">
        {track.display_name}
      </div>
      <div className="text-[11px] text-mute">{track.genre ?? "—"}</div>
      <div className="flex gap-px">
        {Array.from({ length: 10 }).map((_, k) => (
          <span
            key={k}
            className={
              "flex-1 h-1.5 " +
              (k < energyFor(track) ? "bg-ember" : "bg-line2")
            }
          />
        ))}
      </div>
      {selected && (
        <span className="absolute -top-2.5 -right-2.5 bg-ember text-cream font-mono text-[9px] px-2 py-[3px] uppercase tracking-[0.14em]">
          editing
        </span>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Remove track"
        title="Remove track"
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-surf2/80 border border-line2 text-faint hover:text-ember w-6 h-6 flex items-center justify-center text-[11px] cursor-pointer"
      >
        ✕
      </button>
    </div>
  );
}

export default function EditorPage() {
  const router = useRouter();
  const { user } = useAuth();
  const auto = useAutoSession("playlist");
  const sessionId = auto.status === "ready" ? auto.sessionId : null;

  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<number>(0);
  const [cmd, setCmd] = useState("");
  const [events, setEvents] = useState<EditorEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true);
    getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSession(s);
        if (s.playlist && s.playlist.length > 0) {
          setSel((prev) => Math.min(prev, s.playlist.length - 1));
        }
      })
      .catch(() => {
        if (cancelled) return;
        router.push("/dashboard");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, router]);

  const tracks = useMemo(() => session?.playlist ?? [], [session?.playlist]);

  const setHealth = useMemo(() => {
    if (typeof session?.set_health === "number") return session.set_health;
    // Fallback formula for legacy sessions that haven't been re-served by
    // the v2.6.0 backend yet. Same coefficient as `compute_set_health`.
    const n = session?.structured_problems?.length ?? 0;
    return Math.max(0, Math.min(100, 100 - 6 * n));
  }, [session?.set_health, session?.structured_problems]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const onDragEnd = useCallback(
    async (e: DragEndEvent) => {
      if (!sessionId || !e.over || e.active.id === e.over.id) return;
      const fromIdx = tracks.findIndex((t) => t.id === e.active.id);
      const toIdx = tracks.findIndex((t) => t.id === e.over!.id);
      if (fromIdx < 0 || toIdx < 0) return;
      const newOrder = arrayMove(
        tracks.map((_, i) => i),
        fromIdx,
        toIdx,
      );
      // Optimistic — apply locally, then call server. Rollback on failure.
      const prevSession = session;
      const newPlaylist = newOrder.map((i) => tracks[i]);
      setSession({ ...session!, playlist: newPlaylist });
      try {
        const updated = await reorderSessionTracks(sessionId, newOrder);
        setSession(updated);
      } catch (err) {
        setSession(prevSession);
        toast.error((err as Error).message || "Reorder failed.");
      }
    },
    [sessionId, tracks, session],
  );

  const onDeleteTrack = useCallback(
    async (index: number) => {
      if (!sessionId) return;
      const prev = session;
      const newPlaylist = tracks.filter((_, i) => i !== index);
      setSession({ ...session!, playlist: newPlaylist });
      try {
        const updated = await deleteSessionTrack(sessionId, index);
        setSession(updated);
        if (sel >= newPlaylist.length) {
          setSel(Math.max(0, newPlaylist.length - 1));
        }
      } catch (err) {
        setSession(prev);
        toast.error((err as Error).message || "Delete failed.");
      }
    },
    [sessionId, tracks, session, sel],
  );

  const onInsertTrack = useCallback(
    async (track: Track) => {
      if (!sessionId) return;
      const at = Math.min(sel + 1, tracks.length);
      setPickerOpen(false);
      try {
        const updated = await insertSessionTrack(sessionId, at, track.id);
        setSession(updated);
        setSel(at);
      } catch (err) {
        toast.error((err as Error).message || "Insert failed.");
      }
    },
    [sessionId, sel, tracks.length],
  );

  const runCmd = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!sessionId || !cmd.trim() || streaming) return;
      const text = cmd.trim();
      setCmd("");
      setEvents((es) => [...es, { kind: "user", text }]);
      setStreaming(true);

      await streamEditorCommand(sessionId, text, {
        onEvent: (ev) => {
          const t = ev.type as string;
          if (t === "tool_call") {
            const name = ev.name as string;
            const input = ev.input as Record<string, unknown>;
            const args = Object.entries(input ?? {})
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ");
            setEvents((es) => [
              ...es,
              { kind: "tool_call", text: `→ ${name}(${args})` },
            ]);
          } else if (t === "tool_progress") {
            setEvents((es) => [
              ...es,
              {
                kind: "tool_progress",
                text: `↳ ${ev.stage ?? ""}: ${ev.message ?? ""}`,
              },
            ]);
          } else if (t === "tool_result") {
            setEvents((es) => [
              ...es,
              {
                kind: "tool_result",
                text: `✓ ${ev.name}: ${(ev.result as string)?.slice(0, 120) ?? ""}`,
              },
            ]);
          } else if (t === "phase_complete") {
            const data = ev.data as SessionState | undefined;
            if (data) setSession(data);
            setEvents((es) => [
              ...es,
              { kind: "info", text: `phase complete: ${ev.phase}` },
            ]);
          } else if (t === "phase_start") {
            setEvents((es) => [
              ...es,
              { kind: "info", text: `phase start: ${ev.phase}` },
            ]);
          }
        },
        onDone: () => {
          setStreaming(false);
          // Re-fetch session as a belt-and-braces sync (phase_complete
          // payload already carried the new state but a stale tab might
          // have missed it).
          if (sessionId) {
            getSession(sessionId)
              .then(setSession)
              .catch(() => {});
          }
        },
        onError: (msg) => {
          setStreaming(false);
          setEvents((es) => [...es, { kind: "error", text: msg }]);
          toast.error(msg);
        },
      });
    },
    [sessionId, cmd, streaming],
  );

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
  if (!session || tracks.length === 0) {
    return (
      <Shell username={user?.username ?? null}>
        <section className="flex-1 flex flex-col items-center justify-center gap-4">
          <Crumb>your move</Crumb>
          <p className="text-mute">No playlist yet.</p>
          <Btn
            kind="ghost"
            onClick={() => router.push(`/curate?session=${sessionId}`)}
          >
            Back to curate
          </Btn>
        </section>
      </Shell>
    );
  }

  return (
    <Shell
      username={user?.username ?? null}
      sessionLabel={session.session_name ?? session.genre ?? null}
    >
      {/* `minmax(0, 1fr)` clamps the center column to the leftover space so
          the horizontally-scrolling track row inside can't push the
          Materialize rail off-screen. Without this, CSS Grid's default
          `min-width: auto` on a 1fr column lets long content expand the
          column past its allocated width and the right rail vanishes. */}
      <div className="flex-1 grid grid-cols-[minmax(0,1fr)_320px]">
        {/* ── Center: track row + arc + command ── */}
        <section className="px-12 py-8 flex flex-col gap-[22px] min-w-0">
          <div>
            <Crumb tone="ember">your move</Crumb>
            <h2 className="font-display italic font-normal text-[44px] tracking-display-snug m-0 mt-1">
              Sequence the night<span className="text-ember">.</span>
            </h2>
          </div>

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={onDragEnd}
          >
            <SortableContext
              items={tracks.map((t) => t.id)}
              strategy={horizontalListSortingStrategy}
            >
              <div className="flex gap-3 overflow-auto pb-2">
                {tracks.map((t, i) => (
                  <TrackCard
                    key={t.id}
                    track={t}
                    index={i}
                    selected={i === sel}
                    onSelect={() => setSel(i)}
                    onDelete={() => onDeleteTrack(i)}
                  />
                ))}
                <button
                  onClick={() => setPickerOpen(true)}
                  className="flex-[0_0_200px] p-4 flex flex-col items-center justify-center gap-2 border border-dashed border-line2 bg-transparent text-faint cursor-pointer hover:text-ember-text hover:border-line2"
                >
                  <Plus />
                  <span className="text-xs">Add a track</span>
                </button>
              </div>
            </SortableContext>
          </DndContext>

          {/* arc + transitions */}
          <div className="bg-surf border border-line p-[18px]">
            <div className="flex justify-between mb-3">
              <Crumb>arc &amp; transitions</Crumb>
            </div>
            <svg
              viewBox="0 0 500 80"
              preserveAspectRatio="none"
              className="w-full h-20"
            >
              <line
                x1="0"
                y1="60"
                x2="500"
                y2="60"
                stroke="var(--line2)"
                strokeDasharray="3 3"
              />
              <path
                d={tracks
                  .map((t, i) => {
                    const x = (i + 0.5) * (500 / tracks.length);
                    const y =
                      60 -
                      (session.arc?.points?.[i] ?? energyFor(t)) * 4;
                    return `${i === 0 ? "M" : "L"}${x} ${y}`;
                  })
                  .join(" ")}
                stroke="var(--ember)"
                strokeWidth="1.5"
                fill="none"
              />
              {tracks.map((t, i) => (
                <g
                  key={i}
                  transform={`translate(${(i + 0.5) * (500 / tracks.length)}, 0)`}
                >
                  <circle
                    cx="0"
                    cy={60 - (session.arc?.points?.[i] ?? energyFor(t)) * 4}
                    r="3"
                    fill={i === sel ? "var(--ember)" : "var(--cream)"}
                  />
                  <text
                    x="0"
                    y="78"
                    textAnchor="middle"
                    fontFamily="var(--font-jetbrains-mono)"
                    fontSize="9"
                    fill="var(--faint)"
                  >
                    {t.camelot_key ?? "—"}
                  </text>
                </g>
              ))}
            </svg>
          </div>

          {/* command line */}
          <form
            onSubmit={runCmd}
            className="flex gap-2 items-center border border-line2 bg-surf px-4 py-3"
          >
            <span className="font-mono text-[11px] text-ember">›</span>
            <input
              value={cmd}
              onChange={(e) => setCmd(e.target.value)}
              placeholder='swap track 3 · build "garden-chill" · add brian-cid—errors'
              disabled={streaming}
              className="flex-1 bg-transparent border-0 text-ember-text font-mono text-[13px] outline-none placeholder:text-faint disabled:opacity-60"
            />
            <Btn
              kind="cream"
              className="px-4 py-[7px] text-[11px]"
              type="submit"
              disabled={streaming || !cmd.trim()}
            >
              {streaming ? (
                <>
                  <Spinner /> Running
                </>
              ) : (
                "Run"
              )}
            </Btn>
          </form>
          {events.length > 0 && (
            <ul className="font-mono text-[11px] flex flex-col gap-1 max-h-[200px] overflow-auto">
              {events.slice(-12).map((ev, i) => {
                const tone =
                  ev.kind === "user"
                    ? "text-ember-text"
                    : ev.kind === "tool_call"
                      ? "text-ember"
                      : ev.kind === "tool_progress"
                        ? "text-warn"
                        : ev.kind === "tool_result"
                          ? "text-ok"
                          : ev.kind === "error"
                            ? "text-ember"
                            : "text-faint";
                const prefix = ev.kind === "user" ? "› " : "";
                return (
                  <li key={i} className={tone}>
                    {prefix}
                    {ev.text}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ── Right rail: Materialize ── */}
        <aside className="border-l border-line bg-surf px-7 py-8 flex flex-col gap-[22px]">
          <div>
            <Crumb>then</Crumb>
            <h3 className="font-display italic font-normal text-3xl tracking-display-snug m-0 mt-1.5">
              Materialize<span className="text-ember">.</span>
            </h3>
          </div>

          <button
            onClick={() => router.push(`/render?session=${session.id}`)}
            className="bg-cream text-ink border-0 px-[18px] py-5 flex flex-col items-start gap-1.5 cursor-pointer text-left font-sans"
          >
            <span className="font-mono text-[10px] uppercase tracking-mono text-ember-dark">
              route a · async
            </span>
            <span className="font-display italic text-[26px] leading-none">
              Render to YouTube
            </span>
            <span className="text-xs text-[rgba(10,8,7,0.7)] mt-1">
              Apollo presses the vinyl. 1080p MP4 with chapters.
            </span>
          </button>

          <button
            onClick={() => router.push(`/live?session=${session.id}`)}
            className="bg-ember text-cream border-0 px-[18px] py-5 flex flex-col items-start gap-1.5 cursor-pointer text-left font-sans"
          >
            <span className="font-mono text-[10px] uppercase tracking-mono text-[rgba(255,255,255,0.7)]">
              route b · live
            </span>
            <span className="font-display italic text-[26px] leading-none">
              Apollo, take the booth
            </span>
            <span className="text-xs text-[rgba(255,255,255,0.85)] mt-1">
              Real-time mixing with mic awareness and visuals.
            </span>
          </button>

          <div className="mt-auto">
            <Crumb>set health · {setHealth} / 100</Crumb>
            <div className="h-[3px] bg-line mt-1.5 relative">
              <div
                className="h-full bg-ember"
                style={{ width: `${setHealth}%` }}
              />
            </div>
          </div>
        </aside>
      </div>

      <TrackPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        genre={session.genre ?? null}
        existingIds={tracks.map((t) => t.id)}
        onSelect={onInsertTrack}
      />
    </Shell>
  );
}
