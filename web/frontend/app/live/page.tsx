"use client";
/**
 * Apollo v2.6.0 — Live (Audience · Booth · Immersive).
 *
 * Wires the existing production ``useLiveSession`` audio engine into the
 * prototype's three-mode layout. The hook owns the dual-deck `<audio>`
 * plumbing, AudioContext gain ramps, heartbeat, stuck detection, and
 * autoplay unlock — this page is a thin presentation layer plus an
 * autoplay overlay that defers the first deck.play() until the user
 * gestures.
 *
 * Mode switching happens in-place via the segmented control and the
 * URL hash (``#audience`` / ``#cabin`` / ``#immersive``) so reloads
 * remember the active layout.
 *
 * Visualizer:
 *   - Audience mode keeps the static ``<Particles>`` decoration — it's
 *     a poster, no audio reactivity needed.
 *   - Cabin + Immersive swap in the production ``<VisualLayer>`` which
 *     reads ``live.audioRef.current.currentTime`` + beatgrid for sync.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSession, youtubeOAuthStartUrl } from "@/lib/api";
import { getToken, useAuth } from "@/lib/auth";
import { useAuthQueryBootstrap } from "@/lib/auth-bootstrap";
import { useAutoSession } from "@/lib/auto-session";
import {
  useLiveSession,
  type LiveCommand,
} from "@/lib/live";
import type { SessionState } from "@/lib/types";
import VisualLayer from "@/components/VisualLayer";
import {
  ApolloMark,
  Btn,
  Crumb,
  Mic,
  Particles,
} from "@/components/ember/primitives";
import {
  AnimatePresence,
  modeVariants,
  motion,
} from "@/components/ember/motion";
import { Banner, toast } from "@/components/ember/feedback";

type Mode = "audience" | "cabin" | "immersive";

const MODES: ReadonlyArray<[Mode, string]> = [
  ["audience", "Audience"],
  ["cabin", "Booth"],
  ["immersive", "Immersive"],
];

const INTENT_BUTTONS: ReadonlyArray<[LiveCommand["type"], string]> = [
  ["skip", "skip"],
  ["stay", "stay"],
  ["more_energetic", "more energy"],
  ["wind_down", "wind down"],
];

function formatMMSS(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function isMode(s: string): s is Mode {
  return s === "audience" || s === "cabin" || s === "immersive";
}

export default function LivePage() {
  const router = useRouter();
  const { user } = useAuth();
  // Hand off an `?auth=<jwt>` token to localStorage before the rest of
  // the page mounts — lets OBS Browser Sources sign in by URL since
  // they don't share localStorage with the operator's main browser.
  const { bootstrapping: authBootstrapping } = useAuthQueryBootstrap();
  const auto = useAutoSession("editing-or-later");
  const sessionId = auto.status === "ready" ? auto.sessionId : null;

  const [session, setSession] = useState<SessionState | null>(null);
  const [mode, setMode] = useState<Mode>("audience");
  const [cmd, setCmd] = useState("");
  // Tracks whether the user has tapped the audio gate at least once.
  // We dismiss the overlay immediately after the gesture even if the
  // engine hasn't yet flipped state out of "idle" — otherwise the
  // overlay would keep covering the screen during the cold-start
  // window between WS open and the first track_started event.
  const [hasGestured, setHasGestured] = useState(false);
  // v2.7.2 — viewer mode. When ``?viewer=1`` is in the URL, the page
  // attaches to the session's engine event bus via the read-only
  // ``/api/sessions/{id}/live/viewer`` WS. The UI stays identical to
  // the operator's view (mode switcher, chat panel, banners, YT pill)
  // so an OBS Browser Source captures the full ``/live`` look. The
  // outbound rails (chat send, skip, endless toggle, quit) silently
  // no-op in the underlying hook. We only hide two buttons here:
  // ``Quit`` (viewers can't end the session) and the OBS feed copy
  // (would just produce a self-referential URL).
  const [isViewer, setIsViewer] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setIsViewer(params.get("viewer") === "1");
  }, []);

  // Read the active mode from the URL hash on mount + sync future
  // changes back to the hash so reloads / "Show controls" navigation
  // stick to the user's choice.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const initial = window.location.hash.slice(1);
    if (isMode(initial)) setMode(initial);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.hash !== `#${mode}`) {
      window.history.replaceState(null, "", `#${mode}`);
    }
  }, [mode]);

  const live = useLiveSession(sessionId, { viewer: isViewer });

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSession(s);
      })
      .catch(() => {
        if (cancelled) return;
        router.push("/dashboard");
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, router]);

  // Use the session's full Track[] (has `genre`) as the source of truth
  // for display metadata; the engine's LiveTrackSummary lacks genre.
  const playlist = session?.playlist ?? [];
  // Resolve current / next as full Tracks by id-lookup so we keep the
  // engine's authoritative position pointer but read the richer Track
  // shape (genre, ratings, etc.) for the panels.
  const t = useMemo(() => {
    const id = live.currentTrack?.id ?? playlist[0]?.id;
    return playlist.find((p) => p.id === id) ?? playlist[0] ?? null;
  }, [live.currentTrack?.id, playlist]);
  const next = useMemo(() => {
    const id = live.nextTrack?.id;
    if (!id) return null;
    return playlist.find((p) => p.id === id) ?? null;
  }, [live.nextTrack?.id, playlist]);

  const sendChat = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const text = cmd.trim();
      if (!text) return;
      live.sendUserMessage(text);
      setCmd("");
    },
    [cmd, live],
  );

  const handleIntent = useCallback(
    (type: LiveCommand["type"]) => {
      live.sendCommand({ type });
    },
    [live],
  );

  const counter = useMemo(() => {
    const cur = live.currentPosition || (playlist.length > 0 ? 1 : 0);
    const total = playlist.length;
    if (!total) return "—";
    return `${String(cur).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
  }, [live.currentPosition, playlist.length]);

  // ── Crossfade / progress derivations (drive the animated waveform +
  //    "transition incoming" banner). ───────────────────────────────
  const dur = live.currentTrackDuration || 0;
  const pos = live.currentTrackTime || 0;
  const progressFrac = dur > 0 ? Math.min(1, Math.max(0, pos / dur)) : 0;
  const cfCountdown = live.secondsToCrossfade;
  // Reconstruct the absolute crossfade-start position. When the engine
  // has emitted cf_point_sec, secondsToCrossfade is derived as
  // (cf_point_sec - currentTrackTime), so adding currentTime back
  // recovers cf_point_sec. Falls back to a 12 s window before track
  // end so the waveform still renders something meaningful in the
  // legacy path.
  const cfSec =
    Number.isFinite(cfCountdown) && cfCountdown > 0
      ? pos + cfCountdown
      : dur > 0
        ? dur - 12
        : 0;
  const crossfadeFrac = dur > 0 ? Math.min(1, Math.max(0, cfSec / dur)) : 0.85;
  const crossfadeImminent =
    next != null &&
    Number.isFinite(cfCountdown) &&
    cfCountdown > 0 &&
    cfCountdown <= 15;
  const crossfadeActive = live.state === "crossfading";

  if (
    authBootstrapping ||
    auto.status !== "ready" ||
    !session ||
    playlist.length === 0 ||
    !t
  ) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ink text-ember-text font-sans">
        <p className="font-mono text-xs text-faint uppercase tracking-mono">
          {auto.status === "redirect"
            ? "Redirecting…"
            : authBootstrapping
              ? "Signing in…"
              : "Loading session…"}
        </p>
      </div>
    );
  }

  const broadcastingLabel =
    live.state === "ended"
      ? "⊘ session ended"
      : live.connected
        ? "● broadcasting"
        : "○ connecting…";

  return (
    <div className="min-h-screen flex flex-col bg-ink text-ember-text font-sans relative">
      {/* Live-mode header (replaces the Shell nav per prototype's hideNav) */}
      <header className="flex justify-between items-center px-9 py-3.5 border-b border-line bg-surf relative z-30">
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="flex items-baseline gap-3.5">
            <ApolloMark size={22} />
          </Link>
          <span className="text-mute">|</span>
          <span
            className={
              "font-mono text-[11px] uppercase tracking-[0.22em] " +
              (live.connected ? "text-ember" : "text-faint")
            }
          >
            {broadcastingLabel}
          </span>
          <Crumb>
            {counter} · {session.session_name ?? session.genre ?? "live set"}
          </Crumb>
        </div>

        <div className="flex gap-1 p-[3px] border border-line2">
          {MODES.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              className={
                "px-4 py-1.5 text-xs font-sans cursor-pointer " +
                (mode === id
                  ? "bg-cream text-ink"
                  : "bg-transparent text-mute hover:text-ember-text")
              }
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {/* v2.6.0 — endless / improvisation mode toggle. When ON,
              the engine emits playlist_running_low ~30 s before the
              last crossfade so the agent (and the operator) get a
              clear deadline to extend the set. Designed for
              unattended YouTube streaming. */}
          <button
            onClick={() => live.setEndlessMode(!live.endlessMode)}
            disabled={!live.connected}
            title={
              live.endlessMode
                ? "Endless mode ON — Apollo will pick continuation tracks when the queue runs low. Click to disable."
                : "Endless mode OFF — set ends on the last planned track. Click to enable (for YouTube streams)."
            }
            className={
              "px-3.5 py-2 text-xs font-sans cursor-pointer transition-colors " +
              "border " +
              (live.endlessMode
                ? "bg-ember text-cream border-ember"
                : "bg-transparent text-mute border-line2 hover:text-ember-text")
            }
          >
            ♾ Endless: {live.endlessMode ? "on" : "off"}
          </button>

          {/* v2.7 — YouTube Live Chat ingest pill. Only renders when
              the backend has actually emitted a youtube_status event
              (state !== "off"), which means YT is configured server-side
              AND the user has linked their channel. Click behaviour
              depends on state — see the per-branch handlers below. */}
          {live.youtube.state !== "off" && (
            <button
              onClick={() => {
                if (live.youtube.state === "no_broadcast") {
                  window.open("https://studio.youtube.com/", "_blank", "noopener,noreferrer");
                  return;
                }
                if (live.youtube.state === "disconnected") {
                  window.open(youtubeOAuthStartUrl(), "yt-oauth", "width=500,height=700");
                }
                // connected / quota_exceeded / error: noop (informational)
              }}
              title={
                live.youtube.state === "connected"
                  ? `YouTube Live: chat ingest from "${live.youtube.broadcastTitle ?? "active broadcast"}"`
                  : live.youtube.state === "no_broadcast"
                    ? "YouTube linked, but no active broadcast — click to open YouTube Studio"
                    : live.youtube.state === "quota_exceeded"
                      ? "YouTube API quota exceeded — polling at reduced cadence (60 s)"
                      : live.youtube.state === "disconnected"
                        ? `YouTube disconnected${live.youtube.reason ? ` (${live.youtube.reason})` : ""} — click to reconnect`
                        : "YouTube error — see console"
              }
              className={
                "px-3.5 py-2 text-xs font-sans transition-colors border " +
                (live.youtube.state === "connected"
                  ? "bg-red-600/15 text-red-300 border-red-600/40"
                  : live.youtube.state === "quota_exceeded"
                    ? "bg-warn/10 text-warn border-warn/40 cursor-default"
                    : live.youtube.state === "no_broadcast"
                      ? "bg-transparent text-mute border-line2 hover:text-ember-text cursor-pointer"
                      : "bg-transparent text-faint border-line2 hover:text-ember-text cursor-pointer")
              }
            >
              ▶ YT:{" "}
              {live.youtube.state === "connected"
                ? (live.youtube.broadcastTitle?.slice(0, 24) ?? "live")
                : live.youtube.state === "no_broadcast"
                  ? "no broadcast"
                  : live.youtube.state === "quota_exceeded"
                    ? "quota"
                    : live.youtube.state === "disconnected"
                      ? "disconnected"
                      : "error"}
            </button>
          )}

          {sessionId && !isViewer && (
            <Btn
              kind="ghost"
              className="px-3.5 py-2 text-xs"
              onClick={async () => {
                // v2.7.2 — OBS Browser Source URL.
                // The link points at the same ``/live`` route the
                // operator is using, plus ``viewer=1`` so the page
                // attaches to the read-only viewer WS instead of the
                // primary live stream. Two ``/live`` tabs (operator +
                // OBS) therefore coexist on the same session without
                // contending in the WS manager — the OBS tab is just
                // a fan-out subscriber. ``session=<sid>`` makes the
                // URL deterministic; ``auth=<jwt>`` is consumed and
                // stripped by the auth-bootstrap hook on first load.
                const token = getToken() ?? "";
                const params = new URLSearchParams();
                params.set("session", sessionId);
                if (token) params.set("auth", token);
                params.set("viewer", "1");
                const url = `${window.location.origin}/live?${params.toString()}`;
                try {
                  await navigator.clipboard.writeText(url);
                  toast.ok(
                    "OBS feed URL copied. Paste into a Browser Source in OBS — you'll see the same /live layout (mode switcher, chat, visuals) in read-only mode.",
                    { duration: 10_000 },
                  );
                } catch {
                  toast.info(
                    "OBS feed URL is on screen — copy it into a Browser Source.",
                    { duration: 12_000 },
                  );
                }
              }}
              title="Copies the OBS Browser Source URL — same /live page, viewer mode (read-only). Both your operator tab and OBS can stay open at the same time."
            >
              OBS feed ↗
            </Btn>
          )}
          {!isViewer && (
            <Btn
              kind="ghost"
              className="px-3.5 py-2 text-xs"
              onClick={() => {
                if (confirm("End the live session?")) {
                  live.quit();
                  router.push("/dashboard");
                }
              }}
            >
              Quit
            </Btn>
          )}
        </div>
      </header>

      {/* WS reconnect / engine error banner — non-blocking, sits below the
          header. Audio keeps playing during transient disconnects. */}
      {!live.connected && live.state !== "idle" && (
        <Banner tone="warn" className="m-3">
          Reconnecting to the live engine…
        </Banner>
      )}
      {live.error && (
        <Banner tone="error" className="m-3">
          {live.error}
        </Banner>
      )}
      {/* v2.6.0 — endless mode "running low" banner. Cleared on the
          next track_started (handled inside useLiveSession). */}
      {live.endlessMode && live.playlistRunningLow && (
        <Banner tone="info" className="m-3">
          Last track in the queue — Apollo is picking a continuation…
        </Banner>
      )}

      {/* v2.7.2 — chat overlay visible in Audience + Immersive modes.
          Booth mode renders its own integrated chat panel as part of
          the right column (see below), so we suppress this overlay
          there to avoid showing the feed twice. The feed reflects
          ``dj_chat`` events from the agent (``emit_chat``) plus
          YouTube Live Chat messages relayed by ``_on_yt_message`` in
          the backend — both paths share this rail. */}
      {mode !== "cabin" && live.djChat.length > 0 && (
        <aside
          aria-label="apollo chat"
          className="fixed bottom-9 left-9 z-20 max-w-[34ch] flex flex-col gap-1.5 pointer-events-none"
        >
          {live.djChat.slice(-4).map((m, i) => (
            <div
              key={`${m.ts}-${i}`}
              className="font-display italic text-lg text-cream/85 leading-snug bg-black/35 px-3 py-1.5 backdrop-blur-sm"
            >
              <span className="text-ember mr-1.5">‹</span>
              {m.text}
            </div>
          ))}
        </aside>
      )}

      <AnimatePresence mode="wait">
        {mode === "audience" && (
          <motion.div
            key="audience"
            variants={modeVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className="flex-1 relative bg-black grid place-items-center overflow-hidden p-10"
          >
            <div
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse at 50% 50%, rgba(232,85,58,0.20), transparent 70%)",
              }}
            />
            <Particles count={60} />
            <div className="absolute top-7 left-9 right-9 flex justify-between">
              <Crumb tone="ember">track {counter}</Crumb>
              <Crumb tone="cream">
                {t.bpm ?? "?"} BPM · {t.camelot_key ?? "?"} · CAMELOT
              </Crumb>
            </div>
            <div className="text-center relative">
              <Crumb>now playing</Crumb>
              <h1 className="font-display italic font-normal text-[200px] leading-[0.85] text-cream tracking-[-0.05em] m-0 mt-2">
                {t.display_name}
              </h1>
              <div className="font-display text-4xl text-ember mt-4 tracking-display-snug">
                {t.genre ?? ""}
              </div>
              <div className="w-[260px] h-px bg-cream opacity-40 mx-auto my-8" />
              <div className="font-mono text-xs text-mute tracking-[0.22em] uppercase">
                apollo · live · {(session.session_name ?? "untitled").toLowerCase()}
              </div>
            </div>
            <div className="absolute bottom-7 left-9 right-9 flex justify-between items-end">
              {next ? (
                <Crumb>up next · {next.display_name}</Crumb>
              ) : (
                <Crumb>final track</Crumb>
              )}
              {crossfadeActive ? (
                <span className="font-display italic text-3xl text-ember animate-pulse">
                  ● blending into {next?.display_name ?? "next"}
                </span>
              ) : crossfadeImminent ? (
                <span className="font-display italic text-4xl text-warn animate-pulse leading-none">
                  transition in {formatMMSS(cfCountdown)}
                </span>
              ) : (
                <Crumb>crossfade in {formatMMSS(cfCountdown)}</Crumb>
              )}
            </div>
          </motion.div>
        )}

        {mode === "cabin" && (
          <motion.div
            key="cabin"
            variants={modeVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className="flex-1 grid grid-cols-1 lg:grid-cols-[1.2fr_1fr]"
          >
            <section className="px-10 py-8 flex flex-col gap-[22px] border-r border-line">
              <div>
                <Crumb>now</Crumb>
                <h2 className="font-display italic font-normal text-[56px] tracking-[-0.025em] m-0 mt-1 leading-[0.95]">
                  <span className="text-ember-text">{t.genre ?? "—"}</span>
                  <br />
                  <span className="text-ember">{t.display_name}</span>
                </h2>
                <Crumb>
                  {t.bpm ?? "?"} BPM · {t.camelot_key ?? "?"} · crossfade{" "}
                  {formatMMSS(live.secondsToCrossfade)}
                </Crumb>
              </div>

              {/* Synthetic waveform bars — real audio analysis lives
                  inside VisualLayer; here we drive the bar colours from
                  the deck's currentTime so the user gets a clear sense
                  of where the playhead sits and how close the
                  crossfade is. Bars in the crossfade-zone pulse when
                  the transition is imminent. */}
              <div
                className="relative flex items-end gap-px h-[70px]"
                aria-label="track progress"
              >
                {(() => {
                  const BARS = 80;
                  const playIdx = Math.floor(progressFrac * BARS);
                  const cfIdx = Math.floor(crossfadeFrac * BARS);
                  // v2.7.2 — prefer the real RMS envelope produced by
                  // ``main.py --build-catalog``. Legacy entries without
                  // ``waveform_peaks`` fall back to the previous
                  // synthetic sin pattern so the UI never collapses to
                  // a flat row of bars.
                  const peaks = t.waveform_peaks;
                  const peaksValid =
                    Array.isArray(peaks) && peaks.length >= BARS;
                  return Array.from({ length: BARS }).map((_, k) => {
                    const h = peaksValid
                      ? 6 + (peaks![k] ?? 0) * 60
                      : 6 + Math.abs(Math.sin(k * 0.4) * 36) + ((k * 17) % 8);
                    const inCfZone = k >= cfIdx;
                    const passed = k < playIdx;
                    const atPlayhead = k === playIdx;
                    let cls: string;
                    if (atPlayhead) {
                      cls = "bg-cream";
                    } else if (inCfZone) {
                      // Crossfade zone — warning-coloured, pulses when
                      // the transition is within 15 s.
                      cls = crossfadeImminent
                        ? "bg-warn animate-pulse"
                        : "bg-warn opacity-60";
                    } else if (passed) {
                      cls = "bg-ember";
                    } else {
                      cls = "bg-line2";
                    }
                    return (
                      <span
                        key={k}
                        className={"flex-1 transition-colors " + cls}
                        style={{ height: h }}
                      />
                    );
                  });
                })()}
                {/* Crossfade marker — vertical hairline at the trigger
                    point so the user can see "the transition starts
                    here" even when the bars themselves blur together. */}
                {dur > 0 && crossfadeFrac > 0 && crossfadeFrac < 1 && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute top-0 bottom-0 w-px bg-warn opacity-80"
                    style={{ left: `${crossfadeFrac * 100}%` }}
                  />
                )}
              </div>
              <div className="flex justify-between font-mono text-[10px] uppercase tracking-mono text-faint -mt-3">
                <span>{formatMMSS(pos)}</span>
                <span
                  className={
                    crossfadeImminent ? "text-warn animate-pulse" : ""
                  }
                >
                  {crossfadeActive
                    ? "● crossfading"
                    : `crossfade @ ${formatMMSS(cfSec)}`}
                </span>
                <span>{formatMMSS(dur)}</span>
              </div>

              {/* Intent buttons drive engine commands (skip / stay /
                  energy / wind-down). Viewer mode is read-only, so we
                  hide the strip entirely rather than render disabled
                  buttons that look broken when clicked. */}
              {!isViewer && (
                <div className="flex gap-2 flex-wrap">
                  {INTENT_BUTTONS.map(([type, label]) => (
                    <button
                      key={type}
                      onClick={() => handleIntent(type)}
                      className={
                        "px-4 py-2.5 text-[13px] font-sans cursor-pointer capitalize " +
                        "bg-transparent text-ember-text border border-line2 hover:border-ember-text"
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}

              {next && (
                <div className="border-t border-line pt-[18px]">
                  <Crumb>up next</Crumb>
                  <div className="font-display italic text-[26px] mt-1">
                    {next.display_name}{" "}
                    <span className="font-mono text-[11px] text-faint not-italic">
                      {next.bpm ?? "?"} BPM · {next.camelot_key ?? "?"}
                    </span>
                  </div>
                </div>
              )}

              <div className="mt-auto">
                {/* "talk to apollo" header + input form are operator-only —
                    a viewer's send silently no-ops in the hook, so the
                    form would just confuse anyone trying to type. The
                    dj_chat feed below stays visible so viewers still see
                    what the agent is saying. */}
                {!isViewer && (
                  <>
                    <Crumb>talk to apollo</Crumb>
                    <form
                      onSubmit={sendChat}
                      className="flex gap-2 items-center border border-line2 px-3.5 py-2.5 mt-2"
                    >
                      <Mic />
                      <input
                        value={cmd}
                        onChange={(e) => setCmd(e.target.value)}
                        placeholder='"more groove" · "darker" · "drop the energy"'
                        className="flex-1 bg-transparent border-0 text-ember-text font-sans text-[13px] outline-none placeholder:text-faint"
                      />
                      <Btn type="submit" className="px-4 py-1.5 text-[11px]">
                        Send
                      </Btn>
                    </form>
                  </>
                )}

                <div className="mt-3 flex flex-col gap-1.5 max-h-[110px] overflow-auto">
                  {live.djChat.slice(-4).map((m, i) => (
                    <div
                      key={`${m.ts}-${i}`}
                      className="font-display italic text-base text-mute"
                    >
                      <span className="text-ember mr-1.5">‹</span>
                      {m.text}
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="bg-black relative overflow-hidden flex flex-col">
              <div className="flex-1 relative">
                <VisualLayer
                  audioRef={live.audioRef}
                  currentTrack={live.currentTrack}
                />
                <div className="absolute inset-0 grid place-items-center pointer-events-none">
                  <div className="font-display italic text-[96px] text-cream opacity-90 tracking-[-0.04em] text-center max-w-[80%]">
                    {t.display_name}
                  </div>
                </div>
              </div>
            </section>
          </motion.div>
        )}

        {mode === "immersive" && (
          <motion.div
            key="immersive"
            variants={modeVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className="flex-1 relative bg-black overflow-hidden"
          >
            <VisualLayer
              audioRef={live.audioRef}
              currentTrack={live.currentTrack}
            />
            <div className="absolute inset-0 grid place-items-center px-12 pointer-events-none">
              <div
                className="font-display italic text-ember tracking-[-0.05em] leading-[0.9] text-center max-w-full"
                style={{
                  fontSize: "clamp(120px, 18vw, 280px)",
                  textShadow: "0 0 60px rgba(232,85,58,0.5)",
                }}
              >
                {t.display_name}
              </div>
            </div>
            <div className="absolute top-7 left-9 right-9 flex justify-between">
              <span className="font-mono text-[11px] text-ember uppercase tracking-[0.22em]">
                ● live
              </span>
              <Btn
                kind="ghost"
                className="bg-black/40 backdrop-blur-md px-4 py-2 text-xs"
                onClick={() => setMode("cabin")}
              >
                Show controls
              </Btn>
            </div>
            <div className="absolute bottom-7 left-9 right-9 flex justify-between text-cream font-mono text-[11px] uppercase tracking-[0.22em]">
              <span>
                {t.genre ?? "—"} · {t.bpm ?? "?"} BPM · {t.camelot_key ?? "?"}
              </span>
              <span>{counter}</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Audio gate — shown whenever the engine hasn't started playing
          (state==='idle' is the cold-start window between WS open and
          the first track_started) OR the browser explicitly blocked
          autoplay. Either case needs a user gesture; the overlay
          guarantees there is always an obvious way to begin. */}
      {(live.autoplayBlocked || (live.state === "idle" && !hasGestured)) && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center"
          style={{ backdropFilter: "blur(20px)" }}
        >
          <button
            onClick={() => {
              setHasGestured(true);
              live.resumePlayback();
            }}
            className="px-10 py-6 bg-ember text-cream font-display italic text-4xl tracking-[-0.025em] cursor-pointer hover:brightness-110"
          >
            Tap to start the set
          </button>
        </div>
      )}
    </div>
  );
}
