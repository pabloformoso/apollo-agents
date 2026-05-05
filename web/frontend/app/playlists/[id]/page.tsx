"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import {
  deletePlaylist as apiDelete,
  getPlaylist,
  removeTrack,
  renamePlaylist,
  reorderTracks,
} from "@/lib/api";
import { getUser } from "@/lib/auth";
import { usePlayer } from "@/lib/player";
import type { PlaylistDetail, PlaylistTrack, Track } from "@/lib/types";

function formatDuration(sec: number | null | undefined) {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface RowProps {
  rowId: string;
  position: number;
  track: PlaylistTrack;
  onRemove: () => void;
}

function TrackRow({ rowId, position, track, onRemove }: RowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: rowId });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const missing = track.missing === true;

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid="playlist-row"
      className={`flex items-center gap-3 py-2 px-3 rounded group ${
        missing ? "opacity-50" : "hover:bg-[#1e1e2e]/50"
      }`}
    >
      <span
        {...attributes}
        {...listeners}
        className="text-muted cursor-grab active:cursor-grabbing select-none"
        title="Drag to reorder"
        data-testid="playlist-row-handle"
      >
        ⠿
      </span>

      <span className="text-muted text-xs w-5 text-right flex-shrink-0">
        {position}
      </span>

      <div className="flex-1 min-w-0">
        <p className="text-sm text-[#e2e2ff] truncate">
          {track.display_name}
          {missing && (
            <span className="ml-2 text-[10px] text-danger uppercase tracking-widest">
              missing
            </span>
          )}
        </p>
        <p className="text-xs text-muted">{track.genre ?? ""}</p>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0 text-xs">
        {track.camelot_key && (
          <span className="text-neon font-bold">{track.camelot_key}</span>
        )}
        {track.bpm && (
          <span className="text-muted">{Math.round(track.bpm)} BPM</span>
        )}
        <span className="text-muted">{formatDuration(track.duration_sec)}</span>
        <button
          onClick={onRemove}
          className="text-muted hover:text-danger opacity-0 group-hover:opacity-100 transition-opacity ml-2"
          aria-label="Remove from playlist"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export default function PlaylistDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const playlistId = Number(params?.id);

  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [pl, setPl] = useState<PlaylistDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");

  const { play } = usePlayer();

  const load = useCallback(async () => {
    if (!Number.isFinite(playlistId)) return;
    setLoading(true);
    setError(null);
    try {
      const detail = await getPlaylist(playlistId);
      setPl(detail);
      setNameDraft(detail.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load playlist");
    } finally {
      setLoading(false);
    }
  }, [playlistId]);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.push("/login");
      return;
    }
    setUser(u);
    load();
  }, [load, router]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Position-aware row id — duplicates are allowed, so the track id alone
  // isn't unique across rows.
  const rowIds = useMemo(
    () => (pl?.tracks ?? []).map((t, i) => `${t.id}-pos${i}`),
    [pl?.tracks],
  );

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!pl || !over || active.id === over.id) return;
    const oldIndex = rowIds.indexOf(String(active.id));
    const newIndex = rowIds.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(pl.tracks, oldIndex, newIndex);
    // Optimistic update.
    setPl({ ...pl, tracks: next });
    try {
      await reorderTracks(
        pl.id,
        next.map((t) => t.id),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reorder failed");
      // Refresh from server to discard the failed local change.
      load();
    }
  }

  async function handleRename(e: React.FormEvent) {
    e.preventDefault();
    if (!pl) return;
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === pl.name) {
      setEditingName(false);
      return;
    }
    try {
      await renamePlaylist(pl.id, trimmed);
      setPl({ ...pl, name: trimmed });
      setEditingName(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rename failed");
    }
  }

  async function handleDelete() {
    if (!pl) return;
    if (!confirm(`Delete "${pl.name}"? This cannot be undone.`)) return;
    try {
      await apiDelete(pl.id);
      router.push("/playlists");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function handleRemove(index: number) {
    if (!pl) return;
    const t = pl.tracks[index];
    try {
      await removeTrack(pl.id, t.id);
      // Refresh — the backend compacted positions and we need the new order.
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed");
    }
  }

  function handlePlayAll() {
    if (!pl) return;
    const playable = pl.tracks.filter((t) => !t.missing) as Track[];
    if (playable.length === 0) return;
    play(playable[0], playable);
  }

  if (!user) return null;

  return (
    <div className="min-h-screen p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="min-w-0 flex-1 mr-4">
          <button
            onClick={() => router.push("/playlists")}
            className="text-muted text-xs hover:text-[#e2e2ff] mb-2"
          >
            ← All playlists
          </button>
          {editingName ? (
            <form onSubmit={handleRename} className="flex items-center gap-2">
              <input
                autoFocus
                type="text"
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                maxLength={100}
                data-testid="playlist-name-input"
                className="flex-1 bg-[#0a0a0f] border border-border rounded px-2 py-1 text-base text-[#e2e2ff] focus:border-neon focus:outline-none"
              />
              <button
                type="submit"
                className="text-neon text-xs px-2 py-1 hover:underline"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditingName(false);
                  setNameDraft(pl?.name ?? "");
                }}
                className="text-muted text-xs px-2 py-1 hover:text-[#e2e2ff]"
              >
                Cancel
              </button>
            </form>
          ) : (
            <h1
              onClick={() => setEditingName(true)}
              className="font-pixel text-neon text-base glow tracking-widest cursor-text"
              data-testid="playlist-name"
            >
              {pl?.name ?? "…"}
            </h1>
          )}
          <p className="text-muted text-xs mt-1">
            {pl ? `${pl.tracks.length} tracks` : ""}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <button
            onClick={handlePlayAll}
            disabled={!pl || pl.tracks.length === 0}
            data-testid="playlist-play-all"
            className="bg-neon text-[#0a0a0f] px-4 py-2 rounded text-xs font-bold tracking-widest uppercase hover:bg-neon-dim disabled:opacity-50 transition-colors"
          >
            ▶ Play all
          </button>
          <button
            onClick={handleDelete}
            data-testid="playlist-delete"
            className="text-muted text-xs hover:text-danger transition-colors"
          >
            Delete
          </button>
        </div>
      </div>

      {error && (
        <div className="border border-danger rounded p-3 text-xs text-danger mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-muted text-xs animate-pulse">Loading…</p>
      ) : !pl ? (
        <p className="text-muted text-xs">Playlist not found.</p>
      ) : pl.tracks.length === 0 ? (
        <div className="border border-dashed border-border rounded p-12 text-center">
          <p className="text-muted text-sm">
            No tracks yet. Add some from the{" "}
            <button
              onClick={() => router.push("/catalog")}
              className="text-neon hover:underline"
            >
              catalog
            </button>
            .
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={rowIds}
              strategy={verticalListSortingStrategy}
            >
              {pl.tracks.map((t, i) => (
                <TrackRow
                  key={rowIds[i]}
                  rowId={rowIds[i]}
                  position={i + 1}
                  track={t}
                  onRemove={() => handleRemove(i)}
                />
              ))}
            </SortableContext>
          </DndContext>
        </div>
      )}
    </div>
  );
}
