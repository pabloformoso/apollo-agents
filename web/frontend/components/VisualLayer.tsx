"use client";
/**
 * VisualLayer — v2.5.3 beat-synced visual surface.
 *
 * Owns a single ``<canvas>`` (for the WebGL effects) plus an absolutely
 * positioned overlay div that the strobe effect mounts into.  An rAF loop
 * reads the active deck's ``audio.currentTime``, computes the beat clock
 * from the current track's ``beatgrid``, and dispatches it to whichever
 * effect is selected.
 *
 * v7 react-hooks compliance
 * -------------------------
 * The animation loop's body must read the latest ``currentTrack`` /
 * effect selection, but the loop itself is started inside ``useEffect``
 * so we wrap the per-frame work in a ``useEffectEvent`` callback.  That
 * means the effect dependency array stays minimal (basically the
 * audio ref + container ref) and we don't restart the rAF loop on every
 * track change.
 *
 * Fallback behaviour
 * ------------------
 * Tracks without a ``beatgrid`` show a small banner and use a synthetic
 * 120 BPM clock keyed to ``audio.currentTime``.  We deliberately do NOT
 * spin up an AnalyserNode for v2.5.3 — the WS path already shares a
 * single ``AudioContext`` with ``useLiveSession`` and adding a second
 * graph for analysis would risk double-instantiation in tests.  The
 * banner makes the degraded sync mode user-visible.
 */

import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";

import type { LiveTrackSummary } from "@/lib/live";
import {
  computeBeatClock,
  safeComputeBeatClock,
  type BeatClockResult,
} from "@/lib/visualizer/beat_clock";
import {
  createParticlesEffect,
  type ParticlesEffect,
} from "@/lib/visualizer/effects/particles";
import {
  createStrobeEffect,
  STROBE_DEFAULT_MAX_HZ,
  type StrobeEffect,
} from "@/lib/visualizer/effects/strobe";
import {
  createFractalEffect,
  type FractalEffect,
} from "@/lib/visualizer/effects/fractal";

export type VisualEffectKind = "particles" | "strobe" | "fractal";

interface VisualLayerProps {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  currentTrack: LiveTrackSummary | null;
}

const STROBE_BARS_OPTIONS = [1, 4, 8] as const;

export default function VisualLayer({ audioRef, currentTrack }: VisualLayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafIdRef = useRef<number | null>(null);

  // Effect singletons. We lazily instantiate the active one to avoid
  // initialising three.js for users who never look at this layer.
  const particlesRef = useRef<ParticlesEffect | null>(null);
  const fractalRef = useRef<FractalEffect | null>(null);
  const strobeRef = useRef<StrobeEffect | null>(null);

  // Latest selection / track — kept in refs so the rAF loop reads fresh
  // values without re-binding.
  const effectKindRef = useRef<VisualEffectKind>("particles");
  const currentTrackRef = useRef<LiveTrackSummary | null>(null);
  const strobeBarsRef = useRef<number>(4);

  const [effectKind, setEffectKindState] = useState<VisualEffectKind>("particles");
  const [strobeBars, setStrobeBars] = useState<number>(4);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Sync refs when state changes — these run inside event handlers /
  // effects with no setState, so v7 is happy.
  useEffect(() => {
    effectKindRef.current = effectKind;
  }, [effectKind]);
  useEffect(() => {
    currentTrackRef.current = currentTrack;
  }, [currentTrack]);
  useEffect(() => {
    strobeBarsRef.current = strobeBars;
  }, [strobeBars]);

  const hasBeatgrid = useMemo<boolean>(() => {
    const bg = currentTrack?.beatgrid;
    return !!bg && Number.isFinite(bg.bpm) && bg.bpm > 0;
  }, [currentTrack]);

  // ── Per-frame logic, wrapped so the rAF effect can stay stable ────────
  const tick = useEffectEvent(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const audio = audioRef.current;
    const currentTime = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    const track = currentTrackRef.current;

    let beat: BeatClockResult;
    if (track?.beatgrid) {
      beat = safeComputeBeatClock(track.beatgrid, currentTime);
    } else {
      // Fallback: synthesise a 120 BPM clock from currentTime so the
      // visuals still move.  The user sees the "degraded sync" banner.
      beat = computeBeatClock(120, 0, currentTime);
    }

    const kind = effectKindRef.current;
    if (kind === "particles") {
      const eff = particlesRef.current ?? createParticlesEffect();
      if (!particlesRef.current) {
        eff.init(canvas);
        particlesRef.current = eff;
      }
      eff.render(beat, track);
    } else if (kind === "fractal") {
      const eff = fractalRef.current ?? createFractalEffect();
      if (!fractalRef.current) {
        eff.init(canvas);
        fractalRef.current = eff;
      }
      eff.render(beat, track);
    } else if (kind === "strobe") {
      const eff = strobeRef.current ?? createStrobeEffect();
      if (!strobeRef.current) {
        eff.init(container);
        strobeRef.current = eff;
      }
      eff.render(beat, strobeBarsRef.current);
    }
  });

  // ── rAF loop ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined") return;
    let mounted = true;
    const loop = () => {
      if (!mounted) return;
      tick();
      rafIdRef.current = window.requestAnimationFrame(loop);
    };
    rafIdRef.current = window.requestAnimationFrame(loop);
    return () => {
      mounted = false;
      if (rafIdRef.current !== null) {
        window.cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
    // ``tick`` is a useEffectEvent — must NOT appear in deps (v7 rule).
  }, []);

  // ── Resize handling ──────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => {
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const rect = container.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      canvas.width = w;
      canvas.height = h;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      particlesRef.current?.resize(w, h);
      fractalRef.current?.resize(w, h);
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ── Cleanup on unmount ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      particlesRef.current?.destroy();
      fractalRef.current?.destroy();
      strobeRef.current?.destroy();
      particlesRef.current = null;
      fractalRef.current = null;
      strobeRef.current = null;
    };
  }, []);

  // When the user switches effect, dispose every WebGL effect that isn't
  // currently active. Each Three.js renderer takes exclusive ownership of
  // the canvas's GL context, so leaving stale renderers alive while a
  // new one binds the same canvas produces the artifacts reported in
  // issue #44 (fractal residue persisting under particles, FPS sag).
  // Strobe lives on a DOM overlay rather than the canvas, but we also
  // tear it down so its overlay div doesn't pile up.
  const setEffectKind = useCallback((kind: VisualEffectKind) => {
    if (kind !== "particles" && particlesRef.current) {
      particlesRef.current.destroy();
      particlesRef.current = null;
    }
    if (kind !== "fractal" && fractalRef.current) {
      fractalRef.current.destroy();
      fractalRef.current = null;
    }
    if (kind !== "strobe" && strobeRef.current) {
      strobeRef.current.destroy();
      strobeRef.current = null;
    }
    setEffectKindState(kind);
  }, []);

  // Fullscreen handling — we use the Fullscreen API on the container,
  // not document.documentElement, so the layer can be embedded inside
  // LiveStage without taking the whole page out of context.  The
  // /visual-only route makes its parent already fullscreen so the API
  // call there is essentially a no-op.
  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (typeof document === "undefined") return;
    if (!document.fullscreenElement) {
      el.requestFullscreen?.()
        .then(() => setIsFullscreen(true))
        .catch(() => {
          /* ignore — some browsers refuse without a gesture */
        });
    } else {
      document.exitFullscreen?.()
        .then(() => setIsFullscreen(false))
        .catch(() => {
          /* ignore */
        });
    }
  }, []);

  const onFsChange = useEffectEvent(() => {
    if (typeof document === "undefined") return;
    setIsFullscreen(!!document.fullscreenElement);
  });
  useEffect(() => {
    if (typeof document === "undefined") return;
    const handler = () => onFsChange();
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  return (
    <div
      ref={containerRef}
      data-testid="visual-layer"
      data-effect={effectKind}
      className="relative w-full h-full bg-black overflow-hidden rounded"
      style={{ minHeight: 256 }}
    >
      <canvas
        ref={canvasRef}
        data-testid="visual-canvas"
        className="block w-full h-full"
      />

      {/* Effect selector + fullscreen toggle */}
      <div
        data-testid="visual-controls"
        className="absolute top-2 left-2 right-2 flex flex-wrap gap-2 items-center z-10 pointer-events-none"
      >
        <div className="pointer-events-auto flex gap-1 bg-black/60 rounded p-1">
          {(["particles", "strobe", "fractal"] as const).map((k) => (
            <button
              key={k}
              data-testid={`visual-effect-${k}`}
              onClick={() => setEffectKind(k)}
              className={`text-[10px] tracking-widest uppercase px-2 py-1 rounded ${
                effectKind === k
                  ? "bg-neon text-[#0a0a0f]"
                  : "text-[#e2e2ff] hover:text-neon"
              }`}
            >
              {k}
            </button>
          ))}
        </div>

        {effectKind === "strobe" ? (
          <div className="pointer-events-auto flex gap-1 bg-black/60 rounded p-1">
            {STROBE_BARS_OPTIONS.map((n) => (
              <button
                key={n}
                data-testid={`strobe-bars-${n}`}
                onClick={() => setStrobeBars(n)}
                className={`text-[10px] tracking-widest uppercase px-2 py-1 rounded ${
                  strobeBars === n
                    ? "bg-neon text-[#0a0a0f]"
                    : "text-[#e2e2ff] hover:text-neon"
                }`}
              >
                {`every ${n}`}
              </button>
            ))}
          </div>
        ) : null}

        <button
          data-testid="visual-fullscreen"
          onClick={toggleFullscreen}
          className="pointer-events-auto ml-auto bg-black/60 text-[#e2e2ff] hover:text-neon text-[10px] tracking-widest uppercase px-2 py-1 rounded"
        >
          {isFullscreen ? "exit fs" : "fullscreen"}
        </button>
      </div>

      {/* Degraded-sync banner */}
      {!hasBeatgrid && currentTrack ? (
        <div
          data-testid="visual-fallback-banner"
          className="absolute bottom-2 left-2 right-2 z-10 bg-yellow-900/60 border border-yellow-400 text-yellow-200 text-[10px] tracking-widest uppercase rounded px-2 py-1 text-center"
        >
          Degraded sync — this track has no beatgrid (run python main.py
          --generate-beatgrid)
        </div>
      ) : null}

      {/* Strobe safety hint — surfaced when the cap allows above 3 Hz */}
      {effectKind === "strobe" && STROBE_DEFAULT_MAX_HZ > 3 ? (
        <div
          data-testid="strobe-safety-warning"
          className="absolute bottom-2 left-2 right-2 z-10 bg-danger/30 border border-danger text-danger text-[10px] tracking-widest uppercase rounded px-2 py-1 text-center"
        >
          Strobe rate above safety threshold (3 Hz)
        </div>
      ) : null}
    </div>
  );
}
