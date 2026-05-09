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
 */
import type { BeatClockResult } from "../beat_clock";

export interface StrobeEffect {
  /** Bind a host element. The effect mounts a child overlay div in it. */
  init(container: HTMLElement): void;
  /** Per-frame call. ``every_n_downbeats`` selects bar pacing. */
  render(beat: BeatClockResult, every_n_downbeats: number): void;
  /** Override the safety cap. */
  setMaxHz(hz: number): void;
  /** Remove the overlay and stop animations. */
  destroy(): void;
}

const FLASH_DURATION_MS = 80;
const DEFAULT_MAX_HZ = 3;

export function createStrobeEffect(): StrobeEffect {
  let overlay: HTMLDivElement | null = null;
  let lastFiredBeatIndex = -1;
  let lastFiredAt = 0;
  let maxHz = DEFAULT_MAX_HZ;

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
      // Fade is driven by setting opacity directly, no CSS transition;
      // the rAF loop handles the decay so we don't fight the browser
      // compositor for sub-frame timing.
      "will-change:opacity",
    ].join(";");
    container.appendChild(overlay);
  }

  function render(beat: BeatClockResult, every_n_downbeats: number) {
    if (!overlay) return;
    const safeBars = Math.max(1, every_n_downbeats);

    // Fire on the leading edge of a downbeat that lands on a bar matching
    // the cadence — and dedupe by ``beat_index`` so we only flash once per
    // beat regardless of how many rAF frames hit while phase < tolerance.
    if (
      beat.is_downbeat &&
      beat.beat_index !== lastFiredBeatIndex &&
      beat.beat_index % (safeBars * 4) === 0 // 4 beats per bar baseline
    ) {
      const now = performance.now();
      const minIntervalMs = 1000 / Math.max(0.1, maxHz);
      if (now - lastFiredAt >= minIntervalMs) {
        lastFiredBeatIndex = beat.beat_index;
        lastFiredAt = now;
        overlay.style.opacity = "1";
      }
    }

    // Exponential decay back to 0.
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

  function destroy() {
    if (overlay && overlay.parentElement) {
      overlay.parentElement.removeChild(overlay);
    }
    overlay = null;
    lastFiredBeatIndex = -1;
    lastFiredAt = 0;
  }

  return { init, render, setMaxHz, destroy };
}

export const STROBE_DEFAULT_MAX_HZ = DEFAULT_MAX_HZ;
