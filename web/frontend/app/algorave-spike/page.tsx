"use client";
/**
 * §11 S3 — the Strudel bundle spike. THROWAWAY.
 *
 * Answers one question before any design work: can a Next route run Strudel,
 * audibly, in a production build?
 *
 * The first attempt looked like a pass — a Turbopack alias gave one `Pattern`
 * class and the assertion went green — but the page was silent. Two failures
 * hid behind it, both silent by construction, both listed in lib/strudel.ts:
 * the AudioWorklet asset 404s when the bundle is bundled, and no sound is
 * registered unless sample sources are loaded first. Hence the checks below
 * are FUNCTIONAL: the only honest proof is a console with nothing in it.
 *
 * S4 folds this into `/algorave`. Keep the checks when it does.
 */
import { useCallback, useState } from "react";
import { boot, STRUDEL_URL, type StrudelModule } from "@/lib/strudel";

type Phase = "idle" | "booting" | "playing" | "stopped" | "failed";

const PATTERN = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("~ cp").bank("RolandTR909").room(0.3),
  s("hh*8").bank("RolandTR909").gain(0.4),
  note("c2 eb2 g2 bb2").s("supersaw").lpf(sine.range(400, 2000).slow(8)).gain(0.5)
).cpm(124/4)`;

export default function StrudelSpikePage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [detail, setDetail] = useState("not started");
  const [registered, setRegistered] = useState<string[]>([]);
  const [engine, setEngine] = useState<StrudelModule | null>(null);

  const play = useCallback(async () => {
    try {
      setPhase("booting");
      setDetail("loading engine from " + STRUDEL_URL + " and registering sounds…");
      const { strudel, registered: ok, failed } = await boot();
      setEngine(strudel);
      setRegistered(ok);
      if (failed.length) {
        setDetail(`sources failed: ${failed.map((f) => `${f.tag} (${f.error})`).join(", ")}`);
      }
      await strudel.evaluate(PATTERN);
      setPhase("playing");
      setDetail("playing — a 909 kick, clap and hats with a supersaw bass at 124 BPM");
    } catch (err) {
      setPhase("failed");
      setDetail(String(err));
    }
  }, []);

  const stop = useCallback(async () => {
    engine?.hush();
    setPhase("stopped");
    setDetail("stopped");
  }, [engine]);

  return (
    <main className="min-h-screen bg-ink text-ember-text p-8 font-sans">
      <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
        §11 S3 · spike · throwaway
      </p>
      <h1 className="font-display italic text-4xl tracking-display-tight mt-1 mb-6">
        Strudel in Next
      </h1>

      <section className="border border-line rounded-md bg-surf p-4 mb-4 max-w-3xl">
        <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint mb-3">
          Engine
        </p>
        <div className="flex gap-3 mb-3">
          <button
            type="button"
            onClick={play}
            disabled={phase === "booting" || phase === "playing"}
            data-testid="play"
            className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded bg-ember text-ink disabled:opacity-40"
          >
            Play
          </button>
          <button
            type="button"
            onClick={stop}
            disabled={phase !== "playing"}
            data-testid="stop"
            className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded border border-line2 disabled:opacity-40"
          >
            Stop
          </button>
        </div>
        <p
          data-testid="status"
          data-phase={phase}
          className={phase === "failed" ? "text-ember text-sm" : "text-mute text-sm"}
        >
          {detail}
        </p>
        <p data-testid="registered" className="text-faint text-xs font-mono mt-2">
          sources registered: {registered.length ? registered.join(", ") : "—"}
        </p>
      </section>

      <section className="border border-line rounded-md bg-surf p-4 max-w-3xl">
        <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint mb-2">
          Pattern
        </p>
        <pre className="text-xs font-mono text-faint overflow-x-auto">{PATTERN}</pre>
        <p className="text-faint text-xs mt-3">
          The real check is the browser console: a clean run logs no{" "}
          <code>getTrigger</code> errors and no AudioWorklet failure.
        </p>
      </section>
    </main>
  );
}
