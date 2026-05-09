/**
 * strobe — fullscreen flash effect on every Nth downbeat.
 *
 * Implementation is intentionally not Three.js: a single absolutely
 * positioned ``div`` with a controlled ``opacity`` is GPU-cheap, has
 * no draw-call overhead, and integrates cleanly with the rest of the
 * page.  The flash itself is an exponential-out decay over 80 ms.
 *
 * Safety
 * ------
 * Strobing above 3 Hz can trigger photosensitive epilepsy.  We default
 * the safety cap to ``max_hz = 3`` and refuse to fire faster than that.
 * The UI surfaces a warning when the user pushes the rate past the
 * threshold.  ``setMaxHz`` is the only knob that can lift this — and it
 * still rate-limits at the actual value of ``max_hz``.
 *
 * v2.5.2 fixes (issue #44)
 * ------------------------
 * 1. The overlay now sets ``zIndex: 5`` so it renders above the WebGL
 *    canvas (the canvas itself is at the default 0 stacking level, but
 *    fullscreen layouts can land below page chrome). Without this the
 *    flash was mounted but never visible to the user.
 * 2. The cadence selector matches the user-facing label: "every N
 *    downbeats" really means "every N downbeats", not "every N bars".
 *    Previously we multiplied by 4 internally which made "every 4"
 *    actually fire once per 16 bars — way too rare to ever see.
 * 3. A debug logger (off by default) is wired through ``setDebug`` so
 *    we can introspect why a flash was skipped without re-shipping.
 */
import type { BeatClockResult } from "../beat_clock";

export interface StrobeEffect {
  /** Bind a host element. The effect mounts a child overlay div in it. */
  init(container: HTMLElement): void;
  /** Per-frame call. ``every_n_downbeats`` selects downbeat cadence. */
  render(beat: BeatClockResult, every_n_downbeats: number): void;
  /** Override the safety cap. */
  setMaxHz(hz: number): void;
  /** Toggle a console.debug breadcrumb on every render decision. */
  setDebug(enabled: boolean): void;
  /** Remove the overlay and stop animations. */
  destroy(): void;
}

const FLASH_DURATION_MS = 80;
const DEFAULT_MAX_HZ = 3;
const BEATS_PER_BAR = 4;

export function createStrobeEffect(): StrobeEffect {
  let overlay: HTMLDivElement | null = null;
  let lastFiredBeatIndex = -1;
  let lastFiredAt = 0;
  let maxHz = DEFAULT_MAX_HZ;
  let debugEnabled = false;

  function debug(reason: string, ctx: Record<string, unknown> = {}): void {
    if (!debugEnabled) return;
    console.debug(`[strobe] ${reason}`, ctx);
  }

  function init(container: HTMLElement) {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.setAttribute("data-testid", "strobe-overlay");
    overlay.style.cssText = [
      "position:absolute",
      "inset:0",
      "background:#fff",
      "opacity:0",
      "pointer-events:none",
      // Sit above the WebGL canvas (default stacking 0) but below any
      // controls (z-10). Without an explicit z-index the overlay's
      // stacking depended on insertion order, which made it invisible
      // when LiveStage re-ordered children during effect switches —
      // see issue #44.
      "z-index:5",
      // Fade is driven by setting opacity directly, no CSS transition;
      // the rAF loop handles the decay so we don't fight the browser
      // compositor for sub-frame timing.
      "will-change:opacity",
    ].join(";");
    container.appendChild(overlay);
  }

  function render(beat: BeatClockResult, every_n_downbeats: number) {
    if (!overlay) {
      debug("skip:no-overlay", { beat });
      return;
    }
    const safeN = Math.max(1, Math.floor(every_n_downbeats));
    // The beat_clock module flags a downbeat every BEATS_PER_BAR beats.
    // "every N downbeats" therefore = every N*BEATS_PER_BAR beats.
    const beatStride = safeN * BEATS_PER_BAR;

    if (!beat.is_downbeat) {
      // Common case — silently fall through to the decay path. We log
      // only when debug is on to avoid console spam at 60 fps.
      debug("skip:not-downbeat", { beat_index: beat.beat_index });
    } else if (beat.beat_index === lastFiredBeatIndex) {
      debug("skip:dedupe", { beat_index: beat.beat_index });
    } else if (beat.beat_index % beatStride !== 0) {
      debug("skip:cadence", {
        beat_index: beat.beat_index,
        beatStride,
      });
    } else {
      const now = performance.now();
      const minIntervalMs = 1000 / Math.max(0.1, maxHz);
      const sinceLast = now - lastFiredAt;
      if (lastFiredAt > 0 && sinceLast < minIntervalMs) {
        debug("skip:rate-limit", {
          beat_index: beat.beat_index,
          sinceLast,
          minIntervalMs,
        });
      } else {
        lastFiredBeatIndex = beat.beat_index;
        lastFiredAt = now;
        overlay.style.opacity = "1";
        debug("fire", {
          beat_index: beat.beat_index,
          beatStride,
          maxHz,
        });
        return;
      }
    }

    // Exponential decay back to 0. Reaching this branch means we either
    // didn't fire this frame or didn't fire a flash recently.
    if (lastFiredAt === 0) {
      // No flash has ever happened — keep the overlay at zero. Avoids
      // the negative-time math when render is called before any beat.
      if (overlay.style.opacity !== "0") overlay.style.opacity = "0";
      return;
    }
    const since = performance.now() - lastFiredAt;
    if (since < FLASH_DURATION_MS) {
      const t = since / FLASH_DURATION_MS;
      const o = Math.pow(1 - t, 2.5);
      overlay.style.opacity = String(o);
    } else if (overlay.style.opacity !== "0") {
      overlay.style.opacity = "0";
    }
  }

  function setMaxHz(hz: number) {
    if (!Number.isFinite(hz) || hz <= 0) return;
    maxHz = hz;
  }

  function setDebug(enabled: boolean) {
    debugEnabled = !!enabled;
  }

  function destroy() {
    if (overlay && overlay.parentElement) {
      overlay.parentElement.removeChild(overlay);
    }
    overlay = null;
    lastFiredBeatIndex = -1;
    lastFiredAt = 0;
  }

  return { init, render, setMaxHz, setDebug, destroy };
}

export const STROBE_DEFAULT_MAX_HZ = DEFAULT_MAX_HZ;
