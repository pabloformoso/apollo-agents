/**
 * Persistence — and, more importantly, what is deliberately NOT persisted.
 *
 * The playground's rule (§9.1, §9.2): the pen and the B2B mode never survive a
 * reload. A freshly loaded page must never fire an LLM call by itself and never
 * wake up alternating. Restoring `pen: "mind"` would mean an F5 starts asking
 * the mind for mutations with nobody watching.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearSession, loadSession, saveSession } from "@/lib/algorave-persist";

const session = {
  buffer: 's("bd*4")',
  intent: "darker",
  phraseBars: 4,
  b2bBars: 32,
  bpm: 128,
  genre: "deep",
  key: "C:minor",
  model: "gpt-4o-mini",
};

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
});

describe("round trip", () => {
  it("brings back everything a performer would hate to retype", () => {
    saveSession(session);
    expect(loadSession()).toEqual(session);
  });

  it("is null when nothing was ever saved", () => {
    expect(loadSession()).toBeNull();
  });

  it("keeps the model — a preference, unlike the pen", () => {
    // Safe to restore precisely because it arms nothing: a reloaded page still
    // asks the mind nothing until a human presses something.
    saveSession({ ...session, model: "gpt-4o" });
    expect(loadSession()?.model).toBe("gpt-4o");
  });

  it("reads a snapshot written before the selector existed as 'the default'", () => {
    // An older build saved no `model`. That must load as "" — meaning "ask the
    // mind's default" — not as undefined, which would be sent as a choice.
    localStorage.setItem(
      "apollo-algorave-v1",
      JSON.stringify({ v: 1, ...session, model: undefined }),
    );
    expect(loadSession()?.model).toBe("");
  });
});

describe("what it refuses to restore", () => {
  it("carries no pen and no b2b — the fields do not exist in the shape", () => {
    saveSession(session);
    const back = loadSession() as Record<string, unknown>;
    // Asserted on the DATA, not on the caller's discipline: there is no field
    // to accidentally read, so a reload cannot inherit an armed scheduler.
    expect("pen" in back).toBe(false);
    expect("b2b" in back).toBe(false);
    expect("playing" in back).toBe(false);
  });

  it("voids a snapshot with no buffer rather than restoring half a session", () => {
    localStorage.setItem("apollo-algorave-v1", JSON.stringify({ v: 1, intent: "x" }));
    expect(loadSession()).toBeNull();
  });

  it("ignores a shape from another version", () => {
    localStorage.setItem("apollo-algorave-v1", JSON.stringify({ v: 99, buffer: "x" }));
    expect(loadSession()).toBeNull();
  });

  it("replaces a wrong type with the default instead of poisoning the scheduler", () => {
    // A string where phraseBars belongs would make `decide()` compare against
    // NaN and the mind would never fire again.
    localStorage.setItem(
      "apollo-algorave-v1",
      JSON.stringify({ v: 1, buffer: "x", phraseBars: "eight", bpm: -3 }),
    );
    const back = loadSession();
    expect(back?.phraseBars).toBe(8);
    expect(back?.bpm).toBe(124);
  });
});

describe("storage that is not there", () => {
  it("degrades instead of throwing when localStorage is unavailable", () => {
    // A private window, or storage disabled. The page must still work.
    vi.stubGlobal("localStorage", {
      getItem() { throw new Error("denied"); },
      setItem() { throw new Error("denied"); },
      removeItem() { throw new Error("denied"); },
    });
    expect(() => saveSession(session)).not.toThrow();
    expect(loadSession()).toBeNull();
  });

  it("survives content that is not JSON at all", () => {
    localStorage.setItem("apollo-algorave-v1", "{not json");
    expect(loadSession()).toBeNull();
  });
});
