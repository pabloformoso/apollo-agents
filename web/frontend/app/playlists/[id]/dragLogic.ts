import { arrayMove } from "@dnd-kit/sortable";

import type { PlaylistTrack } from "@/lib/types";

/**
 * Pure helper extracted from `handleDragEnd` so the reordering logic can be
 * unit-tested without rendering React or simulating pointer events.
 *
 * Returns `null` when the drag should be a no-op (item dropped on itself, or
 * either id is unknown). Otherwise returns the next track list and the array
 * of track ids to send to the API.
 *
 * Note: rowIds are position-aware (`${trackId}-pos${i}`) because playlists
 * allow duplicate track ids — see `rowIds` memo in the page component.
 */
export function computeDragReorder(
  activeId: string,
  overId: string,
  tracks: PlaylistTrack[],
  rowIds: string[],
): { nextTracks: PlaylistTrack[]; reorderArgs: string[] } | null {
  if (activeId === overId) return null;
  const oldIndex = rowIds.indexOf(activeId);
  const newIndex = rowIds.indexOf(overId);
  if (oldIndex < 0 || newIndex < 0) return null;
  const nextTracks = arrayMove(tracks, oldIndex, newIndex);
  return { nextTracks, reorderArgs: nextTracks.map((t) => t.id) };
}
