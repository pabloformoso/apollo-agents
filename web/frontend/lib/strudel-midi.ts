"use client";
/**
 * MIDI out for the algorave lane — `.midi("port")` on the pattern.
 *
 * **Why this is written here rather than installed.** `@strudel/midi` provides
 * this, but it depends on `@strudel/core` and would arrive with its own copy of
 * it — a SECOND `Pattern` class, which is the exact failure S3 spent a day
 * proving is silent (see lib/strudel.ts). A method registered on a Pattern that
 * is not the one the scheduler runs simply never fires. So the method is added
 * to OUR single bundle's prototype, using hooks that bundle already exports:
 * `onTrigger`, `valueToMidi`, `getAudioContext`.
 *
 * It is a deliberate subset of `@strudel/midi`: note on/off, channel, velocity
 * from gain. No CC maps, no NRPN, no sysex, no program change. Those are worth
 * adding when something asks for them; guessing at them now would be code
 * nobody has ever run.
 *
 * **Where the sound comes out matters.** WebMIDI runs in the BROWSER, so the
 * notes reach the MIDI ports of whatever machine has the tab open — the
 * performer's laptop, not the server. That is the whole reason this is a better
 * fit here than Strudel's OSC/SuperDirt path, where SuperCollider would make
 * the sound on the server, in a room nobody is sitting in.
 *
 * **Secure context required**, like AudioWorklet: `navigator.requestMIDIAccess`
 * does not exist on a plain-HTTP origin that is not localhost. Same constraint,
 * same fix, and `midiSupport()` says which case you are in rather than failing
 * as a mystery.
 */
import type { StrudelModule } from "./strudel";

export type MidiSupport =
  | { ok: true }
  | { ok: false; reason: "insecure" | "unsupported" };

/** Whether this browser can do MIDI at all, and if not, which way it failed. */
export function midiSupport(): MidiSupport {
  if (typeof window === "undefined") return { ok: false, reason: "unsupported" };
  if (!window.isSecureContext) return { ok: false, reason: "insecure" };
  if (typeof navigator.requestMIDIAccess !== "function") {
    return { ok: false, reason: "unsupported" };
  }
  return { ok: true };
}

export interface MidiPort {
  id: string;
  name: string;
  manufacturer: string;
}

let access: MIDIAccess | null = null;

/**
 * Asks for MIDI access and lists the outputs. Throws with a legible message
 * rather than a DOMException — "the browser refused" and "there are no ports"
 * are different problems and the UI has to say which.
 */
export async function enableMidi(): Promise<MidiPort[]> {
  const support = midiSupport();
  if (!support.ok) {
    throw new Error(
      support.reason === "insecure"
        ? "MIDI needs a secure context — reach this page over HTTPS or through localhost"
        : "this browser has no Web MIDI",
    );
  }
  if (!access) {
    try {
      access = await navigator.requestMIDIAccess({ sysex: false });
    } catch (err) {
      throw new Error(`the browser refused MIDI access: ${String(err)}`);
    }
  }
  return [...access.outputs.values()].map((o) => ({
    id: o.id,
    name: o.name ?? o.id,
    manufacturer: o.manufacturer ?? "",
  }));
}

function outputNamed(name: string): MIDIOutput | null {
  if (!access) return null;
  for (const out of access.outputs.values()) {
    if (out.name === name || out.id === name) return out;
  }
  return null;
}

/**
 * The one piece of arithmetic worth reading twice.
 *
 * `onTrigger` hands us `targetTime` in the AUDIO clock, and `output.send`
 * expects a timestamp in the PERFORMANCE clock. They are different origins, so
 * the offset between them has to be applied or every note lands at a time that
 * looks plausible and is wrong — early enough to sound like swing, late enough
 * to sound like lag, depending on how long the page has been open.
 */
function performanceTimeFor(audioTime: number, audioNow: number): number {
  return performance.now() + (audioTime - audioNow) * 1000;
}

export interface MidiOptions {
  /** 1-16, as everyone but the wire format counts them. */
  channel?: number;
  velocity?: number;
  /** Note-off is pulled this far forward so consecutive notes do not glue. */
  noteOffsetMs?: number;
}

/**
 * Adds `.midi(port, options?)` to the running bundle's Pattern. Idempotent.
 *
 * Mirrors `@strudel/midi`'s shape — a pattern method returning `onTrigger` —
 * so a buffer written for the real package behaves the same here.
 */
export function installMidi(strudel: StrudelModule): void {
  const mod = strudel as unknown as {
    Pattern: { prototype: Record<string, unknown> };
    valueToMidi: (value: Record<string, unknown>, fallback?: number) => number;
    getAudioContext: () => { currentTime: number };
  };
  const proto = mod.Pattern?.prototype;
  if (!proto || typeof proto.onTrigger !== "function") return;
  // Idempotent per PROTOTYPE, not per module. A module-level flag would install
  // on the first Pattern it ever saw and silently skip any other — which in
  // production is one bundle and fine, and in a test is a method that is not
  // there. Guarding on the prototype is both correct and honest.
  if (typeof proto.midi === "function") return;

  proto.midi = function midi(this: unknown, port: string, options: MidiOptions = {}) {
    const { channel = 1, velocity = 0.9, noteOffsetMs = 10 } = options;
    const self = this as {
      onTrigger: (fn: (hap: MidiHap, now: number, cps: number, target: number) => void) => unknown;
    };

    return self.onTrigger((hap, _now, cps, targetTime) => {
      const out = outputNamed(port);
      if (!out) return; // Reported by the UI, not once per event.

      hap.ensureObjectValue?.();
      const value = (hap.value ?? {}) as Record<string, unknown>;
      if (value.note === undefined && value.n === undefined) return;

      const noteNum = Math.round(mod.valueToMidi(value, 36));
      if (!Number.isFinite(noteNum) || noteNum < 0 || noteNum > 127) return;

      const gain = typeof value.gain === "number" ? value.gain : 1;
      const vel = typeof value.velocity === "number" ? value.velocity : velocity;
      const v = Math.max(1, Math.min(127, Math.round(gain * vel * 127)));

      const chan =
        (typeof value.midichan === "number" ? value.midichan : channel) - 1;
      const status = Math.max(0, Math.min(15, chan));

      const audioNow = mod.getAudioContext().currentTime;
      const at = performanceTimeFor(targetTime, audioNow);
      const durMs = Math.max(
        1,
        (Number(hap.duration?.valueOf?.() ?? 0.25) / cps) * 1000 - noteOffsetMs,
      );

      out.send([0x90 | status, noteNum, v], at);
      out.send([0x80 | status, noteNum, 0], at + durMs);
    });
  };
}

interface MidiHap {
  value?: unknown;
  duration?: { valueOf: () => number };
  ensureObjectValue?: () => void;
}
