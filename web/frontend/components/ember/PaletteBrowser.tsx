"use client";
/**
 * §11 S7 — the palette browser.
 *
 * Its job is not to list sounds. It is to make the **bank rule visible**, so
 * the rule stops being folklore the validator enforces after the fact:
 *
 *   drums REQUIRE a bank · synths have none · instruments are SILENT with one
 *
 * A sampled instrument carrying `.bank()` produces no error and no sound, and
 * that is exactly why it must be impossible to click your way into it here —
 * `insertionFor` will not accept a bank for one, so the UI has no path to it.
 */
import { useMemo, useState } from "react";
import {
  CATEGORIES,
  banksFor,
  insertionFor,
  type Palette,
  type PaletteCategory,
} from "@/lib/palette";

export type PaletteBrowserProps = {
  palette: Palette | null;
  error?: string | null;
  /** Called with the Strudel line to add to the buffer. */
  onInsert: (line: string) => void;
  /** Called to hear a sound alone. Absent while a set is running. */
  onAudition?: (line: string) => void;
};

export function PaletteBrowser({
  palette,
  error,
  onInsert,
  onAudition,
}: PaletteBrowserProps) {
  const [category, setCategory] = useState<PaletteCategory>("drums");
  const [bank, setBank] = useState<string | null>(null);

  const sounds = useMemo(
    () => (palette ? palette[category] : []),
    [palette, category],
  );

  if (error) {
    return (
      <p data-testid="palette-error" className="text-ember text-sm">
        {error}
      </p>
    );
  }
  if (!palette) {
    return <p className="text-faint text-sm">loading the registry…</p>;
  }

  const hint = CATEGORIES.find(([id]) => id === category)?.[2] ?? "";

  return (
    <div data-testid="palette" className="flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 p-[3px] border border-line2">
          {CATEGORIES.map(([id, label]) => (
            <button
              key={id}
              type="button"
              data-testid={`palette-tab-${id}`}
              onClick={() => {
                setCategory(id);
                setBank(null);
              }}
              className={
                "px-3 py-1 text-xs font-sans cursor-pointer " +
                (category === id
                  ? "bg-cream text-ink"
                  : "bg-transparent text-mute hover:text-ember-text")
              }
            >
              {label}
            </button>
          ))}
        </div>
        <span
          data-testid="palette-rule"
          className="font-mono uppercase tracking-mono text-[10px] text-faint"
        >
          {hint}
        </span>
        {category === "instruments" && (
          // The second rule of this category, and it is invisible in the
          // registry: a map keyed by note name is chromatic and takes
          // `note(...)`, a flat list is walked with `.n(i)`. Writing the wrong
          // one plays — it just transposes a one-shot — so it has to be shown.
          <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
            <span className="text-ok">▲</span> chromatic · note() ·{" "}
            <span className="text-mute">■</span> one-shots · .n()
          </span>
        )}
        <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
          {sounds.length} sounds
        </span>
      </div>

      {category === "drums" && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono uppercase tracking-mono text-[10px] text-warn">
            pick a bank first
          </span>
          {Object.keys(palette.banks).map((b) => (
            <button
              key={b}
              type="button"
              data-testid={`palette-bank-${b}`}
              onClick={() => setBank(b === bank ? null : b)}
              className={
                "font-mono text-[10.5px] px-2.5 py-1 rounded border cursor-pointer " +
                (bank === b
                  ? "border-ember text-ember"
                  : "border-line2 text-mute hover:text-ember-text")
              }
            >
              {b}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {sounds.map((sound) => {
          // A drum is only offered on a bank that actually carries it: the
          // (sound, bank) matrix is data, and a pair outside it is not a sound.
          const carried =
            category !== "drums" || (bank !== null && banksFor(palette, sound).includes(bank));
          const line = insertionFor(category, sound, bank ?? undefined, palette.pitched);
          const usable = carried && line !== null;

          return (
            <span key={sound} className="inline-flex">
              <button
                type="button"
                data-testid={`palette-sound-${sound}`}
                data-usable={String(usable)}
                disabled={!usable}
                onClick={() => line && onInsert(line)}
                title={
                  usable
                    ? `insert  ${line}`
                    : bank === null
                      ? "choose a bank"
                      : `${bank} does not carry ${sound}`
                }
                className={
                  "font-mono text-[11px] px-2.5 py-1 rounded border-l-2 cursor-pointer " +
                  (usable
                    ? "border border-line2 border-l-ok text-ember-text hover:border-ember"
                    : "border border-line text-faint/50 cursor-not-allowed border-l-line")
                }
              >
                {category === "instruments" && (
                  <span
                    data-pitched={String(palette.pitched[sound] === true)}
                    className={
                      "mr-1 " +
                      (palette.pitched[sound] === true ? "text-ok" : "text-mute")
                    }
                  >
                    {palette.pitched[sound] === true ? "▲" : "■"}
                  </span>
                )}
                {sound}
              </button>
              {usable && onAudition && (
                <button
                  type="button"
                  data-testid={`palette-audition-${sound}`}
                  onClick={() => line && onAudition(line)}
                  title="hear it alone"
                  className="font-mono text-[11px] px-1.5 py-1 rounded border border-line text-faint hover:text-ember cursor-pointer -ml-px"
                >
                  ▸
                </button>
              )}
            </span>
          );
        })}
      </div>

      {!onAudition && (
        <p className="font-mono uppercase tracking-mono text-[10px] text-faint">
          audition is off while a set is running — a preview would replace what
          the room is hearing
        </p>
      )}
    </div>
  );
}
