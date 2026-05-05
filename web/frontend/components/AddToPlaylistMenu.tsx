"use client";
import { useEffect, useRef, useState } from "react";
import { addTracks, createPlaylist, listPlaylists } from "@/lib/api";
import type { Playlist } from "@/lib/types";

interface AddToPlaylistMenuProps {
  trackId: string;
  /** Called after a successful add. Receives the playlist that was updated. */
  onAdded?: (playlist: Playlist) => void;
  /** Close handler — the parent owns visibility. */
  onClose: () => void;
}

/**
 * Popover menu listing the user's playlists. Click one → adds the track.
 * "Create new…" lets the user name a fresh playlist inline and adds in
 * the same flow.
 */
export default function AddToPlaylistMenu({
  trackId,
  onAdded,
  onClose,
}: AddToPlaylistMenuProps) {
  const [playlists, setPlaylists] = useState<Playlist[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | "new" | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listPlaylists()
      .then(setPlaylists)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load playlists"),
      );
  }, []);

  // Click outside closes the popover.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  async function handlePick(p: Playlist) {
    if (busyId !== null) return;
    setBusyId(p.id);
    setError(null);
    try {
      await addTracks(p.id, [trackId]);
      setConfirmation(`Added to "${p.name}"`);
      onAdded?.(p);
      // Brief confirmation, then close.
      setTimeout(onClose, 700);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add failed");
      setBusyId(null);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name || busyId !== null) return;
    setBusyId("new");
    setError(null);
    try {
      const created = await createPlaylist(name);
      await addTracks(created.id, [trackId]);
      setConfirmation(`Added to "${created.name}"`);
      onAdded?.(created);
      setTimeout(onClose, 700);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
      setBusyId(null);
    }
  }

  return (
    <div
      ref={rootRef}
      data-testid="add-to-playlist-menu"
      role="menu"
      aria-label="Add to playlist"
      className="absolute z-50 right-0 top-full mt-1 w-64 bg-surface border border-border rounded shadow-lg text-xs"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-3 py-2 border-b border-border text-muted uppercase tracking-widest text-[10px]">
        Add to playlist
      </div>

      {error && (
        <div className="px-3 py-2 text-danger text-[11px]">{error}</div>
      )}

      {confirmation && (
        <div
          className="px-3 py-2 text-neon text-[11px]"
          data-testid="add-to-playlist-confirmation"
        >
          {confirmation}
        </div>
      )}

      <div className="max-h-48 overflow-y-auto">
        {playlists === null ? (
          <p className="px-3 py-2 text-muted">Loading…</p>
        ) : playlists.length === 0 ? (
          <p className="px-3 py-2 text-muted">No playlists yet.</p>
        ) : (
          playlists.map((p) => (
            <button
              key={p.id}
              type="button"
              role="menuitem"
              onClick={() => handlePick(p)}
              disabled={busyId !== null}
              data-testid={`add-to-playlist-item-${p.id}`}
              className="w-full text-left px-3 py-2 hover:bg-[#1e1e2e]/50 disabled:opacity-50 flex items-center justify-between"
            >
              <span className="truncate text-[#e2e2ff]">{p.name}</span>
              <span className="text-muted text-[10px] ml-2">
                {p.track_count}
              </span>
            </button>
          ))
        )}
      </div>

      <div className="border-t border-border p-2">
        {showNew ? (
          <form onSubmit={handleCreate} className="flex items-center gap-2">
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Playlist name"
              maxLength={100}
              data-testid="add-to-playlist-new-name"
              className="flex-1 bg-[#0a0a0f] border border-border rounded px-2 py-1 text-[11px] text-[#e2e2ff] focus:border-neon focus:outline-none"
            />
            <button
              type="submit"
              disabled={!newName.trim() || busyId !== null}
              data-testid="add-to-playlist-new-submit"
              className="text-neon text-[11px] px-2 py-1 disabled:opacity-50 hover:underline"
            >
              Add
            </button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setShowNew(true)}
            data-testid="add-to-playlist-new-trigger"
            className="w-full text-left text-neon hover:underline px-1 py-1"
          >
            + Create new…
          </button>
        )}
      </div>
    </div>
  );
}
