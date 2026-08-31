"use client";
/**
 * §11 S4 — the stage's three modes, shared by every performance surface.
 *
 * This is seam 3 of §11.3: `/live` and `/algorave` render the SAME switcher
 * and the same hash sync, never two copies. The fusion those seams exist for
 * (§11.1) is then a composition rather than a rebuild — and, just as usefully,
 * the duplication is retired before it has a chance to harden.
 *
 * The modes are deliberately not renamed. `cabin` is what the code has always
 * called the Booth, and every URL hash, bookmark and OBS Browser Source
 * already carries it; a tidier identifier is not worth breaking those for.
 */
import { useEffect, useState } from "react";

export type StageMode = "audience" | "cabin" | "immersive";

/** id → label. Order is the on-screen order. */
export const STAGE_MODES: ReadonlyArray<[StageMode, string]> = [
  ["audience", "Audience"],
  ["cabin", "Booth"],
  ["immersive", "Immersive"],
];

export function isStageMode(s: string): s is StageMode {
  return STAGE_MODES.some(([id]) => id === s);
}

/**
 * Owns the mode and keeps it in the URL hash, so a reload — or a
 * "show controls" round trip — lands back where the user was.
 *
 * `replaceState`, not `push`: flipping between modes is a view change, not
 * navigation, and it must not fill the back button with them.
 */
export function useStageMode(
  initial: StageMode = "audience",
): [StageMode, (m: StageMode) => void] {
  const [mode, setMode] = useState<StageMode>(initial);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const fromHash = window.location.hash.slice(1);
    if (isStageMode(fromHash)) setMode(fromHash);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.hash !== `#${mode}`) {
      window.history.replaceState(null, "", `#${mode}`);
    }
  }, [mode]);

  return [mode, setMode];
}

export type ModeSwitcherProps = {
  mode: StageMode;
  onChange: (m: StageMode) => void;
};

/**
 * The segmented control. Markup is kept byte-identical to the one `/live`
 * carried before the extraction — the existing E2E suite must not need a
 * single spec edit for this to land.
 */
export function ModeSwitcher({ mode, onChange }: ModeSwitcherProps) {
  return (
    <div className="flex gap-1 p-[3px] border border-line2">
      {STAGE_MODES.map(([id, label]) => (
        <button
          key={id}
          onClick={() => onChange(id)}
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
  );
}
