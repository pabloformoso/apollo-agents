/**
 * Vitest unit tests for the G2b publish surface.
 *
 *   1. `decodedTakePath` — the page's half of the plan's persistence rule:
 *      ACE's `file` is `/v1/audio?path=<quote(p, safe="")>` and the publisher
 *      needs `p` itself, decoded exactly once.
 *   2. `suggestDisplayName` / `canPublishTake` — the two guesses the confirm
 *      step is allowed to make.
 *   3. `buildPublishRequest` — the payload assembled from the take the page
 *      PERSISTED plus the confirm form. No task id ever goes out.
 *   4. The publish state machine, as pure folds and then through
 *      `useTakePublish` with a stubbed `fetch`: idle → confirm → publishing →
 *      published / failed, with a server refusal carried verbatim.
 *
 * Fetch is stubbed the same way `generator.test.tsx` does it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  buildPublishRequest,
  canPublishTake,
  decodedTakePath,
  INITIAL_PUBLISH_STATE,
  publishCancelled,
  publishFailed,
  publishOpened,
  publishStarted,
  publishSucceeded,
  suggestDisplayName,
  useTakePublish,
  type PublishResponse,
  type PublishState,
  type Take,
} from "@/lib/generator";

// The real shape, confirmed with the ACE session: an absolute POSIX path on
// their box, percent-encoded whole (slashes as %2F) into the `path` param.
const ACE_ROOT = "/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio";
const ACE_FILE = `${ACE_ROOT}/6f1c2b7e-9d4a-4c11-b0a3-2e5f8d7c1a90_0.wav`;
const ACE_FIELD = `/v1/audio?path=${encodeURIComponent(ACE_FILE)}`;

const TAKE: Take = {
  index: 0,
  file: ACE_FIELD,
  prompt: "dark melodic techno, hypnotic, driving",
  lyrics: "[Verse]\nneon rain",
  metas: {
    bpm: 138,
    duration: 181.4,
    genres: "techno",
    keyscale: "A Minor",
    timesignature: "4",
  },
  seed_value: 12345,
};

const PUBLISHED: PublishResponse = {
  track_id: "techno--neon-rain",
  file: "tracks/techno/Neon Rain.wav",
  display_name: "Neon Rain",
  camelot_key: "8A",
  bpm: 138,
  variant_of: null,
  note: "Ingested without madmom … run `python main.py --fix-incomplete`.",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Error" : "OK",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── 1. The persisted path ─────────────────────────────────────────────────

describe("decodedTakePath", () => {
  it("decodes ACE's file field into the server-side path", () => {
    expect(decodedTakePath(ACE_FIELD)).toBe(ACE_FILE);
  });

  it("passes an already-decoded path through untouched", () => {
    expect(decodedTakePath(ACE_FILE)).toBe(ACE_FILE);
  });

  it("passes a bare relative path through untouched", () => {
    expect(decodedTakePath("api_audio/x.wav")).toBe("api_audio/x.wav");
  });

  it("keeps a literal '+' in a filename instead of making it a space", () => {
    // `quote(p, safe="")` leaves '+' alone; URLSearchParams would not.
    const plus = `${ACE_ROOT}/take+one_0.wav`;
    expect(decodedTakePath(`/v1/audio?path=${encodeURIComponent(plus)}`)).toBe(plus);
  });

  it("survives a malformed encoding rather than throwing", () => {
    expect(decodedTakePath("/v1/audio?path=%E0%A4%A")).toBe(
      "/v1/audio?path=%E0%A4%A",
    );
  });

  it("ignores other query parameters", () => {
    expect(decodedTakePath("/v1/audio?fmt=wav&path=%2Fa%2Fb.wav")).toBe("/a/b.wav");
  });
});

// ── 2. The guesses the confirm step makes ─────────────────────────────────

describe("suggestDisplayName", () => {
  it("takes the prompt's first clause, title-cased", () => {
    expect(suggestDisplayName("dark melodic techno, hypnotic, driving")).toBe(
      "Dark Melodic Techno",
    );
  });

  it("caps the suggestion at five words", () => {
    expect(suggestDisplayName("one two three four five six seven")).toBe(
      "One Two Three Four Five",
    );
  });

  it("strips characters a filename cannot carry", () => {
    // display_name becomes the WAV's stem, so the ingest refuses these.
    expect(suggestDisplayName("rain/fall: a study")).toBe("Rain Fall A Study");
  });

  it("falls back rather than suggesting an empty name", () => {
    expect(suggestDisplayName("")).toBe("Untitled Take");
    expect(suggestDisplayName(null)).toBe("Untitled Take");
    expect(suggestDisplayName("///")).toBe("Untitled Take");
  });
});

describe("canPublishTake", () => {
  it("accepts a take carrying bpm and keyscale from the generator", () => {
    expect(canPublishTake(TAKE)).toBe(true);
  });

  it("refuses a take whose metadata did not parse", () => {
    // The ingest never guesses a bpm or a key — guessed metadata is how the
    // catalog acquired the poisoned BPMs that bridge genres live.
    expect(
      canPublishTake({ index: 0, file: ACE_FIELD, result_parse_error: "bad json" }),
    ).toBe(false);
  });

  it("refuses a take missing either half of the metadata", () => {
    expect(canPublishTake({ index: 0, file: ACE_FIELD, metas: { bpm: 138 } })).toBe(
      false,
    );
    expect(
      canPublishTake({ index: 0, file: ACE_FIELD, metas: { keyscale: "A Minor" } }),
    ).toBe(false);
  });

  it("refuses a take with no file at all", () => {
    expect(canPublishTake({ index: 0, file: "  ", metas: TAKE.metas })).toBe(false);
  });
});

// ── 3. The payload, from persisted state ──────────────────────────────────

describe("buildPublishRequest", () => {
  it("sends the DECODED path, the metas and the form's choices", () => {
    const body = buildPublishRequest(TAKE, {
      displayName: "  Neon Rain  ",
      genreFolder: "techno",
    });

    expect(body).toEqual({
      file: ACE_FILE,
      metas: { bpm: 138, keyscale: "A Minor", duration: 181.4 },
      prompt: TAKE.prompt,
      lyrics: TAKE.lyrics,
      display_name: "Neon Rain",
      genre_folder: "techno",
    });
    // No task id: ACE's job store is mortal, its result files are not.
    expect(body).not.toHaveProperty("task_id");
    // The metas that go out are ACE's three, not the whole block.
    expect(Object.keys(body.metas)).toEqual(["bpm", "keyscale", "duration"]);
  });

  it("carries variant_of when the take is a second one of the same piece", () => {
    const body = buildPublishRequest(TAKE, {
      displayName: "Neon Rain",
      genreFolder: "techno",
      variantOf: " Neon Rain ",
    });
    expect(body.variant_of).toBe("Neon Rain");
  });

  it("omits variant_of, prompt and lyrics rather than sending blanks", () => {
    const body = buildPublishRequest(
      { ...TAKE, prompt: "", lyrics: "   " },
      { displayName: "X", genreFolder: "techno", variantOf: "" },
    );
    expect(body).not.toHaveProperty("variant_of");
    expect(body).not.toHaveProperty("prompt");
    expect(body).not.toHaveProperty("lyrics");
  });

  it("sends a null duration when ACE did not report one", () => {
    const body = buildPublishRequest(
      { ...TAKE, metas: { bpm: 138, keyscale: "A Minor" } },
      { displayName: "X", genreFolder: "techno" },
    );
    expect(body.metas.duration).toBeNull();
  });
});

// ── 4a. The state machine, as pure folds ──────────────────────────────────

describe("publish folds — idle → confirm → publishing → published/failed", () => {
  const confirming: PublishState = { ...INITIAL_PUBLISH_STATE, phase: "confirm" };

  it("opens the confirm step from idle", () => {
    expect(publishOpened(INITIAL_PUBLISH_STATE).phase).toBe("confirm");
  });

  it("cancel returns to idle and forgets the error", () => {
    const failed = publishFailed(confirming, new Error("nope"));
    expect(publishCancelled(failed)).toEqual(INITIAL_PUBLISH_STATE);
  });

  it("publishing clears the previous error so a retry reads clean", () => {
    const failed = publishFailed(confirming, new Error("nope"));
    const next = publishStarted(failed);
    expect(next.phase).toBe("publishing");
    expect(next.error).toBeNull();
  });

  it("success keeps the entry the server echoed", () => {
    const next = publishSucceeded(publishStarted(confirming), PUBLISHED);
    expect(next.phase).toBe("published");
    expect(next.result?.track_id).toBe("techno--neon-rain");
    expect(next.result?.note).toContain("--fix-incomplete");
  });

  it("failure carries the server's words verbatim", () => {
    const refusal = "bpm 90 is outside the 'techno' window 120-160 BPM";
    const next = publishFailed(publishStarted(confirming), new Error(refusal));
    expect(next.phase).toBe("failed");
    expect(next.error).toBe(refusal);
  });

  it("falls back to a plain message when the throw was not an Error", () => {
    expect(publishFailed(confirming, "boom").error).toBe(
      "Could not publish the take.",
    );
  });

  it("published is terminal — it never reopens, restarts or cancels", () => {
    const done = publishSucceeded(INITIAL_PUBLISH_STATE, PUBLISHED);
    expect(publishOpened(done)).toBe(done);
    expect(publishStarted(done)).toBe(done);
    expect(publishCancelled(done)).toBe(done);
  });

  it("cancel is ignored while the request is in flight", () => {
    const inflight = publishStarted(confirming);
    expect(publishCancelled(inflight)).toBe(inflight);
  });
});

// ── 4b. The hook against a stubbed backend ────────────────────────────────

describe("useTakePublish", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("walks idle → confirm → publishing → published and posts the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, PUBLISHED));
    const { result } = renderHook(() => useTakePublish());

    expect(result.current.state.phase).toBe("idle");
    act(() => result.current.open());
    expect(result.current.state.phase).toBe("confirm");

    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, {
          displayName: "Neon Rain",
          genreFolder: "techno",
        }),
      );
    });

    expect(result.current.state.phase).toBe("published");
    expect(result.current.state.result?.track_id).toBe("techno--neon-rain");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/generator/publish");
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string);
    expect(sent.file).toBe(ACE_FILE);
    expect(sent.display_name).toBe("Neon Rain");
    expect(sent.metas).toEqual({ bpm: 138, keyscale: "A Minor", duration: 181.4 });
  });

  it("renders a 422 refusal verbatim and keeps the form open", async () => {
    const refusal =
      "track id 'techno--neon-rain' already exists in the catalog … pass --variant-of";
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: refusal }));
    const { result } = renderHook(() => useTakePublish());

    act(() => result.current.open());
    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "Neon Rain", genreFolder: "techno" }),
      );
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe(refusal);
    expect(result.current.state.result).toBeNull();
  });

  it("recovers on a retry after a refusal", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(422, { detail: "id collision" }))
      .mockResolvedValueOnce(jsonResponse(200, PUBLISHED));
    const { result } = renderHook(() => useTakePublish());

    act(() => result.current.open());
    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "Neon Rain", genreFolder: "techno" }),
      );
    });
    expect(result.current.state.phase).toBe("failed");

    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "Neon Rain II", genreFolder: "techno" }),
      );
    });
    expect(result.current.state.phase).toBe("published");
    expect(result.current.state.error).toBeNull();
  });

  it("reports a 503 as the generator being off, not a crash", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(503, { detail: "The ACE-Step generator is not available" }),
    );
    const { result } = renderHook(() => useTakePublish());

    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "X", genreFolder: "techno" }),
      );
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toContain("not available");
  });

  it("degrades a thrown transport error into a readable failure", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useTakePublish());

    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "X", genreFolder: "techno" }),
      );
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe("Failed to fetch");
  });

  it("a published take does not publish twice", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, PUBLISHED));
    const { result } = renderHook(() => useTakePublish());

    await act(async () => {
      await result.current.publish(
        buildPublishRequest(TAKE, { displayName: "Neon Rain", genreFolder: "techno" }),
      );
    });
    expect(result.current.state.phase).toBe("published");

    act(() => result.current.open());
    expect(result.current.state.phase).toBe("published");
  });
});
