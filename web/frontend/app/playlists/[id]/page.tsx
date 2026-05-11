"use client";
/**
 * Apollo v2.6.0 — Playlist detail.
 * Ember design-system port. Same DnD reorder logic, optimistic updates,
 * rename + delete actions, "Play all" — only the visual layer is new.
 * `data-testid` hooks preserved verbatim for E2E.
 */
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
import { useAuth } from "@/lib/auth";
import { usePlayer } from "@/lib/player";
import type { PlaylistDetail, PlaylistTrack, Track } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import { Btn, Crumb } from "@/components/ember/primitives";

import { computeDragReorder } from "./dragLogic";

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
      className={
        "flex items-center gap-4 py-3 px-4 group border-b border-line " +
        (missing ? "opacity-50" : "hover:bg-surf2")
      }
    >
      <span
        {...attributes}
        {...listeners}
        className="text-faint cursor-grab active:cursor-grabbing select-none text-base"
        title="Drag to reorder"
        data-testid="playlist-row-handle"
      >
        ⠿
      </span>

      <span className="font-display italic text-2xl text-faint w-7 text-right flex-shrink-0">
        {String(position).padStart(2, "0")}
      </span>

      <div className="flex-1 min-w-0">
        <p className="font-display italic text-lg text-ember-text leading-[1.15] truncate">
          {track.display_name}
          {missing && (
            <span className="ml-2 font-mono text-[10px] text-ember uppercase tracking-mono not-italic">
              missing
            </span>
          )}
        </p>
        <p className="text-xs text-mute mt-0.5">{track.genre ?? ""}</p>
      </div>

      <div className="flex items-center gap-3 flex-shrink-0 font-mono text-[11px]">
        {track.camelot_key && (
          <span className="text-ember px-2 py-0.5 border border-line2">
            {track.camelot_key}
          </span>
        )}
        {track.bpm && (
          <span className="text-mute">{Math.round(track.bpm)} BPM</span>
        )}
        <span className="text-faint">
          {formatDuration(track.duration_sec)}
        </span>
        <button
          onClick={onRemove}
          className="text-faint hover:text-ember opacity-0 group-hover:opacity-100 transition-opacity ml-2"
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

  const { user, hydrated } = useAuth();
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
    if (!hydrated) return;
    if (!user) {
      router.push("/login");
      return;
    }
    if (!Number.isFinite(playlistId)) return;
    let cancelled = false;
    getPlaylist(playlistId)
      .then((detail) => {
        if (cancelled) return;
        setPl(detail);
        setNameDraft(detail.name);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load playlist");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, playlistId, router]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const rowIds = useMemo(
    () => (pl?.tracks ?? []).map((t, i) => `${t.id}-pos${i}`),
    [pl?.tracks],
  );

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!pl || !over) return;
    const result = computeDragReorder(
      String(active.id),
      String(over.id),
      pl.tracks,
      rowIds,
    );
    if (!result) return;
    setPl({ ...pl, tracks: result.nextTracks });
    try {
      await reorderTracks(pl.id, result.reorderArgs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reorder failed");
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
    <Shell username={user.username}>
      <section className="px-[60px] pt-10 pb-6 border-b border-line">
        <button
          onClick={() => router.push("/playlists")}
          className="font-mono text-[11px] text-faint uppercase tracking-mono hover:text-ember transition-colors"
        >
          ← all playlists
        </button>

        <div className="mt-3 flex items-end justify-between gap-6">
          <div className="min-w-0 flex-1">
            <Crumb>playlist · {pl?.tracks.length ?? "…"} tracks</Crumb>
            {editingName ? (
              <form
                onSubmit={handleRename}
                className="mt-2 flex items-center gap-3"
              >
                <input
                  autoFocus
                  type="text"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  maxLength={100}
                  data-testid="playlist-name-input"
                  className="flex-1 bg-transparent border-0 border-b border-line2 px-0 py-1
                    font-display italic text-[64px] leading-[0.95] tracking-display-tight text-cream
                    outline-none focus:border-ember transition-colors"
                />
                <button
                  type="submit"
                  className="font-mono text-[11px] text-ember uppercase tracking-mono hover:text-ember-dark transition-colors"
                >
                  save
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditingName(false);
                    setNameDraft(pl?.name ?? "");
                  }}
                  className="font-mono text-[11px] text-faint uppercase tracking-mono hover:text-ember-text transition-colors"
                >
                  cancel
                </button>
              </form>
            ) : (
              <h1
                onClick={() => setEditingName(true)}
                className="font-display italic font-normal text-[64px] leading-[0.95] tracking-display-tight m-0 mt-2 cursor-text"
                data-testid="playlist-name"
              >
                {pl?.name ?? "…"}
                <span className="text-ember">.</span>
              </h1>
            )}
          </div>

          <div className="flex items-center gap-3 flex-shrink-0">
            <Btn
              onClick={handlePlayAll}
              disabled={!pl || pl.tracks.length === 0}
              data-testid="playlist-play-all"
            >
              ▶ Play all
            </Btn>
            <Btn
              kind="quiet"
              onClick={handleDelete}
              data-testid="playlist-delete"
              className="hover:text-ember"
            >
              Delete
            </Btn>
          </div>
        </div>
      </section>

      {error && (
        <div className="mx-[60px] mt-4 border border-ember p-4 font-mono text-xs text-ember">
          {error}
        </div>
      )}

      <section className="px-[60px] py-8 flex-1">
        {loading ? (
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            loading…
          </p>
        ) : !pl ? (
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            playlist not found.
          </p>
        ) : pl.tracks.length === 0 ? (
          <div className="border border-dashed border-line2 p-12 text-center">
            <p className="text-mute text-sm">
              No tracks yet. Add some from the{" "}
              <button
                onClick={() => router.push("/catalog")}
                className="text-ember hover:text-ember-dark hover:underline transition-colors"
              >
                catalog
              </button>
              .
            </p>
          </div>
        ) : (
          <div className="bg-surf border border-line">
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
      </section>
    </Shell>
  );
}
