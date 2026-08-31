"use client";
/**
 * §11 S4 — `/algorave`, the live-coding surface inside Apollo.
 *
 * The canvas is modelled on `/live`, not on `/editor`: three modes switched
 * IN PLACE and synced to the URL hash, with the code on screen as the show
 * rather than as a work surface (§11.2). The switcher and the hash sync are
 * the SAME ones `/live` uses — `components/ember/ModeSwitcher` — because a
 * second copy is exactly what §11.3 seam 3 exists to prevent.
 *
 * This route absorbs the S3 spike (`/algorave-spike`, now deleted). What it
 * inherits from it is not the page but `lib/strudel.ts`, and the three things
 * that spike cost us to learn: Strudel must not be bundled, `initStrudel` does
 * not await the worklets, and worklet-backed sounds need a secure context.
 *
 * NOT here, by §11.2 and the S4 scope: the mind, the pen, B2B, the palette
 * browser, the read-only OBS view. This slice is the room, not the instrument.
 */
import { useCallback, useRef, useState } from "react";
import { Shell } from "@/components/ember/Shell";
import { Crumb } from "@/components/ember/primitives";
import { ModeSwitcher, useStageMode } from "@/components/ember/ModeSwitcher";
import { boot, type StrudelModule } from "@/lib/strudel";
import { resolveRunId } from "@/lib/algorave-run";

type Phase = "idle" | "booting" | "playing" | "stopped" | "failed";

/**
 * The opening buffer. Deep house at 124 BPM, and it obeys the bank rule the
 * palette is built on: drum sounds carry `.bank(...)`, sampled instruments
 * never may — a `.bank()` on those is silence.
 */
const OPENING_BUFFER = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("~ cp").bank("RolandTR909").room(0.3),
  s("hh*8").bank("RolandTR909").gain(0.4),
  note("c2 eb2 g2 bb2").s("supersaw").lpf(sine.range(400, 2000).slow(8)).gain(0.5)
).cpm(124/4)`;

export default function AlgoravePage() {
  // Booth by default, unlike `/live`'s Audience: you arrive here to write.
  const [mode, setMode] = useStageMode("cabin");
  const [buffer, setBuffer] = useState(OPENING_BUFFER);
  const [phase, setPhase] = useState<Phase>("idle");
  const [detail, setDetail] = useState("not started");
  const [insecure, setInsecure] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const engine = useRef<StrudelModule | null>(null);

  /**
   * Boots on first use and evaluates. Must run from a user gesture — an
   * AudioContext created without one is suspended and stays silent.
   */
  const evaluate = useCallback(
    async (code: string) => {
      try {
        // Mint the run id here rather than in an effect: this is a user
        // gesture, so it touches the URL at a moment React is happy with, it
        // cannot mismatch during hydration, and it adds no second consumer of
        // `useSearchParams` (the hook whose prerender bailout was S1).
        const id = runId ?? resolveRunId();
        if (!runId) setRunId(id);

        if (!engine.current) {
          setPhase("booting");
          setDetail("loading the engine and registering sounds…");
          const { strudel, secureContext, failed, workletError } = await boot();
          engine.current = strudel;
          setInsecure(!secureContext);
          if (workletError) {
            setDetail(`AudioWorklet did not register: ${workletError}`);
          } else if (failed.length) {
            setDetail(
              `sound sources failed: ${failed.map((f) => f.tag).join(", ")}`,
            );
          }
        }
        await engine.current.evaluate(code);
        setPhase("playing");
        setDetail(`playing · run ${id}`);
      } catch (err) {
        setPhase("failed");
        setDetail(String(err));
      }
    },
    [runId],
  );

  const stop = useCallback(() => {
    engine.current?.hush();
    setPhase("stopped");
    setDetail("stopped");
  }, []);

  // Ctrl/Cmd+Enter evaluates — the live-coding convention, and the reason the
  // buffer is a plain textarea for now: no editor library gets to own that key
  // before S5 decides what the pen needs.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        void evaluate(buffer);
      }
    },
    [buffer, evaluate],
  );

  const playing = phase === "playing";

  const transport = (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => void evaluate(buffer)}
        disabled={phase === "booting"}
        data-testid="evaluate"
        className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded bg-ember text-ink disabled:opacity-40 cursor-pointer"
      >
        {playing ? "Re-evaluate" : "Play"}
      </button>
      <button
        type="button"
        onClick={stop}
        disabled={!playing}
        data-testid="stop"
        className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded border border-line2 disabled:opacity-40 cursor-pointer"
      >
        Stop
      </button>
      <span
        data-testid="status"
        data-phase={phase}
        className={
          "text-xs " + (phase === "failed" ? "text-ember" : "text-mute")
        }
      >
        {detail}
      </span>
    </div>
  );

  const code = (
    <pre
      data-testid="code-display"
      className="font-mono text-ember-text whitespace-pre-wrap break-words"
    >
      {buffer}
    </pre>
  );

  return (
    <Shell sessionLabel="algorave" hideNav={mode === "immersive"}>
      <div
        className={
          "flex flex-col gap-5 " +
          (mode === "immersive" ? "p-6 min-h-screen" : "px-9 py-7")
        }
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-baseline gap-4">
            <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
              Live coding
            </span>
            <Crumb>run {runId ?? "—"}</Crumb>
          </div>
          <ModeSwitcher mode={mode} onChange={setMode} />
        </div>

        {insecure && (
          <div
            data-testid="insecure-warning"
            className="border border-line2 border-l-2 border-l-warn rounded-md bg-surf px-4 py-3 max-w-4xl"
          >
            <p className="font-mono uppercase tracking-mono text-[10.5px] text-warn mb-1">
              Non-secure origin
            </p>
            <p className="text-mute text-sm">
              The browser exposes no <code>AudioWorklet</code> here, so samples
              play but every worklet-backed sound — supersaw, the effects chain
              — does not. Reach this page over HTTPS, or through{" "}
              <code>localhost</code>.
            </p>
          </div>
        )}

        {mode === "cabin" && (
          <div className="flex flex-col gap-4">
            <textarea
              data-testid="buffer"
              value={buffer}
              onChange={(e) => setBuffer(e.target.value)}
              onKeyDown={onKeyDown}
              spellCheck={false}
              className="w-full min-h-[340px] bg-surf border border-line rounded-md p-4 font-mono text-sm text-ember-text outline-none focus:border-line2 resize-y"
            />
            <div className="flex items-center justify-between gap-4 flex-wrap">
              {transport}
              <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
                ⌘/Ctrl + Enter to evaluate
              </span>
            </div>
          </div>
        )}

        {mode === "audience" && (
          <div className="flex flex-col gap-6">
            <div className="bg-surf border border-line rounded-md p-8 text-lg leading-relaxed">
              {code}
            </div>
            {transport}
          </div>
        )}

        {mode === "immersive" && (
          <div className="flex-1 flex items-center justify-center text-xl leading-relaxed">
            {code}
          </div>
        )}
      </div>
    </Shell>
  );
}
