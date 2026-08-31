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
} from "@/lib/mind";
import { diffCounts, hasChanges, lineDiff } from "@/lib/line-diff";

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
  it("allows the automatic path only when the buffer is byte-identical", () => {
    const seen = 's("bd*4")';
    expect(autoApplyDecision(seen, seen)).toEqual({
      autoApply: true,
      why: "buffer_unchanged",
    });
  });

  it("refuses it after ANY edit, including whitespace", () => {
    // Byte-identical means byte-identical: a trailing space is still the human
    // having touched the buffer while the mind was away.
    expect(autoApplyDecision('s("bd*4")', 's("bd*4") ').autoApply).toBe(false);
    expect(autoApplyDecision('s("bd*4")', 's("bd*4")\n').why).toBe(
      "held_buffer_dirty",
    );
    expect(autoApplyDecision('s("bd*4")', 's("bd*2")').autoApply).toBe(false);
  });

  it("treats an emptied buffer as an edit, not as 'nothing there'", () => {
    expect(autoApplyDecision('s("bd*4")', "").autoApply).toBe(false);
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
    expect(sent).toEqual({ code: 's("bd*4")', intent: "more space" });
    // `b2b: false` must not be sent — the mind reads its presence, and an
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

describe("lineDiff", () => {
  it("reports the minimal edit, not a smear from the first difference", () => {
    const before = "a\nb\nc\nd";
    const after = "a\nB\nc\nd";
    const diff = lineDiff(before, after);
    // Only line 2 moved; c and d must stay `same` or the reader cannot see
    // which layer the mind actually touched.
    expect(diffCounts(diff)).toEqual({ added: 1, removed: 1 });
    expect(diff.filter((l) => l.op === "same").map((l) => l.text)).toEqual([
      "a",
      "c",
      "d",
    ]);
  });

  it("says nothing changed when nothing changed", () => {
    expect(hasChanges(lineDiff("a\nb", "a\nb"))).toBe(false);
  });

  it("handles a pure insertion and a pure deletion", () => {
    expect(diffCounts(lineDiff("a", "a\nb"))).toEqual({ added: 1, removed: 0 });
    expect(diffCounts(lineDiff("a\nb", "a"))).toEqual({ added: 0, removed: 1 });
  });
});
