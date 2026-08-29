/**
 * Vitest unit tests for the G4 score surface.
 *
 *   1. `canScoreTake` / `buildCritiqueRequest` — what the row is allowed to
 *      send, and the body it assembles from the take the page PERSISTED.
 *   2. `bandTone` — the one comparison the whole chip fold hangs off,
 *      tested on its own including both edges of the band.
 *   3. `scoreChips` / `scoreVerdict` — the fold from a wire response to what
 *      the panel renders: reference-informed metrics carrying their band and
 *      reading in/out of it, advisory ones marked as such, and a
 *      reference-less genre folding to NO chips (the note is the answer).
 *   4. The score state machine, as pure folds and then through
 *      `useTakeScore` with a stubbed `fetch` — including a refusal carried
 *      verbatim and a re-score that keeps the old numbers on screen.
 *
 * Fetch is stubbed the same way `generator-publish.test.tsx` does it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  INITIAL_SCORE_STATE,
  bandTone,
  buildCritiqueRequest,
  canScoreTake,
  scoreChips,
  scoreFailed,
  scoreStarted,
  scoreSucceeded,
  scoreVerdict,
  useTakeScore,
  type CritiqueBand,
  type CritiqueResponse,
  type ScoreState,
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
  prompt: "warm deep house, dusty rhodes, patient groove",
  lyrics: "",
  metas: {
    bpm: 122,
    duration: 181.4,
    genres: "deep house",
    keyscale: "A Minor",
    timesignature: "4",
  },
  seed_value: 12345,
};

/** A take scored comfortably inside its genre's bands. */
const PASSED: CritiqueResponse = {
  passed: true,
  reference_genre: "deep",
  reference_informed: { centroid_hz: 4400.4, tilt_db_per_oct: -3.42 },
  advisory: { lufs: -17.2, lra: 4.05, crest_db: 11.94 },
  bands: {
    centroid_hz: {
      min: 1734.8,
      max: 11934.5,
      reference_min: 4336.9,
      reference_max: 4773.8,
    },
    tilt_db_per_oct: {
      min: -11.89,
      max: 4.97,
      reference_min: -3.89,
      reference_max: -3.03,
    },
    advisory_lufs: {
      min: -18.0,
      max: -16.9,
      reference_min: -18.0,
      reference_max: -16.9,
    },
  },
  failures: [],
  critique: "It lands where the brief asked. Open the top end a little.",
  note: null,
};

/** The same take, a long way outside them. */
const FAILED: CritiqueResponse = {
  ...PASSED,
  passed: false,
  reference_informed: { centroid_hz: 14200.9, tilt_db_per_oct: -3.42 },
  failures: ["centroid 14201Hz outside [1735, 11935]"],
  critique: null,
};

/** A genre nobody has extracted references for yet. */
const NO_VERDICT: CritiqueResponse = {
  passed: null,
  reference_genre: "techno",
  reference_informed: null,
  advisory: null,
  bands: null,
  failures: [],
  critique: null,
  note: "no references for genre 'techno' in quality_references.json (has: ambient, deep, lofi)",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Error" : "OK",
    json: async () => body,
  } as Response;
}

function chipFor(res: CritiqueResponse, key: string) {
  const chip = scoreChips(res).find((c) => c.key === key);
  if (!chip) throw new Error(`no chip for ${key}`);
  return chip;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── 1. What the row may send ──────────────────────────────────────────────

describe("canScoreTake", () => {
  it("accepts any take that carries audio", () => {
    expect(canScoreTake(TAKE)).toBe(true);
  });

  it("accepts a take whose metadata never parsed", () => {
    // The bench measures AUDIO. A take with no bpm and no key cannot be
    // published, but it is exactly the one worth a second opinion.
    expect(
      canScoreTake({ index: 0, file: ACE_FIELD, result_parse_error: "bad json" }),
    ).toBe(true);
  });

  it("refuses a take with no file at all", () => {
    expect(canScoreTake({ index: 0, file: "   " })).toBe(false);
  });
});

describe("buildCritiqueRequest", () => {
  it("sends the DECODED path, the metas it has, and no task id", () => {
    const body = buildCritiqueRequest(TAKE, { genreFolder: "deep house" });
    expect(body).toEqual({
      file: ACE_FILE,
      metas: { bpm: 122, keyscale: "A Minor", duration: 181.4 },
      prompt: "warm deep house, dusty rhodes, patient groove",
      genre_folder: "deep house",
    });
    expect(body).not.toHaveProperty("task_id");
  });

  it("omits metadata the take does not have rather than guessing it", () => {
    const body = buildCritiqueRequest(
      { index: 1, file: ACE_FIELD, metas: { keyscale: "   " } },
      { genreFolder: "lofi - ambient" },
    );
    expect(body.metas).toEqual({});
    expect(body).not.toHaveProperty("prompt");
  });

  it("carries the take's own prompt, which only the page holds", () => {
    const body = buildCritiqueRequest(TAKE, { genreFolder: "deep house" });
    expect(body.prompt).toBe(TAKE.prompt);
  });
});

// ── 2. The one comparison ─────────────────────────────────────────────────

describe("bandTone", () => {
  const band: CritiqueBand = {
    min: -10,
    max: 10,
    reference_min: -2,
    reference_max: 2,
  };

  it("reads a value inside the band as in", () => {
    expect(bandTone(0, band)).toBe("in");
  });

  it("counts both edges as inside — the bench's own comparison is inclusive", () => {
    expect(bandTone(-10, band)).toBe("in");
    expect(bandTone(10, band)).toBe("in");
  });

  it("reads a value past either edge as out", () => {
    expect(bandTone(-10.01, band)).toBe("out");
    expect(bandTone(10.01, band)).toBe("out");
  });

  it("is unknown without a value or without a band", () => {
    expect(bandTone(null, band)).toBe("unknown");
    expect(bandTone(undefined, band)).toBe("unknown");
    expect(bandTone(Number.NaN, band)).toBe("unknown");
    expect(bandTone(0, null)).toBe("unknown");
  });
});

// ── 3. The chip fold ──────────────────────────────────────────────────────

describe("scoreChips", () => {
  it("renders each reference-informed metric with its value and band", () => {
    const centroid = chipFor(PASSED, "centroid_hz");
    expect(centroid.label).toBe("centroid");
    expect(centroid.value).toBe("4400 Hz");
    // The band is rounded to the metric's own precision — a tenth of a
    // hertz at four figures is noise, not information.
    expect(centroid.band).toBe("1735–11935");
    expect(centroid.tone).toBe("in");

    const tilt = chipFor(PASSED, "tilt_db_per_oct");
    expect(tilt.value).toBe("-3.4 dB/oct");
    expect(tilt.band).toBe("-11.9–5.0");
    expect(tilt.tone).toBe("in");
  });

  it("marks an out-of-band metric out, and leaves the others alone", () => {
    expect(chipFor(FAILED, "centroid_hz").tone).toBe("out");
    expect(chipFor(FAILED, "tilt_db_per_oct").tone).toBe("in");
  });

  it("keeps LUFS, LRA and crest advisory — they are reported, never failed", () => {
    for (const key of ["lufs", "lra", "crest_db"]) {
      expect(chipFor(PASSED, key).tone).toBe("advisory");
    }
    expect(chipFor(PASSED, "lufs").value).toBe("-17.2 LUFS");
    // Loudness is the only advisory metric with a reference range at all.
    expect(chipFor(PASSED, "lufs").band).toBe("-18.0–-16.9");
    expect(chipFor(PASSED, "crest_db").band).toBeNull();
  });

  it("shows a dash for a metric the bench could not measure", () => {
    const partial: CritiqueResponse = {
      ...PASSED,
      reference_informed: { centroid_hz: null, tilt_db_per_oct: -3.42 },
    };
    const centroid = chipFor(partial, "centroid_hz");
    expect(centroid.value).toBe("—");
    expect(centroid.tone).toBe("unknown");
  });

  it("keeps a metric readable when its band is missing", () => {
    const bandless: CritiqueResponse = {
      ...PASSED,
      bands: { tilt_db_per_oct: PASSED.bands!.tilt_db_per_oct },
    };
    const centroid = chipFor(bandless, "centroid_hz");
    expect(centroid.value).toBe("4400 Hz");
    expect(centroid.band).toBeNull();
    expect(centroid.tone).toBe("unknown");
  });

  it("folds a verdict-less response to no chips at all", () => {
    // Nothing was measured, so there is nothing to draw — the note is the
    // whole answer for a genre with no committed references.
    expect(scoreChips(NO_VERDICT)).toEqual([]);
  });
});

describe("scoreVerdict", () => {
  it("names the reference genre when the take sits inside it", () => {
    expect(scoreVerdict(PASSED)).toBe("Sits inside the deep references.");
  });

  it("carries the bench's own words when it does not", () => {
    expect(scoreVerdict(FAILED)).toBe(
      "Outside the deep references: centroid 14201Hz outside [1735, 11935].",
    );
  });

  it("says there is nothing to compare against when there are no bands", () => {
    expect(scoreVerdict(NO_VERDICT)).toBe("No reference bands for this genre yet.");
  });

  it("does not invent a reason when the bench failed without naming one", () => {
    expect(scoreVerdict({ ...FAILED, failures: [] })).toBe(
      "Outside the deep references.",
    );
  });
});

// ── 4. The state machine ──────────────────────────────────────────────────

describe("score folds", () => {
  it("keeps the previous numbers on screen while a re-score is in flight", () => {
    // Blanking the panel mid-request would read as "those were wrong".
    const scored: ScoreState = {
      phase: "scored",
      result: PASSED,
      error: null,
    };
    expect(scoreStarted(scored)).toEqual({
      phase: "scoring",
      result: PASSED,
      error: null,
    });
  });

  it("clears a previous error when a new score starts", () => {
    const failed: ScoreState = {
      phase: "failed",
      result: null,
      error: "boom",
    };
    expect(scoreStarted(failed).error).toBeNull();
  });

  it("lands the result", () => {
    expect(scoreSucceeded(INITIAL_SCORE_STATE, PASSED)).toEqual({
      phase: "scored",
      result: PASSED,
      error: null,
    });
  });

  it("carries a refusal verbatim", () => {
    const state = scoreFailed(
      INITIAL_SCORE_STATE,
      new Error("The ACE-Step generator is not available"),
    );
    expect(state.phase).toBe("failed");
    expect(state.error).toBe("The ACE-Step generator is not available");
  });

  it("falls back to its own words for a non-Error throw", () => {
    expect(scoreFailed(INITIAL_SCORE_STATE, "nope").error).toBe(
      "Could not score the take.",
    );
  });
});

describe("useTakeScore", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("walks idle → scoring → scored and posts the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, PASSED));
    const { result } = renderHook(() => useTakeScore());

    expect(result.current.state).toEqual(INITIAL_SCORE_STATE);

    await act(async () => {
      await result.current.score(
        buildCritiqueRequest(TAKE, { genreFolder: "deep house" }),
      );
    });

    expect(result.current.state.phase).toBe("scored");
    expect(result.current.state.result).toEqual(PASSED);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/generator/critique");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).file).toBe(ACE_FILE);
  });

  it("carries a server refusal verbatim and keeps the panel open", async () => {
    const refusal =
      "file '/tmp/elsewhere.wav' is not under /home/pablo/code/ACE-Step-1.5/…";
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: refusal }));
    const { result } = renderHook(() => useTakeScore());

    await act(async () => {
      await result.current.score(
        buildCritiqueRequest(TAKE, { genreFolder: "deep house" }),
      );
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe(refusal);
  });

  it("accepts a verdict-less answer as a result, not an error", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, NO_VERDICT));
    const { result } = renderHook(() => useTakeScore());

    await act(async () => {
      await result.current.score(
        buildCritiqueRequest(TAKE, { genreFolder: "techno" }),
      );
    });

    expect(result.current.state.phase).toBe("scored");
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.result?.passed).toBeNull();
    expect(result.current.state.result?.note).toContain("no references");
  });

  it("re-scores after a failure without losing the last good numbers", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, PASSED))
      .mockResolvedValueOnce(jsonResponse(502, { detail: "ACE broke" }));
    const { result } = renderHook(() => useTakeScore());
    const body = buildCritiqueRequest(TAKE, { genreFolder: "deep house" });

    await act(async () => {
      await result.current.score(body);
    });
    await act(async () => {
      await result.current.score(body);
    });

    expect(result.current.state.phase).toBe("failed");
    expect(result.current.state.error).toBe("ACE broke");
    expect(result.current.state.result).toEqual(PASSED);
  });
});
