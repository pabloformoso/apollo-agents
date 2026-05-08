"use client";
/**
 * LiveStage — primary UI surface for the v2.5.1 live performance flow.
 *
 * The component is intentionally read-mostly: every interactive control is
 * a thin wrapper around ``useLiveSession``'s ``sendCommand`` /
 * ``sendUserMessage`` / ``quit`` helpers. State for the duration progress,
 * countdown and "now playing" card all derives from the engine events
 * received over ``/ws/live/{id}``.
 *
 * The visual layer placeholder is intentional — Agente D will swap the
 * ``data-testid="visual-slot"`` div for a real ``<VisualLayer>`` in v2.5.3.
 */

import { useEffect, useRef, useState } from "react";
import type { UseLiveSessionApi } from "@/lib/live";
import {
  createMicPerception,
  type MicPerceptionApi,
  type PerceptionSample,
} from "@/lib/mic_perception";

interface LiveStageProps {
  live: UseLiveSessionApi;
  /** Optional — surfaces session metadata for the header. Falls back to
   * the playlist length if absent. */
  durationMin?: number | null;
  sessionName?: string | null;
}

const STATE_LABEL: Record<string, string> = {
  idle: "Idle",
  playing: "Playing",
  crossfading: "Crossfade",
  ended: "Set complete",
};

export default function LiveStage({
  live,
  durationMin,
  sessionName,
}: LiveStageProps) {
  const {
    state,
    connected,
    currentTrack,
    nextTrack,
    secondsToCrossfade,
    playlist,
    currentPosition,
    currentTrackTime,
    currentTrackDuration,
    log,
    djChat,
    error,
    autoplayBlocked,
    sendCommand,
    sendUserMessage,
    sendRaw,
    resumePlayback,
    quit,
  } = live;

  const [chatInput, setChatInput] = useState("");
  const [micActive, setMicActive] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [micRmsDb, setMicRmsDb] = useState<number>(-120);
  const micApiRef = useRef<MicPerceptionApi | null>(null);
  const meterTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const djChatPanelRef = useRef<HTMLUListElement | null>(null);

  // Auto-scroll the dj_chat panel as new messages arrive. setState lives in
  // an effect cleanup pair (canonical v2.4) — the scroll itself is a DOM
  // mutation, no setState involved.
  useEffect(() => {
    const el = djChatPanelRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [djChat.length]);

  // Cleanup the mic stream on unmount so a navigation away from /live
  // releases the device immediately. Matches the v2.4 effect pattern (no
  // setState in the body — the cleanup just stops the API).
  useEffect(() => {
    return () => {
      const api = micApiRef.current;
      if (api) {
        try {
          api.stop();
        } catch {
          /* ignore — already stopped */
        }
      }
      micApiRef.current = null;
      if (meterTimerRef.current !== null) {
        clearInterval(meterTimerRef.current);
        meterTimerRef.current = null;
      }
    };
  }, []);

  const handleMicToggle = async (next: boolean) => {
    setMicError(null);
    if (next) {
      try {
        const api = createMicPerception((sample: PerceptionSample) => {
          // Forward the aggregated sample over the WS — raw audio stays
          // in this browser. The backend's phase_live ingests these into
          // its perception buffer for the agent.
          sendRaw({
            type: "perception",
            rms_db: sample.rms_db,
            onset_density_hz: sample.onset_density_hz,
            voice_likelihood: sample.voice_likelihood,
            timestamp_ms: sample.timestamp_ms,
          });
        });
        micApiRef.current = api;
        await api.start();
        setMicActive(true);
        // Drive the level meter at ~10 Hz from the API's instantaneous RMS.
        if (meterTimerRef.current === null) {
          meterTimerRef.current = setInterval(() => {
            const a = micApiRef.current;
            if (!a) return;
            setMicRmsDb(a.getCurrentRmsDb());
          }, 100);
        }
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : "could not access microphone";
        setMicError(msg);
        setMicActive(false);
        const api = micApiRef.current;
        if (api) {
          try {
            api.stop();
          } catch {
            /* ignore */
          }
        }
        micApiRef.current = null;
        if (meterTimerRef.current !== null) {
          clearInterval(meterTimerRef.current);
          meterTimerRef.current = null;
        }
      }
    } else {
      const api = micApiRef.current;
      if (api) {
        try {
          api.stop();
        } catch {
          /* ignore — already stopped */
        }
      }
      micApiRef.current = null;
      if (meterTimerRef.current !== null) {
        clearInterval(meterTimerRef.current);
        meterTimerRef.current = null;
      }
      setMicActive(false);
      setMicRmsDb(-120);
    }
  };

  // -120 dB → 0 %, -20 dB → 100 % so room-scale ambient (–60…–30 dB)
  // lands around the middle of the bar.
  const meterPct = Math.max(
    0,
    Math.min(100, ((micRmsDb + 120) / 100) * 100),
  );

  const totalTracks = playlist.length;
  // Position is 1-based and derived from the actual playlist + currentTrack
  // identity (robust to engine state races where ``playlist_remaining`` lands
  // before the playlist itself does).
  const displayedPosition = currentPosition > 0 ? currentPosition : Math.min(1, totalTracks);
  // Per-track elapsed % for the progress bar — updates every ~250 ms via
  // ``useLiveSession``'s playback tick.
  const trackPct =
    currentTrackDuration > 0
      ? Math.min(100, (currentTrackTime / currentTrackDuration) * 100)
      : 0;

  return (
    <section
      data-testid="live-stage"
      className="flex flex-col gap-6 px-4 py-6 md:px-8 max-w-5xl mx-auto"
    >
      {/* Header */}
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-[10px] tracking-widest uppercase text-muted">
              Live Performance
            </p>
            <h1 className="text-xl font-pixel text-neon">
              {sessionName ?? "Apollo LiveDJ"}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <span
              data-testid="live-state-badge"
              className={`text-[10px] tracking-widest uppercase px-2 py-1 rounded border ${
                state === "playing"
                  ? "border-neon text-neon"
                  : state === "crossfading"
                  ? "border-yellow-400 text-yellow-300"
                  : state === "ended"
                  ? "border-muted text-muted"
                  : "border-border text-muted"
              }`}
            >
              {STATE_LABEL[state] ?? state}
            </span>
            <span
              data-testid="live-connection"
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-neon" : "bg-muted"
              }`}
              aria-label={connected ? "Connected" : "Disconnected"}
            />
          </div>
        </div>

        <div className="flex items-center gap-2 text-[10px] text-muted">
          <span data-testid="live-position">
            Track {totalTracks > 0 ? displayedPosition : 0} of {totalTracks}
          </span>
          {durationMin ? <span>· target {durationMin} min</span> : null}
        </div>
        <div className="h-2 w-full bg-border rounded overflow-hidden">
          <div
            data-testid="live-progress-bar"
            className="h-full bg-gradient-to-r from-neon-dim to-neon"
            style={{ width: `${trackPct}%`, transition: "width 250ms linear" }}
          />
        </div>
      </header>

      {error ? (
        <div
          data-testid="live-error"
          className="border border-danger text-danger text-xs px-3 py-2 rounded"
        >
          {error}
        </div>
      ) : null}

      {/* Now playing + next */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <article
          data-testid="live-current-track"
          className="bg-surface border border-neon/40 rounded p-5 space-y-3 shadow-[0_0_24px_-10px_rgba(0,229,255,0.4)]"
        >
          <p className="text-[10px] tracking-[0.2em] uppercase text-neon">
            Now playing
          </p>
          <h2
            className="text-2xl text-[#e2e2ff] font-bold leading-tight"
            data-testid="live-current-track-name"
          >
            {currentTrack?.display_name ?? "—"}
          </h2>
          <p className="text-xs text-muted">
            {currentTrack?.bpm ? `${currentTrack.bpm} BPM` : "BPM ?"}
            {currentTrack?.camelot_key ? ` · ${currentTrack.camelot_key}` : ""}
          </p>
          <p
            className="text-sm font-bold text-neon tracking-widest uppercase"
            data-testid="live-countdown"
          >
            Crossfade in {Math.round(secondsToCrossfade)}s
          </p>
        </article>

        <article
          data-testid="live-next-track"
          className="bg-surface border border-border rounded p-5 space-y-3"
        >
          <p className="text-[10px] tracking-[0.2em] uppercase text-muted">
            Next up
          </p>
          <h2
            className="text-2xl text-[#e2e2ff] font-bold leading-tight"
            data-testid="live-next-track-name"
          >
            {nextTrack?.display_name ?? "—"}
          </h2>
          <p className="text-xs text-muted">
            {nextTrack?.bpm ? `${nextTrack.bpm} BPM` : "BPM ?"}
            {nextTrack?.camelot_key ? ` · ${nextTrack.camelot_key}` : ""}
          </p>
        </article>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button
          data-testid="live-skip"
          className="border border-border text-[#e2e2ff] px-5 py-2.5 rounded text-xs uppercase tracking-widest hover:border-neon hover:text-neon transition-colors disabled:opacity-40"
          onClick={() => sendCommand({ type: "skip" })}
          disabled={state === "ended"}
        >
          Skip
        </button>
        <button
          data-testid="live-stay"
          className="border border-border text-[#e2e2ff] px-5 py-2.5 rounded text-xs uppercase tracking-widest hover:border-neon hover:text-neon transition-colors disabled:opacity-40"
          onClick={() => sendCommand({ type: "stay" })}
          disabled={state === "ended"}
        >
          Stay
        </button>
        <button
          data-testid="live-energetic"
          className="bg-neon text-[#0a0a0f] px-5 py-2.5 rounded text-xs font-bold uppercase tracking-widest hover:bg-neon-dim transition-colors disabled:opacity-40"
          onClick={() => sendCommand({ type: "more_energetic" })}
          disabled={state === "ended"}
        >
          More energetic
        </button>
        <button
          data-testid="live-wind-down"
          className="border border-border text-[#e2e2ff] px-5 py-2.5 rounded text-xs uppercase tracking-widest hover:border-neon hover:text-neon transition-colors disabled:opacity-40"
          onClick={() => sendCommand({ type: "wind_down" })}
          disabled={state === "ended"}
        >
          Wind down
        </button>
        <button
          data-testid="live-quit"
          className="border border-danger text-danger px-5 py-2.5 rounded text-xs uppercase tracking-widest hover:bg-danger hover:text-[#0a0a0f] transition-colors ml-auto"
          onClick={quit}
        >
          Quit
        </button>
      </div>

      {/* Mic perception toggle (v2.5.2) — privacy: OFF by default, raw
          audio never leaves the browser, only aggregated metrics. */}
      <section
        data-testid="mic-perception-section"
        className="flex flex-wrap items-center gap-3 border border-border rounded px-3 py-2"
      >
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            data-testid="mic-perception-toggle"
            checked={micActive}
            onChange={(e) => {
              void handleMicToggle(e.target.checked);
            }}
            className="accent-neon"
          />
          <span className="text-[10px] tracking-widest uppercase text-muted">
            Mic perception
          </span>
        </label>
        <span className="text-[10px] text-muted">
          {micActive
            ? "Listening — only aggregated metrics leave this browser."
            : "Off — DJ ignores room ambience."}
        </span>
        {micActive ? (
          <div
            data-testid="mic-level-meter"
            className="flex items-center gap-2 ml-auto"
            aria-label={`Mic level ${Math.round(micRmsDb)} dB`}
          >
            <div className="w-32 h-2 bg-border rounded overflow-hidden">
              <div
                className="h-full bg-neon"
                style={{ width: `${meterPct}%`, transition: "width 100ms linear" }}
              />
            </div>
            <span className="text-[10px] font-mono text-muted">
              {Math.round(micRmsDb)} dB
            </span>
          </div>
        ) : null}
        {micError ? (
          <span data-testid="mic-error" className="text-[10px] text-danger">
            {micError}
          </span>
        ) : null}
      </section>

      {/* Free-form chat */}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!chatInput.trim()) return;
          sendUserMessage(chatInput);
          setChatInput("");
        }}
      >
        <input
          data-testid="live-chat-input"
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          placeholder='Talk to Apollo — "more groove", "drop the energy", anything goes'
          disabled={state === "ended"}
          className="flex-1 bg-[#0a0a0f] border border-border rounded px-3 py-2 text-sm text-[#e2e2ff] focus:outline-none focus:border-neon transition-colors disabled:opacity-40"
        />
        <button
          type="submit"
          data-testid="live-chat-send"
          className="bg-neon text-[#0a0a0f] px-4 py-2 rounded text-xs font-bold uppercase tracking-widest hover:bg-neon-dim transition-colors disabled:opacity-40"
          disabled={state === "ended" || !chatInput.trim()}
        >
          Send
        </button>
      </form>

      {/* DJ chat panel — read-only feed of v2.5.2 ``dj_chat`` events emitted
          by the agent's ``emit_chat`` tool. Empty until the DJ replies. */}
      <section
        data-testid="dj-chat-panel"
        className="border border-border rounded p-3 bg-surface"
      >
        <p className="text-[10px] tracking-widest uppercase text-muted mb-2">
          DJ chat
        </p>
        {djChat.length === 0 ? (
          <p
            data-testid="dj-chat-empty"
            className="text-[10px] text-muted italic"
          >
            (Apollo will speak when there&apos;s something to say.)
          </p>
        ) : (
          <ul
            ref={djChatPanelRef}
            data-testid="dj-chat-list"
            className="text-xs text-[#e2e2ff] space-y-1 max-h-40 overflow-y-auto"
          >
            {djChat.map((entry, i) => (
              <li
                key={`${entry.ts}-${i}`}
                data-testid="dj-chat-entry"
                className="text-neon"
              >
                ‹ {entry.text}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Visual layer placeholder — replaced by <VisualLayer /> in v2.5.3 */}
      <div
        data-testid="visual-slot"
        className="w-full h-64 bg-surface border border-border rounded flex items-center justify-center text-muted text-[10px] tracking-widest uppercase"
      >
        Visual layer — v2.5.3
      </div>

      {/* Autoplay-blocked overlay — surfaces when the browser refused to play
          without a user gesture. Click forwards to ``resumePlayback`` which
          calls ``audioCtx.resume()`` + ``el.play()``. */}
      {autoplayBlocked ? (
        <div
          data-testid="live-autoplay-overlay"
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0a0a0f]/80 backdrop-blur-sm"
        >
          <button
            data-testid="live-autoplay-resume"
            onClick={resumePlayback}
            className="bg-neon text-[#0a0a0f] px-8 py-4 rounded text-sm font-bold uppercase tracking-widest hover:bg-neon-dim transition-colors"
          >
            ▶ Click to start
          </button>
        </div>
      ) : null}

      {/* Recent commands log */}
      {log.length > 0 ? (
        <ul
          data-testid="live-log"
          className="text-xs text-muted space-y-1 max-h-40 overflow-y-auto"
        >
          {log.slice(-12).map((entry, i) => (
            <li
              key={`${entry.ts}-${i}`}
              className={
                entry.role === "user" ? "text-[#e2e2ff]" : "text-neon"
              }
            >
              {entry.role === "user" ? "› " : "‹ "}
              {entry.text}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
