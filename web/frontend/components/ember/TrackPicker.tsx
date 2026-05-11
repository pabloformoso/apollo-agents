"use client";
/**
 * Apollo v2.6.0 — TrackPicker modal.
 *
 * Searchable catalog list. Used by Editor's "Add a track" and (later) by
 * Curate's "swap suggestion". Filtered by genre by default; the user can
 * toggle off the filter via the "Show full catalog" pill.
 *
 * The list is virtualised by simple windowing (first 200 hits) so a
 * 600-track catalog doesn't blow the modal layout. If a track is in the
 * current session playlist its row is dimmed but still selectable — the
 * Editor decides whether to allow duplicates.
 */
import * as React from "react";
import { getCatalog } from "@/lib/api";
import type { Track } from "@/lib/types";
import { Btn, Crumb } from "./primitives";
import { Dialog } from "./Dialog";
import { Spinner } from "./feedback";

const WINDOW_LIMIT = 200;

export type TrackPickerProps = {
  open: boolean;
  onClose: () => void;
  /** Restrict to this genre folder. `null` → show everything. */
  genre?: string | null;
  /** Track ids already in the playlist — rendered dimmed. */
  existingIds?: string[];
  /** Called with the picked track. Closing the modal is the caller's job. */
  onSelect: (track: Track) => void;
};

export function TrackPicker({
  open,
  onClose,
  genre,
  existingIds = [],
  onSelect,
}: TrackPickerProps) {
  const [query, setQuery] = React.useState("");
  const [tracks, setTracks] = React.useState<Track[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showAll, setShowAll] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Fetch once per open — once the catalog is loaded it lives until the
  // dialog closes. Re-fetches on genre/showAll toggle.
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setTracks(null);
    setError(null);
    const targetGenre = showAll ? undefined : genre ?? undefined;
    getCatalog(targetGenre)
      .then((cat) => {
        if (cancelled) return;
        setTracks(cat.tracks);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [open, genre, showAll]);

  // Autofocus the search input on open.
  React.useEffect(() => {
    if (open) {
      // Defer a frame so the portal has mounted.
      const id = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
  }, [open]);

  const filtered = React.useMemo(() => {
    if (!tracks) return [];
    const q = query.trim().toLowerCase();
    const ids = new Set(existingIds);
    const matches = (t: Track) => {
      if (!q) return true;
      return (
        t.display_name?.toLowerCase().includes(q) ||
        (t.genre ?? "").toLowerCase().includes(q) ||
        (t.camelot_key ?? "").toLowerCase().includes(q) ||
        String(t.bpm ?? "").includes(q)
      );
    };
    const out: Track[] = [];
    for (const t of tracks) {
      if (matches(t)) {
        out.push(t);
        if (out.length >= WINDOW_LIMIT) break;
      }
    }
    // Sort already-in-playlist to the bottom so the new options are above.
    out.sort((a, b) => Number(ids.has(a.id)) - Number(ids.has(b.id)));
    return out;
  }, [tracks, query, existingIds]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width="wide"
      label="Pick a track"
      surfaceClassName="flex flex-col gap-3 p-5"
    >
      <div className="flex items-baseline justify-between">
        <Crumb tone="ember">add a track</Crumb>
        {genre && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="font-mono text-[10px] uppercase tracking-mono text-faint hover:text-ember-text cursor-pointer"
          >
            {showAll ? `Filter ${genre}` : "Show full catalog"}
          </button>
        )}
      </div>

      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by name, key, BPM…"
        className="bg-transparent border border-line2 px-3 py-2 text-ember-text font-sans text-sm outline-none placeholder:text-faint focus:border-ember-text"
      />

      {!tracks && !error && (
        <div className="flex items-center gap-2 text-faint font-mono text-[11px] uppercase tracking-mono py-6 justify-center">
          <Spinner /> Loading catalog…
        </div>
      )}

      {error && (
        <div className="text-ember font-mono text-[11px] uppercase tracking-mono py-6 text-center">
          {error}
        </div>
      )}

      {tracks && (
        <ul className="list-none m-0 p-0 flex flex-col overflow-auto max-h-[60vh]">
          {filtered.map((t) => {
            const dim = existingIds.includes(t.id);
            return (
              <li
                key={t.id}
                className={
                  "grid grid-cols-[1fr_60px_50px] gap-3 items-center px-2 py-2 border-b border-line cursor-pointer hover:bg-surf2 " +
                  (dim ? "opacity-40" : "")
                }
                onClick={() => onSelect(t)}
              >
                <div>
                  <div className="font-display italic text-base text-ember-text">
                    {t.display_name}
                  </div>
                  <div className="text-[11px] text-mute">
                    {t.genre ?? "—"}
                  </div>
                </div>
                <span className="font-mono text-[11px] text-mute text-right">
                  {t.bpm ? `${t.bpm} BPM` : "—"}
                </span>
                <span className="font-mono text-[11px] text-ember border border-line2 px-2 py-0.5 text-center">
                  {t.camelot_key ?? "—"}
                </span>
              </li>
            );
          })}
          {filtered.length === 0 && (
            <li className="text-faint font-mono text-[11px] uppercase tracking-mono py-6 text-center">
              No matches.
            </li>
          )}
        </ul>
      )}

      <div className="flex justify-end">
        <Btn kind="ghost" onClick={onClose} className="px-3 py-1.5 text-[11px]">
          Cancel
        </Btn>
      </div>
    </Dialog>
  );
}
