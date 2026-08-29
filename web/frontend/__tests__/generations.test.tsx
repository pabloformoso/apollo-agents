/**
 * Vitest unit tests for the G6 generations library.
 *
 *   1. The list fold — `generationsMerged` keeps the feed newest-first and
 *      lets the FRESHER read of a generation win, which is what makes a
 *      "load more" that overlaps page 1 harmless.
 *   2. Discard / restore — `takeStateSet` as the optimistic flip, its
 *      identity behaviour when nothing matches, and the split the card
 *      renders from (`visibleTakes` / `discardedTakes`).
 *   3. Refresh — `generationReplaced` (reconcile in place) and
 *      `readGeneration`, which is where the three refusals stay distinct:
 *      failed ≠ stale ≠ degraded.
 *   4. The card's own gating: title, chips, dates, pagination.
 *   5. `useGenerationsFeed` end-to-end through `renderHook` with a stubbed
 *      `fetch`: first page, load more, an optimistic discard that is rolled
 *      back verbatim when the store refuses it, and a resume.
 *
 * Fetch is stubbed the way `generator.test.tsx` does it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  DEGRADED_NOTE,
  FAILED_NOTE,
  INITIAL_FEED_STATE,
  STALE_NOTE,
  discardedLabel,
  discardedTakes,
  feedFailed,
  feedLanded,
  feedLoadingMore,
  formatCreatedAt,
  generationChips,
  generationReplaced,
  generationTitle,
  generationsFromPayload,
  generationsMerged,
  hasMorePages,
  isPublishedTake,
  readGeneration,
  takeStateOf,
  takeStateSet,
  useGenerationsFeed,
  visibleTakes,
  type FeedState,
  type Generation,
  type StoredTake,
} from "@/lib/generator";

// ── Helpers ───────────────────────────────────────────────────────────────

type MockFetch = ReturnType<typeof vi.fn>;

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Error" : "OK",
    json: async () => body,
  } as Response;
}

const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";

function take(index: number, over: Partial<StoredTake> = {}): StoredTake {
  return {
    index,
    file: `/v1/audio?path=${encodeURIComponent(`${ACE_ROOT}/g_${index}.wav`)}`,
    prompt: "warm lofi keys",
    lyrics: "",
    metas: {
      bpm: 82,
      duration: 181.4,
      genres: "lofi",
      keyscale: "A minor",
      timesignature: "4/4",
    },
    seed_value: 4242 + index,
    state: "fresh",
    published_track_id: null,
    ...over,
  };
}

function generation(
  id: string,
  createdAt: string,
  over: Partial<Generation> = {},
): Generation {
  return {
    id,
    created_at: createdAt,
    status: "done",
    request: { prompt: "warm lofi keys, tape hiss", genre_folder: "lofi - ambient" },
    takes: [take(0), take(1)],
    ...over,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── 1. The list fold ──────────────────────────────────────────────────────

describe("generationsMerged — newest first", () => {
  it("orders by created_at, whatever order the page arrived in", () => {
    const merged = generationsMerged(
      [],
      [
        generation("older", "2026-08-27T10:00:00Z"),
        generation("newest", "2026-08-29T09:00:00Z"),
        generation("middle", "2026-08-28T22:00:00Z"),
      ],
    );
    expect(merged.map((g) => g.id)).toEqual(["newest", "middle", "older"]);
  });

  it("appends a second page under the first", () => {
    const first = generationsMerged(
      [],
      [
        generation("a", "2026-08-29T09:00:00Z"),
        generation("b", "2026-08-29T08:00:00Z"),
      ],
    );
    const merged = generationsMerged(first, [
      generation("c", "2026-08-28T12:00:00Z"),
      generation("d", "2026-08-27T12:00:00Z"),
    ]);
    expect(merged.map((g) => g.id)).toEqual(["a", "b", "c", "d"]);
  });

  it("dedupes by id and lets the FRESHER read win", () => {
    const stalePending = generation("a", "2026-08-29T09:00:00Z", {
      status: "pending",
      takes: [],
    });
    const nowDone = generation("a", "2026-08-29T09:00:00Z", { status: "done" });
    const merged = generationsMerged([stalePending], [nowDone]);
    expect(merged).toHaveLength(1);
    expect(merged[0].status).toBe("done");
    expect(merged[0].takes).toHaveLength(2);
  });

  it("an overlapping page cannot interleave an older card above a newer one", () => {
    // New work landed while the feed was open, so page 2 repeats a row.
    const page1 = [
      generation("a", "2026-08-29T09:00:00Z"),
      generation("b", "2026-08-29T08:00:00Z"),
    ];
    const page2 = [
      generation("b", "2026-08-29T08:00:00Z"),
      generation("c", "2026-08-29T07:00:00Z"),
    ];
    const merged = generationsMerged(generationsMerged([], page1), page2);
    expect(merged.map((g) => g.id)).toEqual(["a", "b", "c"]);
  });

  it("keeps insertion order for rows the clock cannot separate", () => {
    const merged = generationsMerged(
      [],
      [
        generation("first", "not a date"),
        generation("second", "not a date"),
      ],
    );
    expect(merged.map((g) => g.id)).toEqual(["first", "second"]);
  });

  it("sorts an undated row below every dated one instead of crashing", () => {
    const merged = generationsMerged(
      [],
      [
        generation("undated", ""),
        generation("dated", "2026-08-20T00:00:00Z"),
      ],
    );
    expect(merged.map((g) => g.id)).toEqual(["dated", "undated"]);
  });
});

// ── 2. Discard / restore ──────────────────────────────────────────────────

describe("takeStateSet — the optimistic flip", () => {
  const list = [
    generation("a", "2026-08-29T09:00:00Z"),
    generation("b", "2026-08-29T08:00:00Z"),
  ];

  it("discards one take and leaves its siblings and other cards alone", () => {
    const next = takeStateSet(list, "a", 1, "discarded");
    expect(takeStateOf(next[0].takes![1])).toBe("discarded");
    expect(takeStateOf(next[0].takes![0])).toBe("fresh");
    expect(next[1]).toBe(list[1]);
  });

  it("restores it again", () => {
    const discarded = takeStateSet(list, "a", 1, "discarded");
    const restored = takeStateSet(discarded, "a", 1, "fresh");
    expect(takeStateOf(restored[0].takes![1])).toBe("fresh");
  });

  it("is identity for a generation the feed does not hold", () => {
    expect(takeStateSet(list, "nope", 0, "discarded")).toBe(list);
  });

  it("is identity for a take index the generation does not have", () => {
    expect(takeStateSet(list, "a", 7, "discarded")).toBe(list);
  });

  it("records the catalog id a publish came back with", () => {
    const next = takeStateSet(list, "a", 0, "published", "lofi--neon-rain");
    expect(next[0].takes![0].state).toBe("published");
    expect(next[0].takes![0].published_track_id).toBe("lofi--neon-rain");
  });

  it("leaves an id the store already knew alone when none is passed", () => {
    const seeded = takeStateSet(list, "a", 0, "published", "lofi--neon-rain");
    const flipped = takeStateSet(seeded, "a", 0, "discarded");
    expect(flipped[0].takes![0].published_track_id).toBe("lofi--neon-rain");
  });
});

describe("the card's split", () => {
  it("hides the discarded ones and counts them for the toggle", () => {
    const gen = generation("a", "2026-08-29T09:00:00Z", {
      takes: [take(0), take(1, { state: "discarded" }), take(2)],
    });
    expect(visibleTakes(gen).map((t) => t.index)).toEqual([0, 2]);
    expect(discardedTakes(gen).map((t) => t.index)).toEqual([1]);
    expect(discardedLabel(discardedTakes(gen).length)).toBe("1 discarded");
    expect(discardedLabel(3)).toBe("3 discarded");
  });

  it("reads a missing or unknown state as fresh", () => {
    expect(takeStateOf({ index: 0, file: "a.wav" })).toBe("fresh");
    expect(takeStateOf(take(0, { state: null }))).toBe("fresh");
  });

  it("survives a generation with no takes at all", () => {
    const gen = generation("a", "2026-08-29T09:00:00Z", { takes: null });
    expect(visibleTakes(gen)).toEqual([]);
    expect(discardedTakes(gen)).toEqual([]);
  });

  it("counts a take as published from either column", () => {
    expect(isPublishedTake(take(0, { state: "published" }))).toBe(true);
    expect(
      isPublishedTake(take(0, { published_track_id: "lofi--neon-rain" })),
    ).toBe(true);
    expect(isPublishedTake(take(0))).toBe(false);
  });
});

// ── 3. Refresh ────────────────────────────────────────────────────────────

describe("generationReplaced — reconcile in place", () => {
  const list = [
    generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
    generation("b", "2026-08-29T08:00:00Z"),
  ];

  it("swaps the card without moving it", () => {
    const next = generationReplaced(list, generation("a", "2026-08-29T09:00:00Z"));
    expect(next.map((g) => g.id)).toEqual(["a", "b"]);
    expect(next[0].status).toBe("done");
    expect(next[1]).toBe(list[1]);
  });

  it("ignores an answer for a card the feed does not hold", () => {
    expect(generationReplaced(list, generation("z", "2026-08-29T09:00:00Z"))).toBe(
      list,
    );
  });

  it("ignores an answer with no id rather than guessing", () => {
    const headless = { ...generation("a", "2026-08-29T09:00:00Z"), id: "" };
    expect(generationReplaced(list, headless)).toBe(list);
  });
});

describe("readGeneration — the three refusals stay distinct", () => {
  it("done is terminal, silent and offers nothing", () => {
    const read = readGeneration(generation("a", "2026-08-29T09:00:00Z"));
    expect(read).toEqual({
      status: "done",
      resumable: false,
      degraded: false,
      note: null,
      terminal: true,
    });
  });

  it("pending offers the resume lane and says nothing yet", () => {
    const read = readGeneration(
      generation("a", "2026-08-29T09:00:00Z", { status: "pending" }),
    );
    expect(read.resumable).toBe(true);
    expect(read.terminal).toBe(false);
    expect(read.note).toBeNull();
    expect(read.degraded).toBe(false);
  });

  it("a degraded refresh keeps the card pending AND resumable — it is a blip", () => {
    const read = readGeneration(
      generation("a", "2026-08-29T09:00:00Z", {
        status: "pending",
        degraded: true,
      }),
    );
    expect(read.status).toBe("pending");
    expect(read.degraded).toBe(true);
    expect(read.resumable).toBe(true);
    expect(read.terminal).toBe(false);
    expect(read.note).toBe(DEGRADED_NOTE);
  });

  it("stale is terminal and NOT resumable — ACE answered, it just forgot", () => {
    const read = readGeneration(
      generation("a", "2026-08-29T09:00:00Z", { status: "stale" }),
    );
    expect(read.status).toBe("stale");
    expect(read.resumable).toBe(false);
    expect(read.terminal).toBe(true);
    expect(read.degraded).toBe(false);
    expect(read.note).toBe(STALE_NOTE);
  });

  it("failed carries ACE's own words", () => {
    const read = readGeneration(
      generation("a", "2026-08-29T09:00:00Z", {
        status: "failed",
        error: "CUDA out of memory",
      }),
    );
    expect(read.status).toBe("failed");
    expect(read.note).toBe("CUDA out of memory");
    expect(read.resumable).toBe(false);
    expect(read.terminal).toBe(true);
  });

  it("failed without a reason still reads as failed", () => {
    const read = readGeneration(
      generation("a", "2026-08-29T09:00:00Z", { status: "failed" }),
    );
    expect(read.note).toBe(FAILED_NOTE);
  });
});

// ── 4. Card gating ────────────────────────────────────────────────────────

describe("the card's header", () => {
  it("titles the card with the prompt, collapsed to one line", () => {
    expect(
      generationTitle(
        generation("a", "2026-08-29T09:00:00Z", {
          request: { prompt: "  warm lofi keys,\n  tape hiss  " },
        }),
      ),
    ).toBe("warm lofi keys, tape hiss");
  });

  it("truncates a very long prompt rather than breaking the row", () => {
    const long = "a".repeat(400);
    const title = generationTitle(
      generation("a", "2026-08-29T09:00:00Z", { request: { prompt: long } }),
    );
    expect(title.length).toBeLessThan(100);
    expect(title.endsWith("…")).toBe(true);
  });

  it("names a generation whose prompt never made it to the store", () => {
    expect(
      generationTitle(generation("a", "2026-08-29T09:00:00Z", { request: {} })),
    ).toBe("Untitled generation");
    expect(
      generationTitle(generation("a", "2026-08-29T09:00:00Z", { request: null })),
    ).toBe("Untitled generation");
  });

  it("chips only the parameters that were actually recorded", () => {
    const chips = generationChips(
      generation("a", "2026-08-29T09:00:00Z", {
        request: {
          prompt: "x",
          genre_folder: "techno",
          audio_duration: 181.4,
          bpm: 138,
          batch_size: 2,
        },
      }),
    );
    expect(chips).toEqual(["techno", "181s", "138 BPM", "2 takes"]);
  });

  it("says 'take' in the singular, and reads an edit's lineage field", () => {
    const chips = generationChips(
      generation("a", "2026-08-29T09:00:00Z", {
        request: { genre_folder: "lofi - ambient", task_type: "repaint", batch_size: 1 },
      }),
    );
    expect(chips).toEqual(["lofi - ambient", "repaint", "1 take"]);
  });

  it("chips nothing for a request the store never kept", () => {
    expect(
      generationChips(generation("a", "2026-08-29T09:00:00Z", { request: null })),
    ).toEqual([]);
  });

  it("renders an unparseable timestamp as a dash, not as Invalid Date", () => {
    expect(formatCreatedAt("nonsense")).toBe("—");
    expect(formatCreatedAt(null)).toBe("—");
    expect(formatCreatedAt("2026-08-29T09:00:00Z")).not.toBe("—");
  });
});

describe("generationsFromPayload — either spelling of a list", () => {
  const rows = [generation("a", "2026-08-29T09:00:00Z")];

  it("reads the router's bare array", () => {
    expect(generationsFromPayload(rows)).toBe(rows);
  });

  it("reads the plan's envelope", () => {
    expect(generationsFromPayload({ generations: rows })).toBe(rows);
  });

  it("reads an empty answer as an empty feed, whichever way it is spelled", () => {
    expect(generationsFromPayload([])).toEqual([]);
    expect(generationsFromPayload({})).toEqual([]);
    expect(generationsFromPayload({ generations: null })).toEqual([]);
  });
});

describe("hasMorePages", () => {
  it("a full page means there may be more", () => {
    expect(hasMorePages(10, 10)).toBe(true);
  });
  it("a short page is the end of the feed", () => {
    expect(hasMorePages(3, 10)).toBe(false);
    expect(hasMorePages(0, 10)).toBe(false);
  });
});

// ── 5. Feed folds ─────────────────────────────────────────────────────────

describe("feed folds", () => {
  it("landing clears the first-load flag and sets hasMore from the page size", () => {
    const next = feedLanded(
      INITIAL_FEED_STATE,
      [generation("a", "2026-08-29T09:00:00Z"), generation("b", "2026-08-29T08:00:00Z")],
      2,
    );
    expect(next.loading).toBe(false);
    expect(next.loadingMore).toBe(false);
    expect(next.hasMore).toBe(true);
    expect(next.offset).toBe(2);
    expect(next.error).toBeNull();
  });

  it("advances the offset by what the SERVER sent, not by what the merge kept", () => {
    const first = feedLanded(
      INITIAL_FEED_STATE,
      [generation("a", "2026-08-29T09:00:00Z"), generation("b", "2026-08-29T08:00:00Z")],
      2,
    );
    // Page 2 repeats "b" — one row of the store was still consumed by it.
    const second = feedLanded(
      first,
      [generation("b", "2026-08-29T08:00:00Z"), generation("c", "2026-08-29T07:00:00Z")],
      2,
    );
    expect(second.generations).toHaveLength(3);
    expect(second.offset).toBe(4);
  });

  it("a short page ends the feed", () => {
    const next = feedLanded(INITIAL_FEED_STATE, [generation("a", "2026-08-29T09:00:00Z")], 2);
    expect(next.hasMore).toBe(false);
  });

  it("loadingMore only engages when there is more and nothing in flight", () => {
    const ready: FeedState = {
      ...INITIAL_FEED_STATE,
      loading: false,
      hasMore: true,
    };
    expect(feedLoadingMore(ready).loadingMore).toBe(true);
    // No-ops, returned by identity so a double click cannot double-fetch.
    expect(feedLoadingMore({ ...ready, hasMore: false })).toEqual({
      ...ready,
      hasMore: false,
    });
    expect(feedLoadingMore({ ...ready, loadingMore: true }).loadingMore).toBe(true);
    expect(feedLoadingMore(INITIAL_FEED_STATE)).toBe(INITIAL_FEED_STATE);
  });

  it("a failure keeps the rows already on screen and carries the words verbatim", () => {
    const loaded = feedLanded(INITIAL_FEED_STATE, [generation("a", "2026-08-29T09:00:00Z")], 2);
    const failed = feedFailed(loaded, new Error("Request failed (HTTP 500)"));
    expect(failed.generations).toHaveLength(1);
    expect(failed.loading).toBe(false);
    expect(failed.loadingMore).toBe(false);
    expect(failed.error).toBe("Request failed (HTTP 500)");
  });

  it("a thrown non-Error still says something", () => {
    expect(feedFailed(INITIAL_FEED_STATE, "boom").error).toBe(
      "Could not load the generations.",
    );
  });
});

// ── 6. The hook ───────────────────────────────────────────────────────────

describe("useGenerationsFeed", () => {
  let fetchMock: MockFetch;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  /** Let the mount fetch (and any pending microtasks) settle. */
  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  function urlOf(call: unknown[]): string {
    return String(call[0]);
  }

  it("loads the first page on mount, newest first", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        generations: [
          generation("b", "2026-08-29T08:00:00Z"),
          generation("a", "2026-08-29T09:00:00Z"),
        ],
      }),
    );
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    expect(result.current.state.loading).toBe(false);
    expect(result.current.state.generations.map((g) => g.id)).toEqual(["a", "b"]);
    expect(urlOf(fetchMock.mock.calls[0])).toContain(
      "/generator/generations?limit=2&offset=0",
    );
  });

  it("loads the first page from the router's BARE array too", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, [
        generation("b", "2026-08-29T08:00:00Z"),
        generation("a", "2026-08-29T09:00:00Z"),
      ]),
    );
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    expect(result.current.state.generations.map((g) => g.id)).toEqual(["a", "b"]);
    expect(result.current.state.hasMore).toBe(true);
  });

  it("surfaces a refused list instead of spinning for ever", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "store is down" }));
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    expect(result.current.state.loading).toBe(false);
    expect(result.current.state.error).toBe("store is down");
    expect(result.current.state.generations).toEqual([]);
  });

  it("load more fetches the next offset and appends", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(200, {
          generations: [
            generation("a", "2026-08-29T09:00:00Z"),
            generation("b", "2026-08-29T08:00:00Z"),
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { generations: [generation("c", "2026-08-28T09:00:00Z")] }),
      );
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();
    expect(result.current.state.hasMore).toBe(true);

    await act(async () => {
      await result.current.loadMore();
    });

    expect(urlOf(fetchMock.mock.calls[1])).toContain(
      "/generator/generations?limit=2&offset=2",
    );
    expect(result.current.state.generations.map((g) => g.id)).toEqual([
      "a",
      "b",
      "c",
    ]);
    // A short page is the end of it.
    expect(result.current.state.hasMore).toBe(false);
  });

  it("does not fetch again once the feed has run out", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { generations: [generation("a", "2026-08-29T09:00:00Z")] }),
    );
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();
    expect(result.current.state.hasMore).toBe(false);

    await act(async () => {
      await result.current.loadMore();
    });
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("discards optimistically and PATCHes the store", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "PATCH") return jsonResponse(200, {});
      return jsonResponse(200, {
        generations: [generation("a", "2026-08-29T09:00:00Z")],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.setDiscarded("a", 1, true);
    });

    const gen = result.current.state.generations[0];
    expect(visibleTakes(gen).map((t) => t.index)).toEqual([0]);
    expect(discardedTakes(gen).map((t) => t.index)).toEqual([1]);

    const patch = fetchMock.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    )!;
    expect(urlOf(patch)).toContain("/generator/generations/a/takes/1");
    expect(JSON.parse(String((patch[1] as RequestInit).body))).toEqual({
      state: "discarded",
    });
  });

  it("rolls a refused discard back and says why, verbatim", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "PATCH") {
        return jsonResponse(422, { detail: "published takes cannot be discarded" });
      }
      return jsonResponse(200, {
        generations: [generation("a", "2026-08-29T09:00:00Z")],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.setDiscarded("a", 0, true);
    });

    // Back where it was — a row left hidden after a refusal would be a lie
    // about what the store holds.
    const gen = result.current.state.generations[0];
    expect(visibleTakes(gen).map((t) => t.index)).toEqual([0, 1]);
    expect(discardedTakes(gen)).toEqual([]);
    expect(result.current.state.error).toBe(
      "published takes cannot be discarded",
    );
  });

  it("restores a discarded take", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "PATCH") return jsonResponse(200, {});
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", {
            takes: [take(0), take(1, { state: "discarded" })],
          }),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();
    expect(discardedTakes(result.current.state.generations[0])).toHaveLength(1);

    await act(async () => {
      await result.current.setDiscarded("a", 1, false);
    });

    expect(discardedTakes(result.current.state.generations[0])).toEqual([]);
    const patch = fetchMock.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    )!;
    expect(JSON.parse(String((patch[1] as RequestInit).body))).toEqual({
      state: "fresh",
    });
  });

  it("resume re-polls and reconciles the card in place", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse(200, generation("a", "2026-08-29T09:00:00Z"));
      }
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
          generation("b", "2026-08-29T08:00:00Z"),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();
    expect(result.current.state.generations[0].status).toBe("pending");

    await act(async () => {
      await result.current.resume("a");
    });

    expect(urlOf(fetchMock.mock.calls[1])).toContain(
      "/generator/generations/a/refresh",
    );
    const [first, second] = result.current.state.generations;
    expect(first.id).toBe("a");
    expect(first.status).toBe("done");
    expect(first.takes).toHaveLength(2);
    expect(second.id).toBe("b");
    expect(result.current.resuming).toEqual([]);
  });

  it("a degraded refresh leaves the card pending, resumable and unbroken", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse(200, {
          ...generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
          degraded: true,
        });
      }
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.resume("a");
    });

    const read = readGeneration(result.current.state.generations[0]);
    expect(read.status).toBe("pending");
    expect(read.degraded).toBe(true);
    expect(read.resumable).toBe(true);
    expect(read.note).toBe(DEGRADED_NOTE);
    expect(result.current.state.error).toBeNull();
  });

  it("a stale refresh turns the card terminal and takes the resume away", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse(
          200,
          generation("a", "2026-08-29T09:00:00Z", { status: "stale", takes: [] }),
        );
      }
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.resume("a");
    });

    const read = readGeneration(result.current.state.generations[0]);
    expect(read.status).toBe("stale");
    expect(read.resumable).toBe(false);
    expect(read.terminal).toBe(true);
    expect(read.note).toBe(STALE_NOTE);
  });

  it("reconciles a refresh whose answer forgot to name the card", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        const { id: _id, ...rest } = generation("a", "2026-08-29T09:00:00Z");
        return jsonResponse(200, rest);
      }
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.resume("a");
    });

    expect(result.current.state.generations[0].id).toBe("a");
    expect(result.current.state.generations[0].status).toBe("done");
  });

  it("a refused resume says so and leaves the card alone", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST") {
        return jsonResponse(503, { detail: "Generator disabled" });
      }
      return jsonResponse(200, {
        generations: [
          generation("a", "2026-08-29T09:00:00Z", { status: "pending", takes: [] }),
        ],
      });
    });
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    await act(async () => {
      await result.current.resume("a");
    });

    expect(result.current.state.error).toBe("Generator disabled");
    expect(result.current.state.generations[0].status).toBe("pending");
    expect(result.current.resuming).toEqual([]);
  });

  it("a publish marks the take and keeps the id it came back with", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        generations: [generation("a", "2026-08-29T09:00:00Z")],
      }),
    );
    const { result } = renderHook(() => useGenerationsFeed(2));
    await flush();

    act(() => {
      result.current.notePublished("a", 0, "lofi--neon-rain");
    });

    const published = result.current.state.generations[0].takes![0];
    expect(isPublishedTake(published)).toBe(true);
    expect(published.published_track_id).toBe("lofi--neon-rain");
    // A publish is not a fetch the feed makes — it reconciles what the row
    // already did.
    expect(fetchMock.mock.calls).toHaveLength(1);
  });
});
