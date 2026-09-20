"use client";
/**
 * Apollo G1 — ACE-Step generation dialog (the editor's door).
 *
 * Opened from the Editor's "Generate (ACE)" tile. Same modal primitive and
 * visual voice as `TrackPicker` — the other way a track enters the set —
 * so generating material feels like a sibling of picking it.
 *
 * Two states behind one dialog:
 *   1. **The form** — `GeneratorForm`, the one definition of the request
 *      shared with the Generations page's composer. Prompt, lyrics,
 *      duration, language, genre, takes, and a collapsed Experimental panel.
 *   2. **The task card** — queue position + an ETA countdown refreshed by
 *      every poll, then the takes with the house player and metadata chips.
 *
 * Refusals are rendered, never swallowed. A 409 (the VRAM protocol: a set is
 * on air) shows the server's message VERBATIM — paraphrasing a protocol
 * refusal is how it stops being understood. The same rule carries the
 * publisher's 422s, which arrive in the ingest's own words ("bpm 90 is
 * outside the 'techno' window 120-160 BPM") and are the whole value of it.
 *
 * G2b — a take publishes into the catalog from its own row: confirm the
 * genre and the title (the title becomes the WAV's filename forever), send
 * the path the page PERSISTED when the poll landed, and the row keeps the
 * new track id. Publishing is one-way per take, so the button goes inert.
 *
 * G3 — a take can also be EDITED before it is trusted: repaint a stretch,
 * cover it, or continue it. The edit is released from the same persisted
 * path and comes back as an ordinary task id, so it renders as a CHAINED
 * card **inside its source's row** — "edited from Take 1 · repaint" — whose
 * own takes publish and edit exactly like the originals. The nesting is the
 * lineage: an edit of an edit sits one level deeper, and a chained take is
 * offered `variant of` its SOURCE's published name, which is the only way
 * the no-repeat machinery learns that the two are one piece.
 *
 * G4 — a take can be SCORED from the same row: the backend measures it with
 * the project's own quality bench and (when an LLM is wired) adds a
 * paragraph reading those numbers against the prompt. It renders as chips —
 * each reference-informed metric in or out of its band, the loudness tier
 * marked advisory — and the panel says so in its own label: scoring informs
 * the decision, it never blocks a publish. A genre with no committed
 * references answers with a note instead of a verdict, which is a normal
 * state, not an error.
 */
import * as React from "react";
import Link from "next/link";
import { useGeneratorTask, type CreateTaskRequest } from "@/lib/generator";
import { Btn, Crumb } from "./primitives";
import { Dialog } from "./Dialog";
import { Banner, Spinner } from "./feedback";
// The take row lives in its own module since G6: the generations feed
// renders exactly the same rows, and one definition is what keeps a take
// behaving identically in both frames.
import { TakeRow, playableFor } from "./GeneratorTakes";
import { EngineStatusPanel } from "./EngineStatus";
import { GeneratorForm, type GeneratorFormContext } from "./GeneratorForm";

// ── Dialog ────────────────────────────────────────────────────────────────

export type GeneratorDialogProps = {
  open: boolean;
  onClose: () => void;
  /** Session genre — preselected when it matches a real genre folder. */
  defaultGenre?: string | null;
};

export function GeneratorDialog({
  open,
  onClose,
  defaultGenre,
}: GeneratorDialogProps) {
  const { state, etaCountdown, submit, reset } = useGeneratorTask();
  // What the form resolved: the genre the takes are dressed with and the
  // real folders the publish confirm offers.
  const [ctx, setCtx] = React.useState<GeneratorFormContext>({ genre: "", genres: [] });
  // Names published from THIS batch, in publish order — the first one is
  // what a second take is offered as a variant OF.
  const [publishedNames, setPublishedNames] = React.useState<string[]>([]);

  const busy = state.phase === "submitting";
  const showForm = state.phase === "idle" || busy;
  const genre = ctx.genre;

  const onSubmit = React.useCallback(
    (body: CreateTaskRequest) => {
      void submit(body);
    },
    [submit],
  );

  const playables = React.useMemo(
    () =>
      state.takes.map((t, i) =>
        playableFor(t, state.taskId ?? "task", genre, `Take ${i + 1}`),
      ),
    [state.takes, state.taskId, genre],
  );

  const onPublished = React.useCallback((displayName: string) => {
    setPublishedNames((prev) =>
      prev.includes(displayName) ? prev : [...prev, displayName],
    );
  }, []);

  // "Generate another" starts a new batch, so the variant-of offers from
  // the old one must not follow it across.
  const startOver = React.useCallback(() => {
    setPublishedNames([]);
    reset();
  }, [reset]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width="wide"
      label="Generate a track with ACE-Step"
      surfaceClassName="flex flex-col gap-4 p-5"
    >
      <div
        className="flex flex-wrap items-baseline justify-between gap-2"
        data-testid="generator-dialog"
      >
        <Crumb tone="ember">generate · ace-step</Crumb>
        <span className="flex items-baseline gap-3">
          {state.taskId && (
            <Crumb>task {state.taskId.slice(0, 12)}</Crumb>
          )}
          {/* G6 — the batch outlives this dialog now: it is recorded
              server-side the moment it is released, so there is somewhere
              to send the operator when they close the tab on it. */}
          <Link
            href="/generations"
            data-testid="generator-view-all"
            className="font-mono text-[10px] uppercase tracking-mono text-mute hover:text-ember"
          >
            view all generations →
          </Link>
        </span>
      </div>

      <details className="text-xs text-mute">
        <summary className="cursor-pointer">Engine status</summary>
        <div className="mt-2"><EngineStatusPanel /></div>
      </details>

      {showForm ? (
        <GeneratorForm
          active={open}
          busy={busy}
          error={state.error}
          errorStatus={state.errorStatus}
          defaultGenre={defaultGenre}
          onSubmit={onSubmit}
          onCancel={onClose}
          onContext={setCtx}
        />
      ) : (
        <div className="flex flex-col gap-4" data-testid="generator-task-card">
          <div>
            <h3 className="font-display italic font-normal text-3xl tracking-display-snug m-0 leading-[1.05]">
              {state.phase === "done" ? (
                <>
                  {state.takes.length} take
                  {state.takes.length === 1 ? "" : "s"}
                  <span className="text-ember">.</span>
                </>
              ) : state.phase === "failed" ? (
                <>
                  That one didn&rsquo;t land<span className="text-ember">.</span>
                </>
              ) : (
                <>
                  ACE is writing<span className="text-ember">…</span>
                </>
              )}
            </h3>
          </div>

          {state.phase === "pending" && (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="flex items-center gap-2 text-mute font-mono text-[11px] uppercase tracking-mono">
                <Spinner />
                <span data-testid="generator-queue-position">
                  {state.queuePosition == null
                    ? "queued"
                    : state.queuePosition === 0
                      ? "running"
                      : `queue position ${state.queuePosition}`}
                </span>
              </span>
              <span
                className="font-mono text-[11px] text-ember"
                data-testid="generator-eta"
              >
                {etaCountdown == null
                  ? "eta unknown"
                  : etaCountdown === 0
                    ? "any second now"
                    : `~${etaCountdown}s left`}
              </span>
              {/* A blip, not a failure — deliberately quiet. */}
              {state.degraded && (
                <span
                  className="font-mono text-[10px] text-faint uppercase tracking-mono"
                  data-testid="generator-degraded"
                >
                  · reconnecting
                </span>
              )}
            </div>
          )}

          {state.phase === "failed" && state.error && (
            <Banner tone="error">
              <span
                data-testid="generator-error"
                className="normal-case tracking-normal font-sans text-[12px]"
              >
                {state.error}
              </span>
            </Banner>
          )}

          {state.takes.length > 0 && (
            <ul className="list-none m-0 p-0 flex flex-col max-h-[45vh] overflow-auto">
              {state.takes.map((t, i) => (
                <TakeRow
                  key={`${state.taskId}-${t.index}-${i}`}
                  take={t}
                  playable={playables[i]}
                  queue={playables}
                  genres={ctx.genres}
                  defaultGenre={genre}
                  publishedNames={publishedNames}
                  onPublished={onPublished}
                  label={`Take ${i + 1}`}
                  depth={0}
                />
              ))}
            </ul>
          )}

          <div className="flex justify-end gap-2">
            {state.phase !== "pending" && (
              <Btn
                kind="ghost"
                onClick={startOver}
                data-testid="generator-again"
                className="px-3 py-1.5 text-[11px]"
              >
                Generate another
              </Btn>
            )}
            <Btn
              kind="cream"
              onClick={onClose}
              className="px-3 py-1.5 text-[11px]"
            >
              Close
            </Btn>
          </div>
        </div>
      )}
    </Dialog>
  );
}
