/**
 * React keys for playlist rows.
 *
 * A playlist is an ORDERED SCHEDULE, not a set: the planner and the live
 * DJ may both schedule the same track more than once in a session. So
 * `track.id` is not unique within a playlist and cannot be a React key —
 * doing so makes React collapse or duplicate rows, and it logs
 * "Encountered two children with the same key".
 *
 * Position qualifies it. The `-pos{i}` suffix is also the id format that
 * `playlists/[id]` feeds to dnd-kit's `SortableContext`, so drag-and-drop
 * and plain lists stay on one convention (see `dragLogic.ts` and
 * `__tests__/drag-reorder.test.ts`).
 *
 * The catalog is the opposite case — ids there ARE unique, so catalog
 * grids key on `track.id` directly and must not use this.
 */

export function playlistRowKey(trackId: string, index: number): string {
  return `${trackId}-pos${index}`;
}

export function playlistRowIds(tracks: { id: string }[]): string[] {
  return tracks.map((t, i) => playlistRowKey(t.id, i));
}
