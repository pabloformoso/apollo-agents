import { describe, it, expect } from "vitest";

import { playlistRowKey, playlistRowIds } from "@/lib/playlistKeys";

/**
 * Regression guard for 2026-08-17: the curate / session / editor / render
 * views keyed playlist rows on `track.id`. A playlist may schedule the
 * same track twice, so React saw duplicate keys and logged
 * "Encountered two children with the same key,
 * `aural--aural_2-gong_profundo-v2`" — three of them in one live session.
 *
 * The format is load-bearing beyond uniqueness: `playlists/[id]` feeds
 * these same ids to dnd-kit, and `dragLogic` maps a dragged id back to an
 * index by looking it up in this list. Changing the shape breaks reorder.
 */

function repeated(id: string, times: number) {
  return Array.from({ length: times }, () => ({ id }));
}

describe("playlistRowKey", () => {
  it("qualifies a track id with its position", () => {
    expect(playlistRowKey("aural--gong", 0)).toBe("aural--gong-pos0");
    expect(playlistRowKey("aural--gong", 7)).toBe("aural--gong-pos7");
  });

  it("gives distinct keys to the same track at different positions", () => {
    expect(playlistRowKey("x", 0)).not.toBe(playlistRowKey("x", 1));
  });
});

describe("playlistRowIds", () => {
  it("is unique when a playlist repeats one track", () => {
    const ids = playlistRowIds(repeated("aural--aural_2-gong_profundo-v2", 3));
    expect(new Set(ids).size).toBe(3);
  });

  it("is unique across an interleaved repeat", () => {
    const ids = playlistRowIds([
      { id: "a" },
      { id: "b" },
      { id: "a" },
      { id: "b" },
      { id: "a" },
    ]);
    expect(new Set(ids).size).toBe(5);
  });

  it("stays unique for the real duplicated ids from the live log", () => {
    const ids = playlistRowIds([
      { id: "aural--aural_2-gong_profundo-v2" },
      { id: "aural--aural-warmth_in_the_void-v2" },
      { id: "aural--aural_2-gong_profundo-v2" },
      { id: "aural--aural_2-coro_velado-v2" },
      { id: "aural--aural-warmth_in_the_void-v2" },
      { id: "aural--aural_2-coro_velado-v2" },
    ]);
    expect(new Set(ids).size).toBe(6);
  });

  it("preserves order and position, so index lookup still works", () => {
    const tracks = [{ id: "a" }, { id: "b" }, { id: "a" }];
    const ids = playlistRowIds(tracks);
    expect(ids).toEqual(["a-pos0", "b-pos1", "a-pos2"]);
    // dragLogic resolves a dragged id back to its index this way.
    expect(ids.indexOf("a-pos2")).toBe(2);
  });

  it("handles an empty playlist", () => {
    expect(playlistRowIds([])).toEqual([]);
  });
});
