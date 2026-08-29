/**
 * Vitest unit tests for the G3 edit surface.
 *
 *   1. `canEditTake` / `editRangeError` — what the panel refuses to send,
 *      including the one check the backend cannot make (the source take's
 *      duration is known only HERE, because nothing re-queries the task).
 *   2. `buildEditRequest` — the payload assembled from the take the page
 *      PERSISTED plus the panel. Only the chosen mode's parameters go out,
 *      the path is the DECODED one, and no task id ever appears.
 *   3. The edit state machine, as pure folds and then through `useTakeEdit`
 *      with a stubbed `fetch`: idle → editing → submitting → chained card,
 *      with a 409 (the VRAM protocol) carried verbatim.
 *   4. The chained-card folds — lineage, dedupe, and the `variant of` order
 *      that puts the SOURCE take's published name first.
 *   5. `useGeneratorTask(pollMs, adopted)` — the chained card adopts a task
 *      handle and is polled by the very same loop as an original.
 *
 * Fetch is stubbed the same way `generator.test.tsx` does it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  DEFAULT_COVER_STRENGTH,
  INITIAL_EDIT_FORM,
  INITIAL_EDIT_STATE,
  POLL_INTERVAL_MS,
  REPAINT_TO_THE_END,
  buildEditRequest,
  canEditTake,
  chainAppended,
  chainedTaskFor,
  editCancelled,
  editChanged,
  editFailed,
  editLineage,
  editOpened,
  editRangeError,
  editSourceLabel,
  editStarted,
  editSucceeded,
  taskAdopted,
  useGeneratorTask,
  useTakeEdit,
  variantOptionsFor,
  type CreateTaskResponse,
  type EditForm,
  type EditState,
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

const RELEASED: CreateTaskResponse = {
  task_id: "edit-1",
  queue_position: 4,
  eta_seconds: 205,
};

function form(over: Partial<EditForm> = {}): EditForm {
  return { ...INITIAL_EDIT_FORM, ...over };
}

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

// ── 1. What the panel refuses to send ─────────────────────────────────────

describe("canEditTake", () => {
  it("accepts any take that carries audio", () => {
    expect(canEditTake(TAKE)).toBe(true);
  });

  it("accepts a take whose metadata did not parse", () => {
    // Weaker than canPublishTake on purpose: publishing needs a bpm and a
    // key the ingest refuses to guess; an edit only needs the audio, and
    // the result may well come back readable.
    expect(
      canEditTake({ index: 0, file: ACE_FIELD, result_parse_error: "bad json" }),
    ).toBe(true);
  });

  it("refuses a take with no file at all", () => {
    expect(canEditTake({ index: 0, file: "   " })).toBe(false);
  });
});

describe("editRangeError", () => {
  it("passes a plain in-range repaint", () => {
    expect(editRangeError(form({ start: 10, end: 20 }), 181.4)).toBeNull();
  });

  it("passes -1 as 'to the end' whatever the duration", () => {
    expect(
      editRangeError(form({ start: 120, end: REPAINT_TO_THE_END }), 181.4),
    ).toBeNull();
  });

  it("refuses a backwards or empty range", () => {
    expect(editRangeError(form({ start: 30, end: 20 }), 181.4)).toMatch(
      /before the end/,
    );
    expect(editRangeError(form({ start: 20, end: 20 }), 181.4)).toMatch(
      /before the end/,
    );
  });

  it("refuses a negative start", () => {
    expect(editRangeError(form({ start: -1, end: 20 }), 181.4)).toMatch(
      /cannot be negative/,
    );
  });

  it("refuses a negative end that is not the sentinel", () => {
    expect(editRangeError(form({ start: 0, end: -2 }), 181.4)).toMatch(/-1/);
    expect(editRangeError(form({ start: 0, end: 0 }), 181.4)).toMatch(/-1/);
  });

  it("refuses a range that runs past the take", () => {
    // The backend never re-queries the task, so it has no idea how long
    // the source is — this check exists nowhere else.
    expect(editRangeError(form({ start: 10, end: 400 }), 181.4)).toMatch(/181s/);
    expect(editRangeError(form({ start: 300, end: 400 }), 181.4)).toMatch(
      /past it/,
    );
  });

  it("skips the duration checks when ACE reported no duration", () => {
    expect(editRangeError(form({ start: 10, end: 400 }), null)).toBeNull();
    expect(editRangeError(form({ start: 10, end: 400 }))).toBeNull();
  });

  it("refuses a non-numeric range", () => {
    expect(editRangeError(form({ start: Number.NaN, end: 20 }), 181.4)).toMatch(
      /in seconds/,
    );
  });

  it("has no opinion about cover or complete", () => {
    expect(editRangeError(form({ mode: "cover", start: 99, end: 1 }), 10)).toBeNull();
    expect(
      editRangeError(form({ mode: "complete", start: 99, end: 1 }), 10),
    ).toBeNull();
  });
});

// ── 2. The payload, from persisted state ──────────────────────────────────

describe("buildEditRequest", () => {
  it("sends the DECODED path, the mode and the repaint range", () => {
    const body = buildEditRequest(TAKE, form({ start: 10, end: 20 }), {
      genreFolder: "techno",
    });

    expect(body).toEqual({
      file: ACE_FILE,
      mode: "repaint",
      prompt: TAKE.prompt,
      repainting_start: 10,
      repainting_end: 20,
      genre_folder: "techno",
    });
    // No task id: ACE's job store is mortal, its result files are not.
    expect(body).not.toHaveProperty("task_id");
    // A repaint carries no strength — the server 422s a stray parameter.
    expect(body).not.toHaveProperty("audio_cover_strength");
  });

  it("carries -1 through as 'to the end'", () => {
    const body = buildEditRequest(
      TAKE,
      form({ start: 90, end: REPAINT_TO_THE_END }),
    );
    expect(body.repainting_end).toBe(-1);
  });

  it("sends the strength for a cover and no range", () => {
    const body = buildEditRequest(TAKE, form({ mode: "cover", start: 10, end: 20 }));

    expect(body.mode).toBe("cover");
    expect(body.audio_cover_strength).toBe(DEFAULT_COVER_STRENGTH);
    expect(body).not.toHaveProperty("repainting_start");
    expect(body).not.toHaveProperty("repainting_end");
  });

  it("sends neither for a completion", () => {
    const body = buildEditRequest(
      TAKE,
      form({ mode: "complete", start: 10, end: 20, strength: 0.9 }),
    );

    expect(Object.keys(body).sort()).toEqual(["file", "mode", "prompt"]);
  });

  it("reuses the take's own prompt when the override is empty", () => {
    expect(buildEditRequest(TAKE, form({ prompt: "   " })).prompt).toBe(
      TAKE.prompt,
    );
  });

  it("prefers the override when there is one", () => {
    const body = buildEditRequest(TAKE, form({ prompt: "  more energy  " }));
    expect(body.prompt).toBe("more energy");
  });

  it("omits the prompt when neither the take nor the panel has one", () => {
    const body = buildEditRequest({ ...TAKE, prompt: "" }, form());
    expect(body).not.toHaveProperty("prompt");
  });

  it("omits a blank genre_folder rather than sending one", () => {
    expect(
      buildEditRequest(TAKE, form(), { genreFolder: "  " }),
    ).not.toHaveProperty("genre_folder");
    expect(buildEditRequest(TAKE, form(), {})).not.toHaveProperty("genre_folder");
  });
});

// ── 3a. The state machine, as pure folds ──────────────────────────────────

describe("edit folds — idle → editing → submitting → chained", () => {
  const editing: EditState = { ...INITIAL_EDIT_STATE, phase: "editing" };

  it("opens on a fresh form", () => {
    const dirty = editChanged(editing, { mode: "cover", start: 40 });
    const reopened = editOpened(editCancelled(dirty));
    expect(reopened.phase).toBe("editing");
    expect(reopened.form).toEqual(INITIAL_EDIT_FORM);
    // The default range is "the whole take from the top".
    expect(reopened.form.start).toBe(0);
    expect(reopened.form.end).toBe(REPAINT_TO_THE_END);
    expect(reopened.form.strength).toBe(DEFAULT_COVER_STRENGTH);
  });

  it("cancel returns to idle and forgets the error", () => {
    const failed = editFailed(editing, new Error("nope"));
    expect(editCancelled(failed)).toEqual(INITIAL_EDIT_STATE);
  });

  it("patches one field at a time", () => {
    const next = editChanged(editChanged(editing, { start: 10 }), { end: 20 });
    expect(next.form.start).toBe(10);
    expect(next.form.end).toBe(20);
    expect(next.form.mode).toBe("repaint");
  });

  it("submitting clears the previous error so a retry reads clean", () => {
    const next = editStarted(editFailed(editing, new Error("nope")));
    expect(next.phase).toBe("submitting");
    expect(next.error).toBeNull();
    expect(next.errorStatus).toBeNull();
  });

  it("success closes the panel — the chained card is the whole story now", () => {
    expect(editSucceeded()).toEqual(INITIAL_EDIT_STATE);
  });

  it("failure carries the server's words verbatim, with the status", () => {
    const vram = "VRAM protocol: a set is on air.";
    const err = Object.assign(new Error(vram), { status: 409 });
    const next = editFailed(editStarted(editing), err);
    expect(next.phase).toBe("failed");
    expect(next.error).toBe(vram);
  });

  it("falls back to a plain message when the throw was not an Error", () => {
    expect(editFailed(editing, "boom").error).toBe("Could not start the edit.");
  });

  it("ignores cancel and edits while the request is in flight", () => {
    const inflight = editStarted(editing);
    expect(editCancelled(inflight)).toBe(inflight);
    expect(editChanged(inflight, { start: 99 })).toBe(inflight);
    expect(editOpened(inflight)).toBe(inflight);
  });
});

// ── 3b. The hook against a stubbed backend ────────────────────────────────

describe("useTakeEdit", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("walks idle → editing → submitting → closed, and posts the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, RELEASED));
    const { result } = renderHook(() => useTakeEdit());

    expect(result.current.state.phase).toBe("idle");
    act(() => result.current.open());
    expect(result.current.state.phase).toBe("editing");
    act(() => result.current.change({ start: 10, end: 20 }));

    let released: CreateTaskResponse | null = null;
    await act(async () => {
      released = await result.current.submit(
        buildEditRequest(TAKE, result.current.state.form, {
          genreFolder: "techno",
        }),
      );
    });

    expect(released).toEqual(RELEASED);
    // The panel is gone; the chained card takes it from here.
    expect(result.current.state.phase).toBe("idle");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/generator/edit");
    expect(init.method).toBe("POST");
    const sent = JSON.parse(init.body as string);
    expect(sent.file).toBe(ACE_FILE);
    expect(sent.mode).toBe("repaint");
    expect(sent.repainting_start).toBe(10);
    expect(sent.repainting_end).toBe(20);
    expect(sent).not.toHaveProperty("task_id");
  });

  it("renders a 409 verbatim and keeps the panel open", async () => {
    const vram =
      "VRAM protocol: a set is on air. ACE-Step holds ~12.5 GB of the shared " +
      "16 GB GPU, so generating now would starve the live DJ's model.";
    fetchMock.mockResolvedValue(jsonResponse(409, { detail: vram }));
    const { result } = renderHook(() => useTakeEdit());

    act(() => result.current.open());
    await act(async () => {
      await result.current.submit(buildEditRequest(TAKE, result.current.state.form));
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe(vram);
    expect(result.current.state.errorStatus).toBe(409);
  });

  it("keeps the form after a refusal so the fix is one edit away", async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: "bad range" }));
    const { result } = renderHook(() => useTakeEdit());

    act(() => result.current.open());
    act(() => result.current.change({ mode: "cover", strength: 0.4 }));
    await act(async () => {
      await result.current.submit(buildEditRequest(TAKE, result.current.state.form));
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.form.mode).toBe("cover");
    expect(result.current.state.form.strength).toBe(0.4);
  });

  it("recovers on a retry after a refusal", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(422, { detail: "bad range" }))
      .mockResolvedValueOnce(jsonResponse(200, RELEASED));
    const { result } = renderHook(() => useTakeEdit());

    act(() => result.current.open());
    await act(async () => {
      await result.current.submit(buildEditRequest(TAKE, result.current.state.form));
    });
    expect(result.current.state.phase).toBe("failed");

    let released: CreateTaskResponse | null = null;
    await act(async () => {
      released = await result.current.submit(
        buildEditRequest(TAKE, result.current.state.form),
      );
    });
    expect(released).toEqual(RELEASED);
    expect(result.current.state.phase).toBe("idle");
  });

  it("degrades a thrown transport error into a readable failure", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useTakeEdit());

    await act(async () => {
      await result.current.submit(buildEditRequest(TAKE, INITIAL_EDIT_FORM));
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe("Failed to fetch");
  });
});

// ── 4. The chained-card folds ─────────────────────────────────────────────

describe("lineage", () => {
  it("reads as 'edited from <source>' plus what was done", () => {
    expect(editLineage("Take 1", "repaint")).toBe("edited from Take 1 · repaint");
    expect(editLineage("Neon Rain", "cover")).toBe(
      "edited from Neon Rain · cover",
    );
  });

  it("names the source by its catalog name once it is published", () => {
    expect(editSourceLabel("Take 1", "Neon Rain")).toBe("Neon Rain");
    expect(editSourceLabel("Take 1", null)).toBe("Take 1");
    expect(editSourceLabel("Take 1", "   ")).toBe("Take 1");
  });

  it("builds the chained entry from the released handle", () => {
    const chained = chainedTaskFor(RELEASED, "repaint", "Take 1");
    expect(chained.task).toBe(RELEASED);
    expect(chained.mode).toBe("repaint");
    expect(chained.source).toBe("Take 1");
    expect(chained.lineage).toBe("edited from Take 1 · repaint");
  });
});

describe("chainAppended", () => {
  it("appends in the order the edits were asked for", () => {
    const a = chainedTaskFor(RELEASED, "repaint", "Take 1");
    const b = chainedTaskFor({ ...RELEASED, task_id: "edit-2" }, "cover", "Take 1");
    expect(chainAppended(chainAppended([], a), b).map((c) => c.task.task_id)).toEqual(
      ["edit-1", "edit-2"],
    );
  });

  it("ignores a task id already on the chain", () => {
    // A double-clicked submit would otherwise render two cards polling the
    // same task, each with its own publish state.
    const a = chainedTaskFor(RELEASED, "repaint", "Take 1");
    const again = chainedTaskFor(RELEASED, "cover", "Take 1");
    const chain = chainAppended([], a);
    expect(chainAppended(chain, again)).toBe(chain);
  });
});

describe("variantOptionsFor", () => {
  it("puts the SOURCE take's published name first — it becomes the default", () => {
    expect(variantOptionsFor("Neon Rain", ["Other Piece", "Neon Rain"])).toEqual([
      "Neon Rain",
      "Other Piece",
    ]);
  });

  it("falls back to whatever the batch published when the source has not", () => {
    expect(variantOptionsFor(null, ["Other Piece"])).toEqual(["Other Piece"]);
    expect(variantOptionsFor("", [])).toEqual([]);
  });
});

// ── 5. A chained card is polled by the same loop ──────────────────────────

describe("useGeneratorTask(pollMs, adopted)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function flush(ms = 0) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("taskAdopted turns a handle into the pending state", () => {
    const state = taskAdopted(RELEASED, 1_000);
    expect(state.phase).toBe("pending");
    expect(state.taskId).toBe("edit-1");
    expect(state.queuePosition).toBe(4);
    expect(state.etaSeconds).toBe(205);
    expect(state.etaAtMs).toBe(1_000);
    expect(state.takes).toEqual([]);
  });

  it("starts pending on the adopted handle without a POST", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { status: "pending" }));
    const { result } = renderHook(() =>
      useGeneratorTask(POLL_INTERVAL_MS, RELEASED),
    );

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.taskId).toBe("edit-1");
    expect(result.current.etaCountdown).toBe(205);

    await flush();
    // Only polls — an adopted task was released by the edit endpoint.
    expect(
      fetchMock.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET"),
    ).toBe(true);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/generator/tasks/edit-1",
    );
  });

  it("polls the adopted task to done and renders its takes", async () => {
    let poll = 0;
    fetchMock.mockImplementation(async () => {
      poll += 1;
      return poll < 3
        ? jsonResponse(200, { status: "pending", eta_seconds: 30 })
        : jsonResponse(200, {
            status: "done",
            takes: [{ ...TAKE, file: `${ACE_ROOT}/edited_0.wav` }],
          });
    });

    const { result } = renderHook(() =>
      useGeneratorTask(POLL_INTERVAL_MS, RELEASED),
    );

    await flush();
    expect(result.current.state.phase).toBe("pending");
    await flush(POLL_INTERVAL_MS);
    await flush(POLL_INTERVAL_MS);

    expect(result.current.state.phase).toBe("done");
    expect(result.current.state.takes).toHaveLength(1);
    // …and that take is publishable/editable exactly like an original.
    expect(canEditTake(result.current.state.takes[0])).toBe(true);
  });

  it("a degraded blip on a chained card is a blip, not a failure", async () => {
    let poll = 0;
    fetchMock.mockImplementation(async () => {
      poll += 1;
      if (poll === 1) return jsonResponse(200, { status: "pending", degraded: true });
      return jsonResponse(200, { status: "done", takes: [TAKE] });
    });

    const { result } = renderHook(() =>
      useGeneratorTask(POLL_INTERVAL_MS, RELEASED),
    );

    await flush();
    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.degraded).toBe(true);
    // The ETA it could not refresh keeps counting down through the blip.
    expect(result.current.state.etaSeconds).toBe(205);

    await flush(POLL_INTERVAL_MS);
    expect(result.current.state.phase).toBe("done");
  });
});
