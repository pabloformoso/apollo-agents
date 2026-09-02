"use client";
/**
 * §11 S4–S6 — `/algorave`, the live-coding room inside Apollo.
 *
 * Canvas modelled on `/live` (§11.2): three modes switched IN PLACE, synced to
 * the URL hash, sharing `/live`'s switcher (§11.3 seam 3).
 *
 * S6 adds the turn-taking: the pen, the phrase scheduler and B2B. **None of
 * that logic is written here.** It is imported from the pen module the spike
 * already owns (§11.3 seam 2) — `decide`, `b2bDecide`, the `WHY` enums, the
 * tie rule — so there is exactly one copy in the repo and the spike's tests
 * still guard it. This page only wires a clock to it and renders the answer.
 *
 * Layout follows the original playground: the editor on the left, the mind's
 * proposal on the right, controls in a rail. Reading a diff means reading it
 * against the code it changes, and stacked panes make that a scroll.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Shell } from "@/components/ember/Shell";
import { Crumb } from "@/components/ember/primitives";
import { ModeSwitcher, useStageMode } from "@/components/ember/ModeSwitcher";
import { TurnStrip, type PenHolder } from "@/components/ember/TurnStrip";
import { PaletteBrowser } from "@/components/ember/PaletteBrowser";
import { CodeEditor } from "@/components/ember/CodeEditor";
import { insertIntoBuffer, readPalette, type Palette } from "@/lib/palette";
import { enableMidi, type MidiPort } from "@/lib/strudel-midi";
import { readVerdict, validateBuffer, type Verdict } from "@/lib/validate";
import { loadSession, saveSession } from "@/lib/algorave-persist";
import { boot, type StrudelModule } from "@/lib/strudel";
import {
  fetchRun,
  publishRun,
  readRunId,
  resolveRunId,
  type RunSnapshot,
} from "@/lib/algorave-run";
import { useViewerFlag, viewerUrlFor } from "@/lib/viewer";
import { MindError, askMind, autoApplyDecision, diffLines, fetchMindModels, pushReason, summarizeHumanEdit } from "@/lib/mind";
import type { MindModels } from "@/lib/mind";
import {
  b2bDecide,
  barsElapsed,
  decide,
  nextBoundaryBar,
  barsUntilFlip,
  togglePen,
} from "@algorave/pen";

type Phase = "idle" | "booting" | "playing" | "stopped" | "failed";
type DiffRow = { type: "same" | "add" | "del"; text: string };

const OPENING_BUFFER = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("~ cp").bank("RolandTR909").room(0.3),
  s("hh*8").bank("RolandTR909").gain(0.4),
  note("c2 eb2 g2 bb2").s("supersaw").lpf(sine.range(400, 2000).slow(8)).gain(0.5)
).cpm(124/4)`;

const DEFAULT_BPM = 124;

/** What the key selector offers. Drives the validator's out-of-key check. */
const KEYS = [
  "A:minor", "C:major", "D:minor", "E:minor", "F:major", "G:major",
  "F#:minor", "Bb:major", "C:minor", "D:dorian", "A:phrygian",
];
/** Cycles per second at 4/4 — one cycle is one bar, which is what the pen counts. */
const cpsFor = (bpm: number) => bpm / 60 / 4;

interface Proposal {
  code: string;
  reason: string;
  /** The buffer the mind was shown; the tie rule compares against this. */
  seen: string;
  diff: DiffRow[];
  /** True when the scheduler asked, false when the human clicked. */
  scheduled: boolean;
}

/**
 * What each model COSTS, measured (2026-09-02, five intents through the real
 * validator). Shown beside the option because without it the selector is a
 * trap: pick the 27B mid-set and the mind goes quiet for two minutes with
 * nothing to explain it — a boundary missed while a call is in flight is
 * SKIPPED, silently and correctly.
 *
 * For scale: an 8-bar phrase at cpm(124/4) is about 15 s.
 *
 * A model absent from this map simply gets no hint. Inventing one would be
 * worse than saying nothing.
 */
const MODEL_NOTES: Record<string, string> = {
  "gpt-4o": "~1 s · inside the bar",
  "gpt-4o-mini": "~2 s · inside the bar",
  "google/gemma-4-e4b": "~8 s · half a phrase · stays on this box",
  "qwen3.8-27b": "~120 s · eight phrases · not usable live",
  "qwen3.6-27b": "a reasoner — expect minutes, not seconds",
};

export function AlgoraveClient() {
  // Read ONCE, during the first (client-only) render. No effect, nothing to
  // reconcile — see the note in page.tsx about why this route is `ssr: false`.
  const [saved] = useState(loadSession);

  const [mode, setMode] = useStageMode("cabin");
  const [buffer, setBuffer] = useState(saved?.buffer ?? OPENING_BUFFER);
  const [phase, setPhase] = useState<Phase>("idle");
  const [detail, setDetail] = useState("not started");
  const [insecure, setInsecure] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const engine = useRef<StrudelModule | null>(null);

  const [intent, setIntent] = useState(
    saved?.intent || "keep the groove moving — one clear change",
  );
  // The mind publishes what it serves; null means it could not be asked, and
  // the selector simply does not render. Being unable to CHOOSE a model must
  // never mean being unable to play.
  const [mindModels, setMindModels] = useState<MindModels | null>(null);
  const [model, setModel] = useState(saved?.model ?? "");
  /** Which model actually answered last — the only way to hear a switch. */
  const [answeredBy, setAnsweredBy] = useState<string | null>(null);

  const [thinking, setThinking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [mindError, setMindError] = useState<MindError | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);

  // --- turn taking (S6) -----------------------------------------------------
  const [pen, setPen] = useState<PenHolder>("human");
  const [b2b, setB2b] = useState(false);
  const [phraseBars, setPhraseBars] = useState(saved?.phraseBars ?? 8);
  const [b2bBars, setB2bBars] = useState(saved?.b2bBars ?? 16);
  const [bpm, setBpm] = useState(saved?.bpm ?? DEFAULT_BPM);
  const [barsNow, setBarsNow] = useState(0);
  const [why, setWhy] = useState<string | null>(null);
  const [log, setLog] = useState<{ bar: number; text: string }[]>([]);

  // --- viewer mode (S8) -----------------------------------------------------
  // Three-state: nothing may attach until the URL has been read. See
  // lib/viewer.ts for why treating "not yet known" as "operator" is the bug.
  const { isViewer, resolved: viewerResolved } = useViewerFlag();
  const [mirror, setMirror] = useState<RunSnapshot | null>(null);

  // The viewer reads the run the operator publishes under. It must NOT mint an
  // id: it would then wait forever on a run nobody writes to.
  useEffect(() => {
    if (!isViewer) return;
    const id = readRunId();
    if (!id) return;
    // Deliberately NOT put in state: the viewer only needs it to poll, and a
    // synchronous setState here is a cascading render for nothing.
    let cancelled = false;
    const poll = async () => {
      try {
        const snap = await fetchRun(id);
        if (!cancelled) setMirror(snap);
      } catch {
        // A mirror that cannot reach the server shows the last frame it had
        // rather than an error: OBS is on screen.
      }
    };
    void poll();
    const t = setInterval(poll, 500);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [isViewer]);

  // The operator publishes. Never in viewer mode — a mirror writing back would
  // overwrite the performance with its own stale frame.
  useEffect(() => {
    if (!viewerResolved || isViewer || !runId) return;
    void publishRun(runId, {
      buffer,
      pen,
      barsNow,
      phraseBars,
      reason: proposal?.reason ?? "",
    });
  }, [viewerResolved, isViewer, runId, buffer, pen, barsNow, phraseBars, proposal]);

  // --- genre, key and live validation --------------------------------------
  // The genre and key are not decoration: they are what the validator checks
  // AGAINST, and what the mind is fenced by. Without them the note check has
  // nothing to compare to and the mind falls back to server defaults.
  const [genre, setGenre] = useState(saved?.genre ?? "deep");
  const [key, setKey] = useState(saved?.key ?? "A:minor");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    // Debounced: the validator answers in ~100 ms, so the wait is for the
    // typist, not the process. Checking every keystroke would flicker.
    let cancelled = false;
    const t = setTimeout(() => {
      setChecking(true);
      validateBuffer(buffer, { genre, key })
        .then((v) => {
          if (!cancelled) setVerdict(v);
        })
        .catch(() => {
          // A validator we cannot reach must not look like invalid code.
          if (!cancelled) setVerdict(null);
        })
        .finally(() => {
          if (!cancelled) setChecking(false);
        });
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [buffer, genre, key]);

  const reading = readVerdict(verdict);

  // Asked once. A saved model the mind no longer offers is dropped here rather
  // than sent and refused — the list is the server's, and a preference that
  // outlived it is stale data, not an error to show a performer mid-set.
  useEffect(() => {
    let cancelled = false;
    void fetchMindModels().then((got) => {
      if (cancelled || !got) return;
      setMindModels(got);
      setModel((m) => (m && !got.models.includes(m) ? "" : m));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Saved on a debounce. The PEN and the B2B mode are deliberately absent, and
  // so is the transport: a reloaded page must never fire an LLM call by
  // itself, never wake up alternating, and never start making sound because a
  // browser refreshed (§9.1, §9.2 — the playground's rule, kept).
  useEffect(() => {
    const t = setTimeout(
      () => saveSession({ buffer, intent, phraseBars, b2bBars, bpm, genre, key, model }),
      500,
    );
    return () => clearTimeout(t);
  }, [buffer, intent, phraseBars, b2bBars, bpm, genre, key, model]);

  // --- MIDI out ------------------------------------------------------------
  // WebMIDI runs in THIS browser, so the notes reach the ports of the machine
  // the tab is open on — the performer's, not the server's. That is what makes
  // it a better fit than Strudel's OSC/SuperDirt path, where the sound would
  // be made on the server in a room nobody is in.
  const [midiPorts, setMidiPorts] = useState<MidiPort[] | null>(null);
  const [midiPort, setMidiPort] = useState<string>("");
  const [midiError, setMidiError] = useState<string | null>(null);

  const askForMidi = useCallback(async () => {
    setMidiError(null);
    try {
      const ports = await enableMidi();
      setMidiPorts(ports);
      if (ports.length > 0) setMidiPort((cur) => cur || ports[0].name);
    } catch (err) {
      setMidiPorts([]);
      setMidiError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  // --- the palette (S7) -----------------------------------------------------
  const [palette, setPalette] = useState<Palette | null>(null);
  // Read by `evaluate`, which runs from a gesture and must see the palette as
  // it stands rather than as it was when the callback was created.
  const paletteRef = useRef<Palette | null>(null);
  const [paletteError, setPaletteError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/algorave/palette")
      .then(async (r) => {
        const body = await r.json();
        if (cancelled) return;
        if (!r.ok) setPaletteError(body?.error ?? `HTTP ${r.status}`);
        else {
          const parsed = readPalette(body);
          paletteRef.current = parsed;
          setPalette(parsed);
        }
      })
      .catch((e) => {
        if (!cancelled) setPaletteError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refs so the tick reads the CURRENT values, not the ones captured when the
  // interval was created. A stale `pen` here would fire the mind on a boundary
  // the human had already taken back.
  const penRef = useRef<PenHolder>("human");
  const inFlight = useRef(false);
  const lastBoundary = useRef<number | null>(null);
  const lastFlip = useRef<number | null>(null);
  const startedAt = useRef<number | null>(null);
  // The bar the tick last computed. `ask` runs from an interval, so reading
  // `barsNow` out of its closure logged the bar the closure was BORN on, not
  // the one the boundary fired at — a log you cannot trust is worse than none.
  /**
   * The last text that was EVALUATED, which is what a human edit is diffed
   * against (§9.1). It moves on EVERY evaluate, the mind's own included —
   * without that, handing the pen back would report the mind's last mutation
   * as if a human had made it.
   */
  const lastEvaluated = useRef<string | null>(null);
  const barsRef = useRef(0);
  const bufferRef = useRef(buffer);
  // The model is read through a ref for the SAME reason `barsRef` is: `ask`
  // runs from an interval, so a value captured in its closure is the one the
  // closure was born with. Listing `model` in the deps instead would rebuild
  // `ask` and re-arm the scheduler mid-set; this way a switch simply applies
  // to the next boundary, which is what the UI promises.
  const modelRef = useRef(model);
  // Mirrored in an effect, not during render: the scheduler's interval reads
  // this, and writing a ref while rendering is a tear waiting to happen.
  useEffect(() => {
    bufferRef.current = buffer;
  }, [buffer]);
  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  const cps = useMemo(() => cpsFor(bpm), [bpm]);
  const note = useCallback((bar: number, text: string) => {
    setLog((l) => [...l, { bar, text }].slice(-14));
  }, []);

  useEffect(() => {
    if (!thinking) return;
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
          // Register the registry's OWN sources, not just the built-in
          // fallback: with drum-machines alone, every sampled instrument (the
          // piano and the nine VCSL sounds of #146/#147) resolves to nothing
          // and plays silence without an error. The palette fetch lands on
          // mount, long before a human can press Play; the fallback is only
          // for the case where the registry could not be read at all.
          const { strudel, secureContext, failed, workletError } = await boot(
            paletteRef.current?.sources?.length ? paletteRef.current.sources : undefined,
          );
          engine.current = strudel;
          setInsecure(!secureContext);
          if (workletError) setDetail(`AudioWorklet did not register: ${workletError}`);
          else if (failed.length)
            setDetail(`sound sources failed: ${failed.map((f) => f.tag).join(", ")}`);
        }
        // A backgrounded tab or a sleeping device SUSPENDS the AudioContext;
        // evaluate then schedules onto a stopped clock and the page reads
        // "playing" in total silence (the playground's first real practice,
        // 2026-08-30). Every evaluate here is gesture-driven, so resuming is
        // always allowed.
        const ctx = engine.current.getAudioContext?.();
        if (ctx && ctx.state === "suspended") {
          await ctx.resume();
          note(barsRef.current, "audio context was suspended — resumed");
        }

        await engine.current.evaluate(code);

        // §9.1: while the HUMAN holds the pen, every evaluate of a changed
        // buffer becomes a `human: …` entry in the recent-reasons ring —
        // diffed, never typed. Nobody live-coding narrates their own edits
        // into a text box mid-phrase, and without this the mind is told the
        // buffer changed but never what the human did to it.
        if (penRef.current !== "mind" && lastEvaluated.current !== null) {
          const summary = summarizeHumanEdit(lastEvaluated.current, code) as string | null;
          if (summary) {
            setReasons((r) => pushReason(r, summary) as string[]);
            note(barsRef.current, `${summary} — the mind will be told`);
          }
        }
        lastEvaluated.current = code;

        if (startedAt.current === null) startedAt.current = Date.now();
        setPhase("playing");
        setDetail(`playing · run ${id}`);
      } catch (err) {
        setPhase("failed");
        setDetail(String(err));
      }
    },
    [runId, note],
  );

  const stop = useCallback(() => {
    engine.current?.hush();
    startedAt.current = null;
    lastBoundary.current = null;
    lastFlip.current = null;
    setBarsNow(0);
    setPhase("stopped");
    setDetail("stopped");
  }, []);

  /**
   * Ask the mind. `scheduled` marks a call the phrase scheduler made — only
   * those may auto-apply, and only when the tie rule allows it.
   */
  const ask = useCallback(
    async (scheduled = false) => {
      if (inFlight.current) return;
      const seen = bufferRef.current;
      inFlight.current = true;
      setElapsed(0);
      setThinking(true);
      setMindError(null);
      setProposal(null);
      try {
        const at = barsRef.current;
        const out = await askMind({
          code: seen,
          intent,
          genre,
          key,
          recentReasons: reasons,
          barsElapsed: at,
          // Empty means "the mind's default" — the field is then omitted
          // entirely rather than sent as a choice nobody made.
          model: modelRef.current || undefined,
        });
        setAnsweredBy(out.model);
        const diff = diffLines(seen, out.code) as DiffRow[];
        setReasons((r) => pushReason(r, out.reason) as string[]);

        // The tie rule (#148) gates the AUTOMATIC path only. A hand-clicked
        // Apply is a human looking at the diff and is never blocked.
        const tie = autoApplyDecision({ askedWith: seen, current: bufferRef.current });
        if (scheduled && tie.apply) {
          setBuffer(out.code);
          void evaluate(out.code);
          note(at, `mind applied · ${out.reason.slice(0, 60)}`);
        } else {
          setProposal({ code: out.code, reason: out.reason, seen, diff, scheduled });
          if (scheduled) note(at, `held · ${tie.why}`);
        }
      } catch (err) {
        const e = err instanceof MindError ? err : new MindError(0, "the mind call failed", String(err));
        setMindError(e);
        note(barsRef.current, `mind failed · ${e.message.slice(0, 50)}`);
      } finally {
        inFlight.current = false;
        setThinking(false);
      }
    },
    [intent, genre, key, reasons, evaluate, note],
  );

  // Same reason: the interval must call the CURRENT `ask`, not the one that
  // existed when it was created, and the mirror belongs in an effect.
  const askRef = useRef(ask);
  useEffect(() => {
    askRef.current = ask;
  }, [ask]);

  // --- the scheduler --------------------------------------------------------
  // All the deciding is the pen module's; this only supplies a clock and obeys.
  useEffect(() => {
    if (phase !== "playing") return;
    const t = setInterval(() => {
      const secs = startedAt.current === null ? 0 : (Date.now() - startedAt.current) / 1000;
      const bars = barsElapsed(secs, cps) as number;
      barsRef.current = bars;
      setBarsNow(bars);

      const flip = b2bDecide({
        barsNow: bars,
        lastFlipBar: lastFlip.current,
        b2bBars,
        mode: b2b ? "b2b" : "free",
        playing: true,
        pen: penRef.current,
      });
      if (flip.consume) lastFlip.current = flip.at;
      if (flip.flip && flip.to) {
        penRef.current = flip.to as PenHolder;
        setPen(flip.to as PenHolder);
        note(bars, `b2b · the pen goes to the ${flip.to}`);
      }

      const d = decide({
        barsNow: bars,
        lastBoundaryBar: lastBoundary.current,
        phraseBars,
        inFlight: inFlight.current,
        pen: penRef.current,
        playing: true,
      });
      if (d.consume) lastBoundary.current = d.at;
      setWhy(d.why);
      if (d.fire) {
        note(bars, "boundary · asking the mind");
        void askRef.current(true);
      } else if (d.consume) {
        note(bars, `boundary SKIPPED · ${d.why}`);
      }
    }, 250);
    return () => clearInterval(t);
  }, [phase, cps, phraseBars, b2bBars, b2b, note]);

  const handTheP = useCallback(() => {
    const next = togglePen(penRef.current) as PenHolder;
    penRef.current = next;
    setPen(next);
  }, []);

  const addMidiLayer = useCallback(() => {
    if (!midiPort) return;
    setBuffer((b) =>
      insertIntoBuffer(b, `note("c2 eb2 g2").midi(${JSON.stringify(midiPort)})`),
    );
  }, [midiPort]);

  const insertSound = useCallback((line: string) => {
    setBuffer((b) => insertIntoBuffer(b, line));
  }, []);

  /**
   * Hear one sound alone. Only offered while STOPPED: `evaluate` replaces the
   * running pattern, so an audition mid-set would take the room with it.
   */
  const auditionSound = useCallback(
    (line: string) => {
      void evaluate(line);
    },
    [evaluate],
  );

  const applyProposal = useCallback(() => {
    if (!proposal) return;
    setBuffer(proposal.code);
    setProposal(null);
    void evaluate(proposal.code);
  }, [proposal, evaluate]);

  const playing = phase === "playing";
  const tie = proposal
    ? autoApplyDecision({ askedWith: proposal.seen, current: buffer })
    : null;
  const added = proposal?.diff.filter((l) => l.type === "add").length ?? 0;
  const removed = proposal?.diff.filter((l) => l.type === "del").length ?? 0;

  const strip = (
    <TurnStrip
      pen={pen}
      barsNow={barsNow}
      phraseBars={phraseBars}
      nextBoundaryBar={playing ? (nextBoundaryBar(barsNow, phraseBars) as number) : null}
      barsToFlip={b2b && playing ? (barsUntilFlip(barsNow, b2bBars) as number) : null}
      working={thinking ? intent : null}
      why={playing ? why : null}
      onTogglePen={handTheP}
      onToggleB2b={() => setB2b((v) => !v)}
      b2b={b2b}
    />
  );

  const codeView = (
    <pre
      data-testid="code-display"
      className="font-mono text-ember-text whitespace-pre-wrap break-words"
    >
      {buffer}
    </pre>
  );

  const numberField = (
    label: string,
    hint: string,
    value: number,
    onChange: (n: number) => void,
    testid: string,
  ) => (
    <label className="flex flex-col gap-1">
      <span className="font-mono uppercase tracking-mono text-[10px] text-faint leading-tight">
        {label}
        <br />
        <span className="text-faint/70">{hint}</span>
      </span>
      <input
        type="number"
        min={1}
        value={value}
        data-testid={testid}
        onChange={(e) => onChange(Number(e.target.value) || value)}
        className="bg-surf border border-line rounded px-2 py-1 font-mono text-sm text-ember-text outline-none focus:border-line2"
      />
    </label>
  );

  const rail = (
    <aside className="flex flex-col gap-4 lg:w-[250px] shrink-0">
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => void evaluate(buffer)}
          disabled={phase === "booting"}
          data-testid="evaluate"
          className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2.5 rounded bg-ember text-ink disabled:opacity-40 cursor-pointer text-left"
        >
          {playing ? "Re-evaluate" : "Play"}
          <span className="block text-[9px] normal-case tracking-normal opacity-70">
            evaluates the editor buffer
          </span>
        </button>
        <button
          type="button"
          onClick={stop}
          disabled={!playing}
          data-testid="stop"
          className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2.5 rounded border border-line2 disabled:opacity-40 cursor-pointer text-left"
        >
          Stop
        </button>
      </div>

      <div className="flex gap-2">
        <label className="flex flex-col gap-1 flex-1 min-w-0">
          <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
            Genre
          </span>
          <select
            data-testid="genre"
            value={genre}
            onChange={(e) => setGenre(e.target.value)}
            className="bg-surf border border-line rounded px-2 py-1 font-mono text-[11px] text-ember-text outline-none focus:border-line2"
          >
            {/* An empty value means no fence: the registry-wide palette. */}
            <option value="">no fence</option>
            <option value="deep">deep</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 flex-1 min-w-0">
          <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
            Key
          </span>
          <select
            data-testid="key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="bg-surf border border-line rounded px-2 py-1 font-mono text-[11px] text-ember-text outline-none focus:border-line2"
          >
            {KEYS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Only when the mind said what it serves. No list, no selector — the
          page then plays on the mind's own default exactly as before. */}
      {mindModels && mindModels.models.length > 1 && (
        <label className="flex flex-col gap-1">
          <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
            Mind{" "}
            {answeredBy && (
              <span className="text-faint normal-case tracking-normal">
                · answered by {answeredBy}
              </span>
            )}
          </span>
          <select
            data-testid="model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="bg-surf border border-line rounded px-2 py-1 font-mono text-[11px] text-ember-text outline-none focus:border-line2"
          >
            <option value="">
              default{mindModels.default ? ` · ${mindModels.default}` : ""}
            </option>
            {mindModels.models.map((m) => (
              <option key={m} value={m}>
                {m}
                {MODEL_NOTES[m] ? ` — ${MODEL_NOTES[m]}` : ""}
              </option>
            ))}
          </select>
          <span className="font-mono text-[10px] text-faint">
            Takes effect on the next ask, not the one in flight.
          </span>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
          Intent
        </span>
        <input
          data-testid="intent"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="darker · more space · build"
          className="bg-surf border border-line rounded px-2 py-2 font-sans text-sm text-ember-text outline-none focus:border-line2"
        />
      </label>

      <button
        type="button"
        onClick={() => void ask()}
        disabled={thinking || intent.trim().length === 0}
        data-testid="ask-mind"
        className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2.5 rounded bg-cream text-ink disabled:opacity-40 cursor-pointer text-left"
      >
        Mind
        <span className="block text-[9px] normal-case tracking-normal opacity-70">
          asks now, outside the phrase grid
        </span>
      </button>

      {numberField(
        "Phrase",
        "bars between the mind's mutations",
        phraseBars,
        setPhraseBars,
        "phrase-bars",
      )}
      {numberField(
        "B2B",
        "bars per turn before the pen flips",
        b2bBars,
        setB2bBars,
        "b2b-bars",
      )}
      {numberField("BPM", "sets the bar clock", bpm, setBpm, "bpm")}

      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
          MIDI out
        </span>
        {/* Availability is NOT checked during render: `midiSupport()` reads
            `window.isSecureContext`, which the server cannot know, and doing so
            here produced a hydration mismatch (React #418). `enableMidi()`
            already reports which way it failed, so the button is always offered
            and the answer arrives on the click. */}
        {midiPorts === null ? (
          <button
            type="button"
            onClick={() => void askForMidi()}
            data-testid="enable-midi"
            className="font-mono uppercase tracking-mono text-[10.5px] px-3 py-2 rounded border border-line2 text-ember-text cursor-pointer text-left"
          >
            Enable MIDI
            <span className="block text-[9px] normal-case tracking-normal text-faint">
              play your own synths from here
            </span>
          </button>
        ) : midiPorts.length === 0 ? (
          <p data-testid="midi-error" className="text-warn text-xs">
            {midiError ??
              "no MIDI outputs — open a virtual port (loopMIDI, IAC, MIDI Through) and enable again"}
          </p>
        ) : (
          <>
            <select
              data-testid="midi-port"
              value={midiPort}
              onChange={(e) => setMidiPort(e.target.value)}
              className="bg-surf border border-line rounded px-2 py-1 font-mono text-[11px] text-ember-text outline-none focus:border-line2"
            >
              {midiPorts.map((p) => (
                <option key={p.id} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={addMidiLayer}
              data-testid="add-midi-layer"
              className="font-mono uppercase tracking-mono text-[10.5px] px-3 py-2 rounded border border-line2 text-ember-text cursor-pointer text-left"
            >
              Add a MIDI layer
              <span className="block text-[9px] normal-case tracking-normal text-faint">
                .midi({midiPort ? `"${midiPort}"` : "…"}) — notes leave, no sound here
              </span>
            </button>
          </>
        )}
      </div>

      <div
        data-testid="scheduler-log"
        className="flex flex-col gap-1 font-mono text-[10.5px] text-faint max-h-[220px] overflow-y-auto"
      >
        {log.length === 0 ? (
          <span>the scheduler has said nothing yet</span>
        ) : (
          log.map((l, i) => (
            <span key={i}>
              bar {l.bar} · {l.text}
            </span>
          ))
        )}
      </div>
    </aside>
  );

  const proposalPane = (
    <section
      data-testid="proposal-pane"
      className="flex flex-col border border-line rounded-md bg-surf min-h-[380px]"
    >
      <header className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-line">
        <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
          Proposal — what the mind would play
        </span>
        {thinking && (
          <span
            data-testid="thinking"
            className="font-mono uppercase tracking-mono text-[10.5px] text-ember"
          >
            thinking… {elapsed}s
          </span>
        )}
      </header>

      <div className="flex-1 overflow-auto">
        {mindError && (
          <div data-testid="mind-error" className="px-4 py-3">
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
          <div data-testid="proposal" data-auto-appliable={String(tie?.apply ?? false)}>
            <p className="px-4 py-3 text-ok text-sm italic font-display border-b border-line">
              {proposal.reason || "no reason given"}
            </p>
            {tie && !tie.apply && (
              <p data-testid="tie-warning" className="px-4 py-2 text-xs text-warn border-b border-line">
                {tie.why}
              </p>
            )}
            <pre className="px-4 py-3 font-mono text-xs overflow-x-auto">
              {proposal.diff.map((l, i) => (
                <div
                  key={i}
                  className={
                    l.type === "add" ? "text-ok" : l.type === "del" ? "text-ember" : "text-faint"
                  }
                >
                  {l.type === "add" ? "+ " : l.type === "del" ? "- " : "  "}
                  {l.text}
                </div>
              ))}
            </pre>
          </div>
        )}

        {!proposal && !mindError && !thinking && (
          <p className="px-4 py-3 text-faint text-sm">waiting for the mind…</p>
        )}
      </div>

      {proposal && (
        <footer className="flex items-center gap-3 px-4 py-3 border-t border-line">
          <button
            type="button"
            onClick={applyProposal}
            data-testid="apply"
            className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded bg-cream text-ink cursor-pointer"
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
          <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
            +{added} −{removed}
          </span>
        </footer>
      )}
    </section>
  );

  // The viewer renders NOTHING interactive and boots NO engine: OBS captures
  // video, the audio comes from the operator's desktop, and a second engine
  // would double every sound. §11.2: it broadcasts, it does not converse — no
  // chat here either.
  if (isViewer) {
    return (
      <main
        data-testid="viewer"
        className="min-h-screen bg-ink text-ember-text font-sans p-8 flex flex-col gap-5"
      >
        <div className="flex items-baseline gap-4">
          <span className="font-display italic text-2xl tracking-display-snug">
            {mirror?.pen === "mind" ? "Mind" : "You"}
          </span>
          <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
            holds the pen
          </span>
          {mirror && (
            <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
              bar {mirror.barsNow} · phrase {mirror.phraseBars}
            </span>
          )}
        </div>

        {mirror?.reason && (
          <p className="font-display italic text-mute text-lg">{mirror.reason}</p>
        )}

        <pre
          data-testid="viewer-code"
          className="font-mono text-ember-text text-lg leading-relaxed whitespace-pre-wrap break-words"
        >
          {mirror?.buffer ?? "waiting for the set to start…"}
        </pre>
      </main>
    );
  }

  return (
    <Shell sessionLabel="algorave" hideNav={mode === "immersive"}>
      <div
        className={
          "flex flex-col gap-4 " + (mode === "immersive" ? "p-6 min-h-screen" : "px-7 py-6")
        }
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-baseline gap-4">
            <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
              Live coding
            </span>
            <Crumb>
              run {runId ?? "—"} · {bpm} BPM
            </Crumb>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              data-testid="copy-obs"
              onClick={() => {
                const url = viewerUrlFor(window.location.href);
                void navigator.clipboard?.writeText(url);
                setDetail(`OBS feed URL copied — ${url}`);
              }}
              title="Copies the read-only URL for an OBS Browser Source. Both tabs can stay open."
              className="font-mono uppercase tracking-mono text-[10.5px] px-3 py-1.5 rounded border border-line2 text-mute hover:text-ember cursor-pointer"
            >
              copy OBS feed
            </button>
            <ModeSwitcher mode={mode} onChange={setMode} />
          </div>
        </div>

        {insecure && (
          <div
            data-testid="insecure-warning"
            className="border border-line2 border-l-2 border-l-warn rounded-md bg-surf px-4 py-3"
          >
            <p className="font-mono uppercase tracking-mono text-[10.5px] text-warn mb-1">
              Non-secure origin
            </p>
            <p className="text-mute text-sm">
              The browser exposes no <code>AudioWorklet</code> here, so samples play but
              every worklet-backed sound — supersaw, the effects chain — does not. Reach
              this page over HTTPS, or through <code>localhost</code>.
            </p>
          </div>
        )}

        {mode === "cabin" && (
          <>
            {strip}
            <div className="flex flex-col lg:flex-row gap-4 items-stretch">
              <section className="flex flex-col flex-1 min-w-0 border border-line rounded-md bg-surf">
                <header className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-line">
                  <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
                    Editor — the code the room hears
                  </span>
                  <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
                    ⌘/Ctrl+Enter evaluates · ⌃Space completes
                  </span>
                </header>
                <CodeEditor
                  value={buffer}
                  onChange={setBuffer}
                  onEvaluate={() => void evaluate(bufferRef.current)}
                  palette={palette}
                  className="flex-1 min-h-[380px] overflow-auto px-2"
                />
                <footer className="flex items-center justify-between gap-3 px-4 py-2 border-t border-line flex-wrap">
                  <span
                    data-testid="status"
                    data-phase={phase}
                    className={"text-xs " + (phase === "failed" ? "text-ember" : "text-mute")}
                  >
                    {detail}
                  </span>
                  {/* The same verdict the mind is held to, applied as you
                      type. `invalid` means it will not play; out-of-key means
                      it WILL play and clash — different colours on purpose. */}
                  <span
                    data-testid="verdict"
                    data-tone={reading.tone}
                    className={
                      "font-mono text-[10.5px] uppercase tracking-mono " +
                      (reading.tone === "error"
                        ? "text-ember"
                        : reading.tone === "warn"
                          ? "text-warn"
                          : reading.tone === "ok"
                            ? "text-ok"
                            : "text-faint")
                    }
                    title={reading.facts.join(" · ")}
                  >
                    {checking ? "checking…" : reading.headline}
                    {reading.facts.length > 0 && (
                      <span className="text-faint normal-case tracking-normal">
                        {" "}
                        · {reading.facts.join(" · ")}
                      </span>
                    )}
                  </span>
                </footer>
              </section>

              <div className="flex-1 min-w-0">{proposalPane}</div>
              {rail}
            </div>

            <section className="border border-line rounded-md bg-surf px-4 py-3">
              <header className="mb-3">
                <span className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
                  Palette — what the mind may write, and so may you
                </span>
              </header>
              <PaletteBrowser
                palette={palette}
                error={paletteError}
                onInsert={insertSound}
                onAudition={playing ? undefined : auditionSound}
              />
            </section>
          </>
        )}

        {mode === "audience" && (
          <div className="flex flex-col gap-5">
            {strip}
            <div className="bg-surf border border-line rounded-md p-8 text-lg leading-relaxed">
              {codeView}
            </div>
          </div>
        )}

        {mode === "immersive" && (
          <div className="flex-1 flex flex-col items-center justify-center gap-6 text-xl leading-relaxed">
            {codeView}
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
