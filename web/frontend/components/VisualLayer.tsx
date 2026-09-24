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
 *
 * 2026-09-24 — shader scenes
 * --------------------------
 * The default is now ``auto``: one of four audio-reactive shader scenes
 * (``lib/visualizer/effects/shader_scenes.ts``) picked per track by
 * ``scene_picker.autoScene`` — aurora for beatless genres, prism for
 * mid-tempo, tunnel for driving sets — painted in the track's key and
 * eased between tracks. They listen to ``analyserRef`` (a TAP on the
 * master bus that ``useLiveSession`` owns — still one audio graph) and
 * fall back to the beat clock without it. Scene changes dip through
 * black instead of cutting. The v2.5 effects stay selectable as
 * "classic". Controls fade out after a few idle seconds so a fullscreen
 * capture is clean.
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
import {
  createShaderSceneEffect,
  SHADER_SCENES,
  type ShaderSceneEffect,
} from "@/lib/visualizer/effects/shader_scenes";
import {
  bandsFromSpectrum,
  beatEnvelopes,
  createFollower,
  followFeatures,
  syntheticFeatures,
} from "@/lib/visualizer/audio_features";
import {
  autoScene,
  easeRgb,
  paletteFor,
  symmetryFor,
  type RGB,
  type ShaderScene,
} from "@/lib/visualizer/scene_picker";

export type ClassicEffectKind = "particles" | "strobe" | "fractal";
export type VisualEffectKind = "auto" | ShaderScene | ClassicEffectKind;

const CLASSIC_EFFECTS: readonly ClassicEffectKind[] = ["particles", "strobe", "fractal"];
const MODERN_EFFECTS: readonly VisualEffectKind[] = ["auto", ...SHADER_SCENES];

/** Seconds of stillness before the controls fade out. */
const CONTROLS_IDLE_MS = 3000;
/** Half of a scene change: fade to black, swap, fade back. */
const SCENE_DIP_MS = 450;

function isShaderKind(k: VisualEffectKind): k is "auto" | ShaderScene {
  return k === "auto" || (SHADER_SCENES as readonly string[]).includes(k);
}

/**
 * v3.4 — accept either an HTMLAudioElement or the BufferDeck shim
 * exposed by useLiveSession (``VisualAudioShim`` in lib/live.ts).
 * Both surface a numeric ``currentTime`` field; that's all this
 * component reads. The type widening lets the shim be passed
 * without an unsafe cast.
 */
interface AudioTimeSource {
  currentTime: number;
}

interface VisualLayerProps {
  audioRef: React.RefObject<AudioTimeSource | null>;
  currentTrack: LiveTrackSummary | null;
  /** Master-bus (or mic) analyser. Absent → scenes follow the beat clock. */
  analyserRef?: React.RefObject<AnalyserNode | null>;
  /** Initial selection; the lab page pins a scene. */
  defaultEffect?: VisualEffectKind;
}

const STROBE_BARS_OPTIONS = [1, 4, 8] as const;

export default function VisualLayer({
  audioRef,
  currentTrack,
  analyserRef,
  defaultEffect = "auto",
}: VisualLayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafIdRef = useRef<number | null>(null);

  // Effect singletons. We lazily instantiate the active one to avoid
  // initialising three.js for users who never look at this layer.
  const particlesRef = useRef<ParticlesEffect | null>(null);
  const fractalRef = useRef<FractalEffect | null>(null);
  const strobeRef = useRef<StrobeEffect | null>(null);
  const shaderRef = useRef<ShaderSceneEffect | null>(null);

  // Shader-scene state, all per-frame and therefore refs.
  const followerRef = useRef(createFollower());
  const spectrumRef = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const colorARef = useRef<RGB | null>(null);
  const colorBRef = useRef<RGB | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef<number | null>(null);
  /** Pending scene change: the scene to show once the dip reaches black. */
  const dipRef = useRef<{ to: ShaderScene; startedAt: number } | null>(null);

  // Latest selection / track — kept in refs so the rAF loop reads fresh
  // values without re-binding.
  const effectKindRef = useRef<VisualEffectKind>(defaultEffect);
  const currentTrackRef = useRef<LiveTrackSummary | null>(null);
  const strobeBarsRef = useRef<number>(4);

  const [effectKind, setEffectKindState] = useState<VisualEffectKind>(defaultEffect);
  const [shownScene, setShownScene] = useState<ShaderScene | null>(null);
  const [controlsIdle, setControlsIdle] = useState(false);
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

  // ── Shader scenes ────────────────────────────────────────────────────
  const renderShaderScene = (
    canvas: HTMLCanvasElement,
    kind: "auto" | ShaderScene,
    beat: BeatClockResult,
    track: LiveTrackSummary | null,
  ) => {
    const now = performance.now();
    const startedAt = startedAtRef.current ?? now;
    startedAtRef.current = startedAt;
    const dt = lastFrameAtRef.current === null ? 0 : (now - lastFrameAtRef.current) / 1000;
    lastFrameAtRef.current = now;

    // Which scene should be on screen, and are we mid-dip towards it?
    const wanted: ShaderScene = kind === "auto" ? autoScene(track) : kind;
    let eff = shaderRef.current;
    if (!eff) {
      eff = createShaderSceneEffect(wanted);
      eff.init(canvas);
      eff.resize(canvas.width || 1, canvas.height || 1);
      shaderRef.current = eff;
      setShownScene(wanted);
    } else if (eff.scene !== wanted && !dipRef.current) {
      dipRef.current = { to: wanted, startedAt: now };
    }
    let fade = 1;
    const dip = dipRef.current;
    if (dip) {
      const t = (now - dip.startedAt) / SCENE_DIP_MS;
      if (t >= 1 && eff.scene !== dip.to) {
        eff.destroy();
        eff = createShaderSceneEffect(dip.to);
        eff.init(canvas);
        eff.resize(canvas.width || 1, canvas.height || 1);
        shaderRef.current = eff;
        setShownScene(dip.to);
      }
      if (t >= 2) dipRef.current = null;
      fade = t < 1 ? 1 - t : Math.min(1, t - 1);
    }
    canvas.style.opacity = String(fade);

    // Hearing: the analyser if there is one, else the beat clock.
    const env = beatEnvelopes(beat);
    const analyser = analyserRef?.current ?? null;
    let raw = syntheticFeatures(env);
    if (analyser) {
      const n = analyser.frequencyBinCount;
      if (!spectrumRef.current || spectrumRef.current.length !== n) {
        spectrumRef.current = new Uint8Array(new ArrayBuffer(n));
      }
      analyser.getByteFrequencyData(spectrumRef.current);
      raw = bandsFromSpectrum(
        spectrumRef.current,
        analyser.context.sampleRate,
        analyser.fftSize,
      );
    }
    const bands = followFeatures(followerRef.current, raw, dt);

    // Colour: the key's palette, eased so a new track tints in over seconds.
    const target = paletteFor(track?.camelot_key);
    colorARef.current = colorARef.current
      ? easeRgb(colorARef.current, target.a, dt)
      : [...target.a];
    colorBRef.current = colorBRef.current
      ? easeRgb(colorBRef.current, target.b, dt)
      : [...target.b];

    eff.render({
      time: (now - startedAt) / 1000,
      beat: env.beat,
      kick: env.kick,
      accent: env.accent,
      ...bands,
      colorA: colorARef.current,
      colorB: colorBRef.current,
      symmetry: symmetryFor(track?.camelot_key),
    });
  };

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
    if (isShaderKind(kind)) {
      renderShaderScene(canvas, kind, beat, track);
      return;
    }
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
      shaderRef.current?.resize(w, h);
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
      shaderRef.current?.destroy();
      particlesRef.current = null;
      fractalRef.current = null;
      strobeRef.current = null;
      shaderRef.current = null;
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
    // Scenes own the GL context too; a manual pick cuts straight to the
    // new scene (the dip is for changes nobody asked for).
    if (shaderRef.current) {
      shaderRef.current.destroy();
      shaderRef.current = null;
    }
    dipRef.current = null;
    if (canvasRef.current) canvasRef.current.style.opacity = "1";
    if (!isShaderKind(kind)) setShownScene(null);
    setEffectKindState(kind);
  }, []);

  // Controls fade out when the pointer has been still for a while, so a
  // fullscreen view (or a capture of it) is just the picture.
  const idleTimerRef = useRef<number | null>(null);
  const wakeControls = useCallback(() => {
    setControlsIdle(false);
    if (idleTimerRef.current !== null) window.clearTimeout(idleTimerRef.current);
    idleTimerRef.current = window.setTimeout(() => setControlsIdle(true), CONTROLS_IDLE_MS);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    idleTimerRef.current = window.setTimeout(() => setControlsIdle(true), CONTROLS_IDLE_MS);
    return () => {
      if (idleTimerRef.current !== null) window.clearTimeout(idleTimerRef.current);
    };
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
      data-scene={shownScene ?? undefined}
      className="relative w-full h-full bg-black overflow-hidden rounded"
      style={{ minHeight: 256, cursor: controlsIdle ? "none" : undefined }}
      onPointerMove={wakeControls}
      onPointerDown={wakeControls}
    >
      <canvas
        ref={canvasRef}
        data-testid="visual-canvas"
        className="block w-full h-full"
      />

      {/* Effect selector + fullscreen toggle */}
      <div
        data-testid="visual-controls"
        data-idle={controlsIdle ? "true" : "false"}
        className={`absolute top-2 left-2 right-2 flex flex-wrap gap-2 items-center z-10 pointer-events-none transition-opacity duration-700 ${
          controlsIdle ? "opacity-0" : "opacity-100"
        }`}
      >
        <div className="pointer-events-auto flex gap-1 bg-black/50 backdrop-blur-md rounded-full p-1 border border-white/10">
          {MODERN_EFFECTS.map((k) => (
            <button
              key={k}
              data-testid={`visual-effect-${k}`}
              onClick={() => setEffectKind(k)}
              title={k === "auto" && shownScene ? `auto · ${shownScene}` : undefined}
              className={`text-[10px] tracking-[0.2em] uppercase px-3 py-1 rounded-full transition-colors ${
                effectKind === k
                  ? "bg-white text-black"
                  : "text-white/70 hover:text-white"
              }`}
            >
              {k === "auto" && effectKind === "auto" && shownScene
                ? `auto · ${shownScene}`
                : k}
            </button>
          ))}
        </div>
        <div className="pointer-events-auto flex gap-1 bg-black/40 rounded-full p-1">
          {CLASSIC_EFFECTS.map((k) => (
            <button
              key={k}
              data-testid={`visual-effect-${k}`}
              onClick={() => setEffectKind(k)}
              className={`text-[9px] tracking-widest uppercase px-2 py-1 rounded-full ${
                effectKind === k
                  ? "bg-white/80 text-black"
                  : "text-white/40 hover:text-white/80"
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
          className="pointer-events-auto ml-auto bg-black/50 backdrop-blur-md border border-white/10 text-white/70 hover:text-white text-[10px] tracking-[0.2em] uppercase px-3 py-1 rounded-full"
        >
          {isFullscreen ? "exit fs" : "fullscreen"}
        </button>
      </div>

      {/* Degraded-sync banner — classic effects only: the shader scenes
          listen to the audio itself, and beatless genres (healing, aural)
          have no grid to find, so the banner there would be permanent
          noise on a public broadcast. */}
      {!hasBeatgrid && currentTrack && !isShaderKind(effectKind) ? (
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
