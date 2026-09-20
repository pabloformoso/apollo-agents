/**
 * §11 S8 — the run mirror's server half, now carrying WHY.
 *
 * The state arrives from a browser, so every field is validated and bounded
 * here: a history entry the viewer would render is never trusted as-is.
 */
import { describe, expect, it } from "vitest";
import { GET, POST } from "@/app/api/algorave/run/route";

const url = (id: string) => `http://localhost/api/algorave/run?id=${id}`;

async function publish(id: string, body: unknown) {
  return POST(new Request(url(id), { method: "POST", body: JSON.stringify(body) }));
}

describe("the run route carries the applied history", () => {
  it("stores and returns history, thinking, intent and model", async () => {
    const change = {
      source: "mind", bar: 16, reason: "sparser hats", model: "google/gemma-4-e4b",
      added: 1, removed: 1, lines: ['s("hh*4")'], ts: 5,
    };
    expect((await publish("r1", {
      buffer: "x", pen: "mind", barsNow: 16, phraseBars: 8, reason: "",
      history: [change], thinking: true, intent: "darker", model: "google/gemma-4-e4b",
    })).status).toBe(200);
    const body = await (await GET(new Request(url("r1")))).json();
    expect(body.history).toEqual([change]);
    expect(body.thinking).toBe(true);
    expect(body.intent).toBe("darker");
    expect(body.model).toBe("google/gemma-4-e4b");
  });

  it("defaults the new fields for an older operator that does not send them", async () => {
    await publish("r2", { buffer: "x", pen: "human", barsNow: 0, phraseBars: 8, reason: "r" });
    const body = await (await GET(new Request(url("r2")))).json();
    expect(body.history).toEqual([]);
    expect(body.thinking).toBe(false);
    expect(body.intent).toBe("");
    expect(body.model).toBeNull();
  });

  it("bounds what it will remember: six changes, sane types, clipped text", async () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      source: i % 2 ? "human" : "mind", bar: i, reason: `r${i}`, model: null,
      added: 1, removed: 0, lines: Array.from({ length: 60 }, () => "l"), ts: i,
    }));
    await publish("r3", {
      buffer: "x", history: [...many, "garbage", { source: "alien", bar: -4, reason: 42, lines: "no" }],
      intent: "i".repeat(1000),
    });
    const body = await (await GET(new Request(url("r3")))).json();
    expect(body.history).toHaveLength(6);
    expect(body.history[0].reason).toBe("r15");
    expect(body.history[0].lines).toHaveLength(24);
    const last = body.history[5];
    expect(last).toMatchObject({ source: "mind", bar: 0, reason: "", lines: [] });
    expect(body.intent).toHaveLength(200);
  });
});
