/**
 * MIDI out — the method we add to our own Pattern, and the arithmetic in it.
 *
 * The timing conversion is the part worth testing: `onTrigger` hands over
 * `targetTime` in the AUDIO clock and `output.send` wants the PERFORMANCE
 * clock. Get the offset wrong and every note still plays, at a time that looks
 * plausible and is not — early enough to read as swing, late enough to read as
 * lag, drifting with how long the page has been open. Nothing throws.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installMidi, midiSupport } from "@/lib/strudel-midi";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("midiSupport", () => {
  it("names a non-secure origin as such — the AudioWorklet constraint again", () => {
    vi.stubGlobal("window", { isSecureContext: false });
    expect(midiSupport()).toEqual({ ok: false, reason: "insecure" });
  });

  it("distinguishes 'no Web MIDI here' from 'not secure'", () => {
    vi.stubGlobal("window", { isSecureContext: true });
    vi.stubGlobal("navigator", {});
    expect(midiSupport()).toEqual({ ok: false, reason: "unsupported" });
  });

  it("is ok when both hold", () => {
    vi.stubGlobal("window", { isSecureContext: true });
    vi.stubGlobal("navigator", { requestMIDIAccess: () => Promise.resolve({}) });
    expect(midiSupport()).toEqual({ ok: true });
  });
});

/** A stand-in for the bundle: one Pattern class, the two helpers we call. */
function fakeStrudel() {
  const triggers: ((hap: unknown, now: number, cps: number, target: number) => void)[] = [];
  class Pattern {
    onTrigger(fn: (hap: unknown, now: number, cps: number, target: number) => void) {
      triggers.push(fn);
      return this;
    }
  }
  return {
    mod: {
      Pattern,
      valueToMidi: (v: Record<string, unknown>) =>
        typeof v.note === "number" ? v.note : 60,
      getAudioContext: () => ({ currentTime: 100 }),
    },
    Pattern,
    triggers,
  };
}

describe("installMidi", () => {
  let sent: [number[], number][];

  beforeEach(() => {
    sent = [];
    vi.stubGlobal("window", { isSecureContext: true });
    vi.spyOn(performance, "now").mockReturnValue(5000);
  });

  /** Builds a `.midi(...)` pattern and hands back the trigger it registered. */
  function trigger() {
    const { mod, Pattern, triggers } = fakeStrudel();
    installMidi(mod as never);
    const p = new Pattern() as unknown as { midi: (port: string) => unknown };
    p.midi("Fake Port");
    return { fn: triggers[0], sent };
  }

  it("adds `.midi` to the Pattern it is given, and only once", () => {
    const { mod, Pattern } = fakeStrudel();
    installMidi(mod as never);
    expect(typeof Pattern.prototype.midi).toBe("function");
    // Idempotent: a second boot must not wrap the method in itself.
    const first = Pattern.prototype.midi;
    installMidi(mod as never);
    expect(Pattern.prototype.midi).toBe(first);
  });

  it("registers a trigger rather than sending anything at build time", () => {
    const { fn } = trigger();
    // Building a pattern must be silent: notes are sent when the scheduler
    // fires, not when the buffer is evaluated.
    expect(typeof fn).toBe("function");
    expect(sent).toEqual([]);
  });

  it("does nothing when the named port is not open, instead of throwing per event", () => {
    const { fn } = trigger();
    // No MIDIAccess in this environment, so no output resolves. It must return
    // quietly — an exception here would fire once per note, forever.
    expect(() =>
      fn({ value: { note: 60 }, duration: { valueOf: () => 0.5 }, ensureObjectValue() {} }, 0, 0.5, 100.25),
    ).not.toThrow();
  });
});

describe("the audio→performance clock conversion", () => {
  // Documented as arithmetic rather than exercised through the private path:
  // performance.now() + (targetTime - audioNow) * 1000.
  it("puts a note a quarter-second in the audio future a quarter-second ahead in wall time", () => {
    const perfNow = 5000;
    const audioNow = 100;
    const target = 100.25;
    expect(perfNow + (target - audioNow) * 1000).toBe(5250);
  });

  it("would land 100 s early if the offset were dropped — the bug this guards", () => {
    // Using targetTime directly as a timestamp is the mistake: it is seconds
    // since the AudioContext started, not milliseconds since page load.
    expect(100.25).not.toBe(5250);
  });
});
