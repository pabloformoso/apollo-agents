"use client";
/**
 * Apollo v2.6.0 — Render.
 *
 * Two-column layout:
 *   - Left: vinyl-press copy + cover stripe placeholder + Download MP4 /
 *     Copy YouTube description / (placeholder) Upload to YouTube.
 *   - Right: live progress with five stages (stems · crossfades · master ·
 *     cover · encode) and a chapters table read from the backend's
 *     ``transitions.json``.
 *
 * Wiring (v2.6.0):
 *   - On mount, polls ``GET /api/sessions/:id/render/status``. If a job
 *     is running we re-subscribe; if it already completed we render the
 *     final state without spawning a new one. If neither and the session
 *     phase isn't yet "complete", we POST ``/render`` to start.
 *   - SSE stream via ``subscribeRender`` (``lib/render-stream.ts``) feeds
 *     stage / pct / eta into state.
 *   - Download MP4 fires a query-token URL via ``renderAssetUrl``.
 *   - YouTube upload is out of scope for v2.6.0 — the button is
 *     disabled with a tooltip and a sibling "Copy description" action
 *     pulls ``youtube.md`` into the clipboard.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getSession, getRenderStatus, startRender } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAutoSession } from "@/lib/auto-session";
import {
  subscribeRender,
  renderAssetUrl,
  type RenderAssets,
  type RenderChapter,
  type RenderFrame,
} from "@/lib/render-stream";
import type { SessionState } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import {
  Arrow,
  Btn,
  Crumb,
  Stripe,
} from "@/components/ember/primitives";
import { Banner, Spinner, toast } from "@/components/ember/feedback";

const STAGE_ORDER: ReadonlyArray<[string, string]> = [
  ["stems", "Stems aligned"],
  ["crossfades", "Crossfades rendered"],
  ["master", "Mastering · -14 LUFS"],
  ["cover", "Cover composed"],
  ["encode", "MP4 encoded · 1080p"],
];

function formatTimestamp(ms: number): string {
  const total = Math.floor(ms / 1000);
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export default function RenderPage() {
  const router = useRouter();
  const { user } = useAuth();
  const auto = useAutoSession("playlist");
  const sessionId = auto.status === "ready" ? auto.sessionId : null;

  const [session, setSession] = useState<SessionState | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [eta, setEta] = useState<number | null>(null);
  const [assets, setAssets] = useState<RenderAssets | null>(null);
  const [chapters, setChapters] = useState<RenderChapter[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  // 1s clock for elapsed display.
  useEffect(() => {
    if (pct >= 100) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [pct]);

  // Initial session fetch — also covers the "session.phase === complete"
  // case where we should NOT auto-kick a new render.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSession(s);
        if (s.phase === "complete") setPct(100);
      })
      .catch(() => {
        if (cancelled) return;
        router.push("/dashboard");
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, router]);

  // Main lifecycle: probe status → start if needed → subscribe SSE.
  useEffect(() => {
    if (!sessionId || !session) return;
    let cancelled = false;
    let handle: { close: () => void } | null = null;

    const subscribe = () => {
      if (cancelled) return;
      setStartedAt((prev) => prev ?? Date.now());
      handle = subscribeRender(sessionId, {
        onFrame: (f: RenderFrame) => {
          if (cancelled) return;
          if (f.stage) setStage(f.stage);
          setPct(f.pct);
          setEta(f.etaSeconds);
          setReconnecting(null);
        },
        onDone: ({ assets: a, chapters: ch }) => {
          if (cancelled) return;
          setAssets(a);
          setChapters(ch);
          setPct(100);
          setEta(0);
          setStage("encode");
          setReconnecting(null);
          // Refresh session so phase reflects "complete".
          getSession(sessionId)
            .then((s) => !cancelled && setSession(s))
            .catch(() => {});
        },
        onError: (msg, terminal) => {
          if (cancelled) return;
          if (terminal) {
            setError(msg);
            setReconnecting(null);
          } else {
            setReconnecting(msg);
          }
        },
      });
    };

    (async () => {
      try {
        const status = await getRenderStatus(sessionId);
        if (cancelled) return;
        if (status.running) {
          if (typeof status.pct === "number") setPct(status.pct);
          if (status.stage) setStage(status.stage);
          if (typeof status.etaSeconds === "number" || status.etaSeconds === null) {
            setEta(status.etaSeconds ?? null);
          }
          subscribe();
        } else if (status.assets) {
          // Already finished before this mount — render the final state
          // from the snapshot without spawning a new render.
          setAssets(status.assets);
          setChapters(status.chapters ?? []);
          setPct(100);
          setStage("encode");
        } else if (status.error) {
          setError(status.error);
        } else if (session.phase !== "complete") {
          // No active job + session not complete → start one.
          await startRender(sessionId);
          subscribe();
        } else {
          // Session is complete but no job entry — assets must already
          // exist on disk; surface them lazily by hitting status again.
          // For now, just show 100% and let download buttons probe the
          // server (404 on missing files is handled by the endpoint).
          setPct(100);
          setStage("encode");
          // Belt-and-braces — populate assets from a known kind list so
          // download buttons work without the SSE done frame.
          const known = ["wav", "mp4", "short", "transitions", "youtube_md"];
          setAssets(
            Object.fromEntries(
              known.map((k) => [
                k,
                `/api/sessions/${sessionId}/download/${k}`,
              ]),
            ),
          );
        }
      } catch (e) {
        if (cancelled) return;
        toast.error((e as Error).message || "Couldn't reach render service.");
        setError((e as Error).message || "Render unavailable");
      }
    })();

    return () => {
      cancelled = true;
      handle?.close();
    };
  }, [sessionId, session]);

  const stages = useMemo(() => {
    const order = STAGE_ORDER.map(([k]) => k);
    const currentIdx = stage ? order.indexOf(stage) : -1;
    return STAGE_ORDER.map(([key, label], i) => ({
      key,
      label,
      done: pct >= 100 || (currentIdx >= 0 && i < currentIdx),
      running: currentIdx === i && pct < 100,
    }));
  }, [stage, pct]);

  const tracks = session?.playlist ?? [];

  const elapsedSec = useMemo(() => {
    if (!startedAt) return 0;
    return Math.floor((now - startedAt) / 1000);
  }, [startedAt, now]);

  const onDownload = useCallback(
    (kind: string) => {
      if (!sessionId) return;
      window.location.href = renderAssetUrl(sessionId, kind);
    },
    [sessionId],
  );

  const onCopyDescription = useCallback(async () => {
    if (!sessionId) return;
    try {
      // The download endpoint serves the text directly with content-type
      // text/markdown — fetch it manually and write to clipboard.
      const url = renderAssetUrl(sessionId, "youtube_md");
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      toast.ok("YouTube description copied.");
    } catch (e) {
      toast.error((e as Error).message || "Couldn't copy description.");
    }
  }, [sessionId]);

  if (auto.status !== "ready" || !session) {
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

  const done = pct >= 100;

  return (
    <Shell
      username={user?.username ?? null}
      sessionLabel={session?.session_name ?? session?.genre ?? null}
    >
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1.1fr_1fr]">
        {/* ── Left: vinyl + actions ── */}
        <section className="px-12 py-10 border-r border-line flex flex-col gap-[22px]">
          <div>
            <Crumb tone="ember">release · async</Crumb>
            <h2 className="font-display italic font-normal text-[56px] tracking-[-0.025em] m-0 mt-1 leading-[0.95]">
              {!done ? (
                <>
                  Pressing
                  <br />
                  the vinyl<span className="text-ember">.</span>
                </>
              ) : (
                <>
                  Vinyl&apos;s
                  <br />
                  ready<span className="text-ember">.</span>
                </>
              )}
            </h2>
          </div>

          {error && (
            <Banner tone="error">
              {error}
              <button
                onClick={() => {
                  setError(null);
                  if (sessionId) {
                    startRender(sessionId).catch((e) =>
                      toast.error((e as Error).message),
                    );
                  }
                }}
                className="ml-3 font-mono text-[10px] uppercase tracking-mono text-cream cursor-pointer hover:brightness-110"
              >
                Retry
              </button>
            </Banner>
          )}

          {reconnecting && !error && (
            <Banner tone="warn">
              <Spinner /> {reconnecting}
            </Banner>
          )}

          <Stripe
            alpha={0.16}
            className="aspect-[5/7] relative p-7 flex flex-col justify-between border-line2"
          >
            <div>
              <Crumb tone="ember">APOLLO · 010</Crumb>
              <div className="font-display italic text-[56px] leading-[0.95] text-cream mt-4">
                {(session?.session_name ?? "untitled set")
                  .split(" · ")[0]
                  .toLowerCase()}
              </div>
            </div>
            <div className="font-mono text-[10px] text-mute uppercase tracking-mono leading-[1.6]">
              <div>
                {tracks.length} tracks · {Math.floor(tracks.length * 6.8)}:00
              </div>
              <div>
                {(session?.mood ?? "—")} · {(session?.genre ?? "—")}
              </div>
              <div>curated by Apollo for {user?.username ?? "you"}</div>
            </div>
          </Stripe>

          <div className="flex flex-col gap-2.5">
            <div className="flex gap-2.5">
              <Btn
                kind="cream"
                className="flex-1 justify-center"
                disabled={!done || !assets?.mp4}
                onClick={() => onDownload("mp4")}
              >
                Download MP4
              </Btn>
              <Btn
                kind="ghost"
                className="flex-1 justify-center"
                disabled
                title="YouTube auto-upload coming in v2.7 — your youtube.md is ready in the download menu."
              >
                Upload to YouTube
              </Btn>
            </div>
            {done && assets?.youtube_md && (
              <button
                onClick={onCopyDescription}
                className="font-mono text-[10px] uppercase tracking-mono text-faint hover:text-ember-text cursor-pointer text-left"
              >
                Copy YouTube description
              </button>
            )}
          </div>
        </section>

        {/* ── Right: progress + chapters ── */}
        <section className="px-12 py-10 flex flex-col gap-6">
          <div>
            <Crumb>
              render ·{" "}
              {Math.floor(elapsedSec / 60)}m{" "}
              {String(elapsedSec % 60).padStart(2, "0")}s elapsed
            </Crumb>
            <div className="flex items-baseline gap-3 mt-1.5">
              <span className="font-display italic text-[56px] text-ember">
                {Math.round(pct)}%
              </span>
              <Crumb>
                {eta == null
                  ? "calculating…"
                  : `~ ${Math.ceil(eta)}s left`}
              </Crumb>
            </div>
            <div className="h-1 bg-surf2 mt-3.5 relative">
              <div
                className="h-full bg-ember transition-[width] duration-200"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          <ul className="list-none m-0 p-0 flex flex-col gap-3">
            {stages.map((st) => (
              <li
                key={st.key}
                className="grid grid-cols-[20px_1fr_80px] items-center pb-3 border-b border-line"
              >
                <span
                  className={
                    "font-mono text-xs " +
                    (st.done
                      ? "text-ok"
                      : st.running
                        ? "text-ember"
                        : "text-faint")
                  }
                >
                  {st.done ? "✓" : st.running ? "●" : "○"}
                </span>
                <span className="font-display italic text-[19px]">
                  {st.label}
                </span>
                <span
                  className={
                    "font-mono text-[10px] uppercase tracking-mono " +
                    (st.done
                      ? "text-ok"
                      : st.running
                        ? "text-ember"
                        : "text-faint")
                  }
                >
                  {st.done ? "complete" : st.running ? "running" : "queued"}
                </span>
              </li>
            ))}
          </ul>

          {(chapters.length > 0 || tracks.length > 0) && (
            <div className="mt-auto p-[18px] bg-surf border border-line">
              <Crumb>chapters</Crumb>
              <div className="mt-2.5 flex flex-col gap-1.5 font-mono text-xs text-mute">
                {chapters.length > 0
                  ? chapters.map((c, i) => (
                      <div
                        key={i}
                        className="grid grid-cols-[44px_1fr_36px]"
                      >
                        <span className="text-ember">{formatTimestamp(c.tMs)}</span>
                        <span className="text-ember-text overflow-hidden text-ellipsis whitespace-nowrap">
                          {c.title}
                        </span>
                        <span>{c.camelot ?? "—"}</span>
                      </div>
                    ))
                  : tracks.map((t, i) => {
                      // Pre-build estimate (6.8 min/track) until the
                      // done frame brings real chapters back.
                      const total = i * 408;
                      const mm = Math.floor(total / 60);
                      const ss = total % 60;
                      return (
                        <div
                          key={t.id}
                          className="grid grid-cols-[44px_1fr_36px]"
                        >
                          <span className="text-ember">
                            {String(mm).padStart(2, "0")}:
                            {String(ss).padStart(2, "0")}
                          </span>
                          <span className="text-ember-text overflow-hidden text-ellipsis whitespace-nowrap">
                            {t.display_name}
                          </span>
                          <span>{t.camelot_key ?? "—"}</span>
                        </div>
                      );
                    })}
              </div>
            </div>
          )}

          {done && (
            <Btn
              onClick={() => router.push("/dashboard")}
              className="self-start"
            >
              Back to library <Arrow />
            </Btn>
          )}
        </section>
      </div>
    </Shell>
  );
}
