/**
 * The GPU status panel's readings.
 *
 * The distinction the whole panel exists for: REACHABLE is not RESIDENT. A box
 * started with `--no-init` answers /health while holding nothing, and reporting
 * that as merely "available" is what hid, twice, that nothing was loaded — once
 * as a slow first brief, once as an ACE that looked ready and was not.
 */
import { describe, expect, it } from "vitest";
import { readAce, readLlm } from "@/components/ember/EngineStatus";

const ace = (o: Partial<Parameters<typeof readAce>[0]> = {}) => ({
  configured: true, reachable: true, loaded: false, llm_loaded: false,
  model: "acestep-v15-turbo", lm_model: null, ...o,
});
const llm = (o: Partial<Parameters<typeof readLlm>[0]> = {}) => ({
  configured: true, reachable: true, loaded: [], known: 6, ...o,
});

describe("ACE", () => {
  it("separates 'reachable' from 'holding the GPU' — the whole point", () => {
    const idle = readAce(ace({ loaded: false }));
    expect(idle.tone).toBe("idle");
    expect(idle.headline).toBe("ready, holding nothing");

    const busy = readAce(ace({ loaded: true, lm_model: "acestep-5Hz-lm-0.6B" }));
    expect(busy.tone).toBe("holding");
    expect(busy.detail).toContain("acestep-5Hz-lm-0.6B");
  });

  it("names the model it WOULD load while idle, which is not the same claim", () => {
    expect(readAce(ace({ loaded: false })).detail).toBe("acestep-v15-turbo");
  });

  it("tells 'not configured' apart from 'not answering'", () => {
    // One is a feature that is off, the other a box that is down. Flattening
    // them would send someone to debug a server that was never meant to run.
    expect(readAce(ace({ configured: false })).headline).toBe("not configured");
    expect(readAce(ace({ reachable: false })).headline).toBe("not answering");
  });
});

describe("the local LLM", () => {
  it("reports no model loaded as idle, not as broken", () => {
    // It loads on demand; this is the line that explains a slow first brief.
    const r = readLlm(llm({ loaded: [] }));
    expect(r.tone).toBe("idle");
    expect(r.detail).toBe("6 available");
  });

  it("keeps LOADED and KNOWN as different numbers", () => {
    // "listed ≠ loadable" is recorded in the root CLAUDE.md after LM Studio
    // 400'd on every model it was still happily listing.
    const r = readLlm(llm({ loaded: ["google/gemma-4-e4b"], known: 6 }));
    expect(r.tone).toBe("holding");
    expect(r.detail).toBe("google/gemma-4-e4b");
  });

  it("does not claim anything when it cannot be reached", () => {
    expect(readLlm(llm({ reachable: false })).tone).toBe("off");
  });
});
