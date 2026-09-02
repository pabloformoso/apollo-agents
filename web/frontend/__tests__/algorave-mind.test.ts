/**
 * §11 S5 — the mind client, the tie rule, and the diff.
 *
 * The tie rule is the one with teeth: **on a tie, the human wins** (#148).
 * Everything else here exists so a refusal reads as what it is instead of
 * being flattened into "something went wrong".
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MIND_ENDPOINT,
  MindError,
  askMind,
  autoApplyDecision,
  fetchMindModels,
} from "@/lib/mind";
import { diffLines } from "@algorave/pen";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(status: number, body: unknown, raw?: string) {
  const text = raw ?? JSON.stringify(body);
  const fn = vi.fn(async () =>
    new Response(text, { status, headers: { "content-type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("the tie rule — on a tie, the human wins", () => {
  // The implementation is the spike's, imported through lib/mind (§11.3 seam
  // 2). These assertions exist so the APP's use of it is pinned too: a change
  // to the shared module that broke this contract would otherwise only be
  // caught on the spike's side.
  it("allows the automatic path only when the buffer is byte-identical", () => {
    const seen = 's("bd*4")';
    expect(autoApplyDecision({ askedWith: seen, current: seen }).apply).toBe(true);
  });

  it("refuses it after ANY edit, including whitespace", () => {
    expect(autoApplyDecision({ askedWith: 's("bd*4")', current: 's("bd*4") ' }).apply).toBe(false);
    expect(autoApplyDecision({ askedWith: 's("bd*4")', current: 's("bd*4")\n' }).apply).toBe(false);
    expect(autoApplyDecision({ askedWith: 's("bd*4")', current: 's("bd*2")' }).apply).toBe(false);
  });

  it("treats an emptied buffer as an edit, not as 'nothing there'", () => {
    expect(autoApplyDecision({ askedWith: 's("bd*4")', current: "" }).apply).toBe(false);
  });
});

describe("askMind", () => {
  it("sends the mind's own field names, and omits what it was not given", async () => {
    const fetchSpy = stubFetch(200, { code: 's("bd*2")', reason: "sparser", stats: {} });
    await askMind({ code: 's("bd*4")', intent: "more space" });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(MIND_ENDPOINT);
    const sent = JSON.parse(String(init.body));
    // The shared `mindRequest` always emits the fields the mind defaults
    // anyway — genre, key, bars_elapsed, recent_reasons — so the wire shape
    // stays byte-identical to what the bench measured.
    expect(sent.code).toBe('s("bd*4")');
    expect(sent.intent).toBe("more space");
    expect(sent.bars_elapsed).toBe(0);
    expect(sent.recent_reasons).toEqual([]);
    // `b2b: false` must NOT be sent — the mind reads its presence, and an
    // always-present flag would change the prompt of every free-mode call.
    expect("b2b" in sent).toBe(false);
  });

  it("sends b2b only when true, and renames barsElapsed to the wire name", async () => {
    const fetchSpy = stubFetch(200, { code: "x", reason: "", stats: {} });
    await askMind({ code: "a", intent: "i", b2b: true, barsElapsed: 8 });
    const sent = JSON.parse(String((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body));
    expect(sent.b2b).toBe(true);
    expect(sent.bars_elapsed).toBe(8);
  });

  it("carries a refusal whole, keeping status and detail apart", async () => {
    stubFetch(502, {
      error: "the mind could not produce valid Strudel — keep playing what you have",
      detail: "two validator errors",
    });
    await expect(askMind({ code: "a", intent: "i" })).rejects.toMatchObject({
      status: 502,
      message: expect.stringContaining("could not produce valid Strudel"),
      detail: "two validator errors",
    });
  });

  it("separates what a retry can fix from what it cannot", async () => {
    // 503 is "the validator is not installed" — asking again changes nothing.
    stubFetch(503, { error: "validator unavailable", detail: "" });
    const notWorth = await askMind({ code: "a", intent: "i" }).catch((e) => e);
    expect((notWorth as MindError).worthRetrying).toBe(false);

    stubFetch(504, { error: "no answer in time", detail: "" });
    const worth = await askMind({ code: "a", intent: "i" }).catch((e) => e);
    expect((worth as MindError).worthRetrying).toBe(true);
  });

  it("refuses a 200 that carries no code rather than wiping the buffer", async () => {
    stubFetch(200, { reason: "hmm", stats: {} });
    await expect(askMind({ code: "a", intent: "i" })).rejects.toThrow(
      /without any code/,
    );
  });

  it("does not pretend an HTML error page is an answer", async () => {
    stubFetch(500, null, "<html>502 Bad Gateway</html>");
    await expect(askMind({ code: "a", intent: "i" })).rejects.toThrow(
      /not JSON/,
    );
  });
});

describe("diffLines — the shared implementation", () => {
  const counts = (d: { type: string }[]) => ({
    added: d.filter((l) => l.type === "add").length,
    removed: d.filter((l) => l.type === "del").length,
  });

  it("reports the minimal edit, not a smear from the first difference", () => {
    const diff = diffLines("a\nb\nc\nd", "a\nB\nc\nd") as { type: string; text: string }[];
    expect(counts(diff)).toEqual({ added: 1, removed: 1 });
    expect(diff.filter((l) => l.type === "same").map((l) => l.text)).toEqual(["a", "c", "d"]);
  });

  it("says nothing changed when nothing changed", () => {
    const diff = diffLines("a\nb", "a\nb") as { type: string }[];
    expect(diff.every((l) => l.type === "same")).toBe(true);
  });

  it("handles a pure insertion and a pure deletion", () => {
    expect(counts(diffLines("a", "a\nb") as { type: string }[])).toEqual({ added: 1, removed: 0 });
    expect(counts(diffLines("a\nb", "a") as { type: string }[])).toEqual({ added: 0, removed: 1 });
  });
});


// ─── the model selector ────────────────────────────────────────────────
//
// The page may CHOOSE, but only from what the mind published. The wire rule
// mirrors `b2b`: emitted when set, absent otherwise — a `model` on every call
// would be the page naming a choice nobody made, and would take the mind off
// its own default for free-mode requests.

describe("choosing a model", () => {
  it("sends `model` when one was picked", async () => {
    const fetchSpy = stubFetch(200, { code: "x", reason: "", stats: {}, model: "gpt-4o-mini" });
    await askMind({ code: "a", intent: "i", model: "gpt-4o-mini" });
    const sent = JSON.parse(String((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body));
    expect(sent.model).toBe("gpt-4o-mini");
  });

  it("omits `model` entirely when none was picked", async () => {
    const fetchSpy = stubFetch(200, { code: "x", reason: "", stats: {} });
    await askMind({ code: "a", intent: "i" });
    const sent = JSON.parse(String((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body));
    expect("model" in sent).toBe(false);
  });

  it("reads back WHICH model answered — the only way to hear a switch", async () => {
    stubFetch(200, { code: "x", reason: "", stats: {}, model: "gpt-4o" });
    expect((await askMind({ code: "a", intent: "i" })).model).toBe("gpt-4o");
  });

  it("reports a missing `model` as null rather than inventing one", async () => {
    stubFetch(200, { code: "x", reason: "", stats: {} });
    expect((await askMind({ code: "a", intent: "i" })).model).toBeNull();
  });
});

describe("fetchMindModels", () => {
  it("returns the published list and its default", async () => {
    stubFetch(200, { models: ["a", "b"], default: "a" });
    expect(await fetchMindModels()).toEqual({ models: ["a", "b"], default: "a" });
  });

  it("is null when the mind cannot be asked — the page then hides the selector", async () => {
    // A degradation, never an error: unable to CHOOSE must not mean unable to
    // play, so the page falls back to the mind's own default.
    stubFetch(502, { error: "could not reach the mind" });
    expect(await fetchMindModels()).toBeNull();
  });

  it("is null on an empty list, so a one-model mind renders no selector", async () => {
    stubFetch(200, { models: [], default: null });
    expect(await fetchMindModels()).toBeNull();
  });

  it("drops non-string entries instead of rendering them as options", async () => {
    stubFetch(200, { models: ["a", 7, null, "b"], default: "a" });
    expect(await fetchMindModels()).toEqual({ models: ["a", "b"], default: "a" });
  });

  it("survives a transport failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await fetchMindModels()).toBeNull();
  });
});
