"use client";
/**
 * §11 S4 + S5 — `/algorave`, the live-coding room inside Apollo.
 *
 * The canvas is modelled on `/live`, not on `/editor` (§11.2): three modes
 * switched IN PLACE and synced to the URL hash, code on screen as the show
 * rather than as a work surface. The switcher and hash sync are the SAME ones
 * `/live` uses — §11.3 seam 3.
 *
 * S5 adds the mind: an intent goes out, a proposal comes back as a diff, and
 * the human accepts or discards it. Every call goes through `lib/mind.ts`
 * (seam 1); this page never names the endpoint.
 *
 * NOT here, per the S5 scope: phrase-boundary scheduling and B2B. Those are
 * S6, and `autoApplyDecision` is exported ready for them — the tie rule is
 * computed and shown now, but nothing applies itself yet.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Shell } from "@/components/ember/Shell";
import { Crumb } from "@/components/ember/primitives";
import { ModeSwitcher, useStageMode } from "@/components/ember/ModeSwitcher";
import { boot, type StrudelModule } from "@/lib/strudel";
import { resolveRunId } from "@/lib/algorave-run";
import { MindError, askMind, autoApplyDecision } from "@/lib/mind";
import { diffCounts, hasChanges, lineDiff, type DiffLine } from "@/lib/line-diff";

type Phase = "idle" | "booting" | "playing" | "stopped" | "failed";

/** What the mind typically takes (p50 ~20 s). Used to pace the wait, not to time it out. */
const EXPECTED_WAIT_SEC = 20;

const OPENING_BUFFER = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("~ cp").bank("RolandTR909").room(0.3),
  s("hh*8").bank("RolandTR909").gain(0.4),
  note("c2 eb2 g2 bb2").s("supersaw").lpf(sine.range(400, 2000).slow(8)).gain(0.5)
).cpm(124/4)`;

interface Proposal {
  code: string;
  reason: string;
  /** The buffer the mind was shown. The tie rule compares against this. */
  seen: string;
  diff: DiffLine[];
}

export default function AlgoravePage() {
  const [mode, setMode] = useStageMode("cabin");
  const [buffer, setBuffer] = useState(OPENING_BUFFER);
  const [phase, setPhase] = useState<Phase>("idle");
  const [detail, setDetail] = useState("not started");
  const [insecure, setInsecure] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const engine = useRef<StrudelModule | null>(null);

  const [intent, setIntent] = useState("keep the groove moving — one clear change");
  const [thinking, setThinking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [mindError, setMindError] = useState<MindError | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);

  // The wait is ~20 s. Counting it makes the pause legible as something in
  // progress rather than something broken — the interval callback is the
  // allowed place to setState from an effect.
  useEffect(() => {
    if (!thinking) return;
    // Only the interval here: the counter is reset where the wait actually
    // begins (in `ask`), because setting state in an effect body is what
    // cascading renders are made of.
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [thinking]);

  const evaluate = useCallback(
    async (code: string) => {
      try {
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
            setDetail(`sound sources failed: ${failed.map((f) => f.tag).join(", ")}`);
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

  const ask = useCallback(async () => {
    // Captured HERE, before the await: this exact text is what the tie rule
    // compares against when the answer lands.
    const seen = buffer;
    setElapsed(0);
    setThinking(true);
    setMindError(null);
    setProposal(null);
    try {
      const out = await askMind({
        code: seen,
        intent,
        recentReasons: reasons.slice(-5),
      });
      setProposal({
        code: out.code,
        reason: out.reason,
        seen,
        diff: lineDiff(seen, out.code),
      });
      if (out.reason) setReasons((r) => [...r, out.reason].slice(-5));
    } catch (err) {
      setMindError(
        err instanceof MindError
          ? err
          : new MindError(0, "the mind call failed", String(err)),
      );
    } finally {
      setThinking(false);
    }
  }, [buffer, intent, reasons]);

  const applyProposal = useCallback(() => {
    if (!proposal) return;
    setBuffer(proposal.code);
    setProposal(null);
    void evaluate(proposal.code);
  }, [proposal, evaluate]);

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
  // The tie rule (#148). Recomputed on every render because the human may be
  // typing right now, while the proposal on screen was written against an
  // older buffer.
  const tie = proposal ? autoApplyDecision(proposal.seen, buffer) : null;

  const transport = (
    <div className="flex items-center gap-3 flex-wrap">
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
        className={"text-xs " + (phase === "failed" ? "text-ember" : "text-mute")}
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

  /** The wait, as a state rather than a spinner: what was asked, and how long. */
  const waiting = (
    <div
      data-testid="thinking"
      className="border border-line2 border-l-2 border-l-ember rounded-md bg-surf px-4 py-3"
    >
      <p className="font-mono uppercase tracking-mono text-[10.5px] text-ember mb-1">
        The mind is listening · {elapsed}s
      </p>
      <p className="text-mute text-sm italic font-display">“{intent}”</p>
      <div className="mt-3 h-px bg-line2 relative overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-ember transition-[width] duration-1000 ease-linear"
          style={{
            width: `${Math.min(100, (elapsed / EXPECTED_WAIT_SEC) * 100)}%`,
          }}
        />
      </div>
      <p className="text-faint text-xs mt-2">
        Usually about {EXPECTED_WAIT_SEC}s. It is writing against the buffer as
        it was when you asked — keep playing.
      </p>
    </div>
  );

  const mindPanel = (
    <div className="flex flex-col gap-3">
      <div className="flex gap-3 flex-wrap items-center">
        <input
          data-testid="intent"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="darker · more space · build"
          className="flex-1 min-w-[260px] bg-surf border border-line rounded-md px-3 py-2 font-sans text-sm text-ember-text outline-none focus:border-line2"
        />
        <button
          type="button"
          onClick={() => void ask()}
          disabled={thinking || intent.trim().length === 0}
          data-testid="ask-mind"
          className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded border border-line2 text-ember-text disabled:opacity-40 cursor-pointer"
        >
          Ask the mind
        </button>
      </div>

      {thinking && waiting}

      {mindError && (
        <div
          data-testid="mind-error"
          className="border border-line2 border-l-2 border-l-ember rounded-md bg-surf px-4 py-3"
        >
          <p className="font-mono uppercase tracking-mono text-[10.5px] text-ember mb-1">
            {mindError.worthRetrying ? "The mind stumbled" : "Something needs fixing"}
          </p>
          <p className="text-mute text-sm">{mindError.message}</p>
          {mindError.detail && (
            <p className="text-faint text-xs font-mono mt-1 break-words">
              {mindError.detail}
            </p>
          )}
        </div>
      )}

      {proposal && (
        <div
          data-testid="proposal"
          data-auto-appliable={String(tie?.autoApply ?? false)}
          className="border border-line rounded-md bg-surf"
        >
          <div className="flex items-baseline justify-between gap-3 px-4 py-3 border-b border-line flex-wrap">
            <p className="text-mute text-sm italic font-display">
              {proposal.reason || "no reason given"}
            </p>
            <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
              +{diffCounts(proposal.diff).added} −
              {diffCounts(proposal.diff).removed}
            </span>
          </div>

          {tie && !tie.autoApply && (
            <p
              data-testid="tie-warning"
              className="px-4 py-2 text-xs text-warn border-b border-line"
            >
              You edited while it was thinking, so your text stands. This
              proposal was written against the older buffer — read it before
              applying.
            </p>
          )}

          {hasChanges(proposal.diff) ? (
            <pre className="px-4 py-3 font-mono text-xs overflow-x-auto">
              {proposal.diff.map((l, i) => (
                <div
                  key={i}
                  className={
                    l.op === "add"
                      ? "text-ok"
                      : l.op === "del"
                        ? "text-ember"
                        : "text-faint"
                  }
                >
                  {l.op === "add" ? "+ " : l.op === "del" ? "- " : "  "}
                  {l.text}
                </div>
              ))}
            </pre>
          ) : (
            <p className="px-4 py-3 text-faint text-sm">
              The mind returned the same buffer — nothing to apply.
            </p>
          )}

          <div className="flex gap-3 px-4 py-3 border-t border-line">
            <button
              type="button"
              onClick={applyProposal}
              disabled={!hasChanges(proposal.diff)}
              data-testid="apply"
              className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded bg-cream text-ink disabled:opacity-40 cursor-pointer"
            >
              Apply
            </button>
            <button
              type="button"
              onClick={() => setProposal(null)}
              data-testid="discard"
              className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded border border-line2 cursor-pointer"
            >
              Discard
            </button>
          </div>
        </div>
      )}
    </div>
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
              className="w-full min-h-[280px] bg-surf border border-line rounded-md p-4 font-mono text-sm text-ember-text outline-none focus:border-line2 resize-y"
            />
            <div className="flex items-center justify-between gap-4 flex-wrap">
              {transport}
              <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
                ⌘/Ctrl + Enter to evaluate
              </span>
            </div>
            {mindPanel}
          </div>
        )}

        {mode === "audience" && (
          <div className="flex flex-col gap-6">
            <div className="bg-surf border border-line rounded-md p-8 text-lg leading-relaxed">
              {code}
            </div>
            {thinking && waiting}
            {transport}
          </div>
        )}

        {mode === "immersive" && (
          <div className="flex-1 flex flex-col items-center justify-center gap-6 text-xl leading-relaxed">
            {code}
            {thinking && (
              <p className="font-display italic text-mute text-base">
                the mind is listening · {elapsed}s
              </p>
            )}
          </div>
        )}
      </div>
    </Shell>
  );
}
