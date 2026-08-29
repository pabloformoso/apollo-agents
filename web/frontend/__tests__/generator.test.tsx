/**
 * Vitest unit tests for the G1 ACE-Step surface.
 *
 *   1. The pure folds behind the polling state machine (`applySnapshot`,
 *      `applyPollError`, `etaRemaining`) — transitions without timers.
 *   2. `useGeneratorTask` driven end-to-end through `renderHook` with a
 *      stubbed `fetch` and fake timers: pending → done at the 3 s cadence,
 *      a degraded blip that must NOT fail the task, a failed task, a 409
 *      refusal rendered verbatim, and the ETA countdown maths.
 *   3. `GenerateTrackTile`'s feature-flag gating — hidden / disabled with
 *      the VRAM tooltip / enabled.
 *
 * Fetch is stubbed the way `lib/__tests__/api.test.ts` does it (a
 * `vi.stubGlobal("fetch", …)` returning hand-rolled Response shapes); the
 * hooks are exercised through `renderHook` + `act` the way
 * `__tests__/live.test.ts` drives `useLiveSession`.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import React from "react";

import {
  INITIAL_TASK_STATE,
  POLL_INTERVAL_MS,
  applyPollError,
  applySnapshot,
  etaRemaining,
  GeneratorError,
  takeAudioUrl,
  useGeneratorTask,
  type GeneratorTaskState,
  type Take,
  type TaskSnapshot,
} from "@/lib/generator";
import {
  GenerateTrackTile,
  VRAM_BLOCKED_TOOLTIP,
} from "@/components/ember/GenerateTrackTile";

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

const TAKES: Take[] = [
  {
    index: 0,
    file: "outputs/ace/abc_0.wav",
    prompt: "warm lofi keys",
    lyrics: "",
    metas: {
      bpm: 82,
      duration: 181.4,
      genres: "lofi",
      keyscale: "A minor",
      timesignature: "4/4",
    },
    seed_value: 4242,
  },
  {
    index: 1,
    file: "outputs/ace/abc_1.wav",
    prompt: "warm lofi keys",
    lyrics: "",
    metas: {
      bpm: 80,
      duration: 179.9,
      genres: "lofi",
      keyscale: "C major",
      timesignature: "4/4",
    },
    seed_value: 99,
  },
];

const BODY = {
  prompt: "warm lofi keys, tape hiss",
  audio_duration: 180,
  genre_folder: "lofi - ambient",
  batch_size: 2,
};

function pendingState(over: Partial<GeneratorTaskState> = {}): GeneratorTaskState {
  return {
    ...INITIAL_TASK_STATE,
    phase: "pending",
    taskId: "task-1",
    queuePosition: 2,
    etaSeconds: 40,
    etaAtMs: 1_000,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// ── 1. Pure folds ─────────────────────────────────────────────────────────

describe("etaRemaining — countdown maths", () => {
  it("returns null when the server could not estimate", () => {
    expect(etaRemaining(null, 0, 10_000)).toBeNull();
    expect(etaRemaining(undefined, 0, 10_000)).toBeNull();
    expect(etaRemaining(Number.NaN, 0, 10_000)).toBeNull();
  });

  it("subtracts wall time elapsed since the poll that produced the ETA", () => {
    // 40 s estimate captured at t=1000ms, read 12 s later → 28 s left.
    expect(etaRemaining(40, 1_000, 13_000)).toBe(28);
  });

  it("floors at zero instead of going negative when the job runs over", () => {
    expect(etaRemaining(10, 1_000, 60_000)).toBe(0);
  });

  it("rounds up so a part-second never reads as one second less", () => {
    expect(etaRemaining(40, 1_000, 1_500)).toBe(40);
    expect(etaRemaining(40, 1_000, 2_500)).toBe(39);
  });

  it("falls back to the raw estimate when no capture time is known", () => {
    expect(etaRemaining(17.2, null, 999_999)).toBe(18);
  });
});

describe("applySnapshot — poll folds", () => {
  it("pending refreshes the ETA and stamps the capture time", () => {
    const next = applySnapshot(
      pendingState(),
      { status: "pending", eta_seconds: 25 },
      50_000,
    );
    expect(next.phase).toBe("pending");
    expect(next.etaSeconds).toBe(25);
    expect(next.etaAtMs).toBe(50_000);
    expect(next.degraded).toBe(false);
  });

  it("a degraded poll stays pending and keeps the ETA it could not refresh", () => {
    const next = applySnapshot(
      pendingState(),
      { status: "pending", degraded: true },
      50_000,
    );
    expect(next.phase).toBe("pending");
    expect(next.degraded).toBe(true);
    // Previous estimate survives the blip so the countdown keeps ticking.
    expect(next.etaSeconds).toBe(40);
    expect(next.etaAtMs).toBe(1_000);
    expect(next.error).toBeNull();
  });

  it("done lands the takes, clears degraded and stops the clock", () => {
    const next = applySnapshot(
      pendingState({ degraded: true }),
      { status: "done", takes: TAKES },
      50_000,
    );
    expect(next.phase).toBe("done");
    expect(next.takes).toHaveLength(2);
    expect(next.degraded).toBe(false);
    expect(next.error).toBeNull();
  });

  it("failed carries the server's reason", () => {
    const next = applySnapshot(
      pendingState(),
      { status: "failed", error: "CUDA out of memory" },
      50_000,
    );
    expect(next.phase).toBe("failed");
    expect(next.error).toBe("CUDA out of memory");
  });

  it("failed without a reason still reads as a failure", () => {
    const next = applySnapshot(pendingState(), { status: "failed" }, 50_000);
    expect(next.phase).toBe("failed");
    expect(next.error).toBe("Generation failed.");
  });

  it("keeps a take whose metadata failed to parse rather than dropping it", () => {
    const broken: TaskSnapshot = {
      status: "done",
      takes: [{ index: 0, file: "a.wav", result_parse_error: "bad json" }],
    };
    const next = applySnapshot(pendingState(), broken, 50_000);
    expect(next.phase).toBe("done");
    expect(next.takes[0].result_parse_error).toBe("bad json");
  });
});

describe("applyPollError — a blip is not a failure", () => {
  it("degrades on a transport error and keeps the task alive", () => {
    const next = applyPollError(pendingState(), new TypeError("network down"));
    expect(next.phase).toBe("pending");
    expect(next.degraded).toBe(true);
    expect(next.error).toBeNull();
  });

  it("degrades on a 500 rather than tearing the card down", () => {
    const next = applyPollError(pendingState(), new GeneratorError(500, "boom"));
    expect(next.phase).toBe("pending");
    expect(next.degraded).toBe(true);
  });

  it("fails on 404 — the task is gone, polling forever would be a lie", () => {
    const next = applyPollError(
      pendingState(),
      new GeneratorError(404, "Unknown task"),
    );
    expect(next.phase).toBe("failed");
    expect(next.error).toBe("Unknown task");
    expect(next.errorStatus).toBe(404);
  });
});

// ── 2. The hook ───────────────────────────────────────────────────────────

describe("useGeneratorTask — submit + poll loop", () => {
  let fetchMock: MockFetch;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Route by URL so the order of the hook's calls doesn't matter. */
  function route(handlers: {
    post?: () => Response;
    polls?: Array<() => Response>;
  }) {
    let pollIdx = 0;
    fetchMock.mockImplementation(
      async (url: string, init?: RequestInit): Promise<Response> => {
        if (init?.method === "POST") {
          return (
            handlers.post?.() ??
            jsonResponse(200, {
              task_id: "task-1",
              queue_position: 2,
              eta_seconds: 40,
            })
          );
        }
        if (String(url).includes("/generator/tasks/")) {
          const h =
            handlers.polls?.[Math.min(pollIdx, (handlers.polls?.length ?? 1) - 1)];
          pollIdx += 1;
          return h ? h() : jsonResponse(200, { status: "pending" });
        }
        return jsonResponse(200, {});
      },
    );
  }

  async function flush(ms = 0) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("submit → pending with queue position and ETA from the POST", async () => {
    route({ polls: [() => jsonResponse(200, { status: "pending" })] });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.taskId).toBe("task-1");
    expect(result.current.state.queuePosition).toBe(2);
    expect(result.current.state.etaSeconds).toBe(40);
    expect(result.current.etaCountdown).toBe(40);
  });

  it("polls every 3 s and lands on done with the takes", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => jsonResponse(200, { status: "pending", eta_seconds: 15 }),
        () => jsonResponse(200, { status: "done", takes: TAKES }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush(); // immediate first poll

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.etaSeconds).toBe(30);

    await flush(POLL_INTERVAL_MS);
    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.etaSeconds).toBe(15);

    await flush(POLL_INTERVAL_MS);
    expect(result.current.state.phase).toBe("done");
    expect(result.current.state.takes).toHaveLength(2);
    expect(result.current.state.takes[0].metas?.bpm).toBe(82);

    // Polling stops once the task resolves.
    const callsAtDone = fetchMock.mock.calls.length;
    await flush(POLL_INTERVAL_MS * 3);
    expect(fetchMock.mock.calls.length).toBe(callsAtDone);
  });

  it("a degraded blip does NOT fail the task — the next poll still lands", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => jsonResponse(200, { status: "pending", degraded: true }),
        () => jsonResponse(200, { status: "done", takes: TAKES }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    await flush(POLL_INTERVAL_MS);

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.degraded).toBe(true);
    expect(result.current.state.error).toBeNull();

    await flush(POLL_INTERVAL_MS);
    expect(result.current.state.phase).toBe("done");
    expect(result.current.state.degraded).toBe(false);
  });

  it("a thrown poll degrades and recovers on the following poll", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => {
          throw new TypeError("Failed to fetch");
        },
        () => jsonResponse(200, { status: "done", takes: TAKES }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    await flush(POLL_INTERVAL_MS);

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.state.degraded).toBe(true);

    await flush(POLL_INTERVAL_MS);
    expect(result.current.state.phase).toBe("done");
  });

  it("a failed task surfaces the server's reason and stops polling", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => jsonResponse(200, { status: "failed", error: "CUDA OOM" }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    await flush(POLL_INTERVAL_MS);

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe("CUDA OOM");

    const callsAtFail = fetchMock.mock.calls.length;
    await flush(POLL_INTERVAL_MS * 2);
    expect(fetchMock.mock.calls.length).toBe(callsAtFail);
  });

  it("the ETA counts down each second and resets to the fresh poll value", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => jsonResponse(200, { status: "pending", eta_seconds: 12 }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    expect(result.current.etaCountdown).toBe(30);

    await flush(1000);
    expect(result.current.etaCountdown).toBe(29);
    await flush(1000);
    expect(result.current.etaCountdown).toBe(28);

    // At t≈3 s the next poll lands and the countdown restarts from the
    // server's newer estimate rather than drifting off the old one.
    await flush(1000);
    expect(result.current.etaCountdown).toBe(12);
  });

  it("holds the countdown steady through a degraded poll", async () => {
    route({
      polls: [
        () => jsonResponse(200, { status: "pending", eta_seconds: 30 }),
        () => jsonResponse(200, { status: "pending", degraded: true }),
      ],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    await flush(POLL_INTERVAL_MS);

    // 3 s elapsed against the last good 30 s estimate.
    expect(result.current.state.degraded).toBe(true);
    expect(result.current.etaCountdown).toBe(27);
  });

  it("shows no countdown when the server could not estimate", async () => {
    route({
      post: () =>
        jsonResponse(200, {
          task_id: "task-1",
          queue_position: null,
          eta_seconds: null,
        }),
      polls: [() => jsonResponse(200, { status: "pending" })],
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();

    expect(result.current.state.phase).toBe("pending");
    expect(result.current.etaCountdown).toBeNull();
    expect(result.current.state.queuePosition).toBeNull();
  });

  it("a 409 refusal keeps the form and carries the message verbatim", async () => {
    const VRAM =
      "VRAM protocol: a live session is on air — generation is refused until it ends.";
    route({ post: () => jsonResponse(409, { detail: VRAM }) });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });

    expect(result.current.state.phase).toBe("idle");
    expect(result.current.state.error).toBe(VRAM);
    expect(result.current.state.errorStatus).toBe(409);
    expect(result.current.state.taskId).toBeNull();
    // No task means no polling.
    await flush(POLL_INTERVAL_MS * 2);
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  it("a 503 refusal reports the generator as off, not as a crash", async () => {
    route({ post: () => jsonResponse(503, { detail: "Generator disabled" }) });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });

    expect(result.current.state.phase).toBe("idle");
    expect(result.current.state.errorStatus).toBe(503);
    expect(result.current.state.error).toBe("Generator disabled");
  });

  it("flattens a 422 validation body into one readable line", async () => {
    route({
      post: () =>
        jsonResponse(422, {
          detail: [
            { loc: ["body", "audio_duration"], msg: "must be 120..600" },
            { loc: ["body", "genre_folder"], msg: "unknown genre" },
          ],
        }),
    });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });

    expect(result.current.state.errorStatus).toBe(422);
    expect(result.current.state.error).toContain("audio_duration: must be 120..600");
    expect(result.current.state.error).toContain("genre_folder: unknown genre");
  });

  it("reset clears the card back to the form", async () => {
    route({ polls: [() => jsonResponse(200, { status: "done", takes: TAKES })] });
    const { result } = renderHook(() => useGeneratorTask());

    await act(async () => {
      await result.current.submit(BODY);
    });
    await flush();
    expect(result.current.state.phase).toBe("done");

    act(() => {
      result.current.reset();
    });
    expect(result.current.state).toEqual(INITIAL_TASK_STATE);
  });
});

describe("takeAudioUrl", () => {
  it("routes through the backend proxy with the path url-encoded", () => {
    const url = takeAudioUrl("outputs/ace/abc_0.wav");
    expect(url).toContain("/api/generator/audio?path=");
    expect(url).toContain("outputs%2Face%2Fabc_0.wav");
    // Never the ACE box directly — auth + LAN isolation live server-side.
    expect(url).not.toContain(":8001");
  });
});

// ── 3. Feature-flag gating ────────────────────────────────────────────────

describe("GenerateTrackTile — health gating", () => {
  let fetchMock: MockFetch;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  async function renderTile(onClick = vi.fn()) {
    const view = render(<GenerateTrackTile onClick={onClick} />);
    // Flush the health fetch.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    return { view, onClick };
  }

  it("renders nothing while health is still loading", () => {
    fetchMock.mockReturnValue(new Promise(() => {})); // never settles
    render(<GenerateTrackTile onClick={() => {}} />);
    expect(screen.queryByTestId("generator-open")).toBeNull();
  });

  it("hides the affordance when the generator is unavailable", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { available: false, blocked_by_live: false, stats: null }),
    );
    await renderTile();
    expect(screen.queryByTestId("generator-open")).toBeNull();
  });

  it("hides the affordance when the health endpoint itself errors", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await renderTile();
    expect(screen.queryByTestId("generator-open")).toBeNull();
  });

  it("shows an enabled tile when the generator is up and off air", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        available: true,
        blocked_by_live: false,
        stats: { avg_job_seconds: 40 },
      }),
    );
    const { onClick } = await renderTile();
    const btn = screen.getByTestId("generator-open") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disables the tile with the VRAM tooltip while a set is on air", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { available: true, blocked_by_live: true, stats: {} }),
    );
    const { onClick } = await renderTile();
    const btn = screen.getByTestId("generator-open") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe(VRAM_BLOCKED_TOOLTIP);
    expect(btn.title).toMatch(/VRAM protocol/i);
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });
});
