"use client";
/**
 * The composer — the prompt box at the top of `/generations`.
 *
 * The Suno shape: you describe a song where you will listen to it, and the
 * result lands in the feed right below, not in a modal over some other
 * page. This component owns exactly one task at a time: it submits through
 * `useGeneratorTask` (the same hook the dialog uses), hands the feed a
 * pending card the moment ACE accepts the job (`onAdopt`), and tells the
 * feed to re-read that card when the takes land (`onLanded`). It never
 * renders takes itself — the card does, with the same rows as everywhere.
 *
 * It is visible even when ACE is off. The rule for the editor's tile and
 * the catalog's button — unavailable renders NOTHING — is right for a door
 * on someone else's page; on the page whose point IS the prompt box, a box
 * that says why it is inert beats a page with nothing on it.
 */
import * as React from "react";
import {
  useGeneratorHealth,
  useGeneratorTask,
  type CreateTaskRequest,
  type CreateTaskResponse,
} from "@/lib/generator";
import { Crumb } from "./primitives";
import { Spinner } from "./feedback";
import { GeneratorForm } from "./GeneratorForm";

export type GeneratorComposerProps = {
  /** ACE accepted the job: the feed shows a pending card for it now. */
  onAdopt: (res: CreateTaskResponse, request: CreateTaskRequest) => void;
  /** The task resolved (done or failed): the feed re-reads that card. */
  onLanded: (taskId: string) => void;
  defaultGenre?: string | null;
};

export const ACE_OFF_REASON = "ACE is not running — start it from the panel below";
export const ACE_LIVE_REASON = "A set is on air — generation shares the GPU with it";

export function GeneratorComposer({ onAdopt, onLanded, defaultGenre = null }: GeneratorComposerProps) {
  const health = useGeneratorHealth();
  const { state, etaCountdown, submit, reset } = useGeneratorTask();
  const lastRequest = React.useRef<CreateTaskRequest | null>(null);
  const adoptedFor = React.useRef<string | null>(null);
  const landedFor = React.useRef<string | null>(null);

  const disabledReason =
    health.status === "unavailable"
      ? ACE_OFF_REASON
      : health.status === "ready" && health.health.blocked_by_live
        ? ACE_LIVE_REASON
        : null;

  // Adopt once per task id, in an effect: `submit` resolves inside the hook
  // and the id only exists in its state afterwards.
  React.useEffect(() => {
    if (!state.taskId || adoptedFor.current === state.taskId || !lastRequest.current) return;
    adoptedFor.current = state.taskId;
    onAdopt(
      { task_id: state.taskId, queue_position: state.queuePosition, eta_seconds: state.etaSeconds },
      lastRequest.current,
    );
  }, [state.taskId, state.queuePosition, state.etaSeconds, onAdopt]);

  // When it lands, the card re-reads itself and the box is ready again.
  React.useEffect(() => {
    if (!state.taskId || landedFor.current === state.taskId) return;
    if (state.phase !== "done" && state.phase !== "failed") return;
    landedFor.current = state.taskId;
    onLanded(state.taskId);
    if (state.phase === "done") reset();
  }, [state.phase, state.taskId, onLanded, reset]);

  const onSubmit = React.useCallback(
    (body: CreateTaskRequest) => {
      lastRequest.current = body;
      void submit(body);
    },
    [submit],
  );

  const pending = state.phase === "pending";

  return (
    <div className="flex flex-col gap-3">
      <GeneratorForm
        active
        variant="composer"
        busy={state.phase === "submitting"}
        disabled={disabledReason !== null || pending}
        disabledReason={pending ? null : disabledReason}
        error={state.phase === "failed" ? null : state.error}
        errorStatus={state.errorStatus}
        defaultGenre={defaultGenre}
        onSubmit={onSubmit}
      />
      {pending && (
        <div data-testid="composer-pending" className="flex items-center gap-3 flex-wrap">
          <span className="flex items-center gap-2 text-mute font-mono text-[11px] uppercase tracking-mono">
            <Spinner />
            ACE is writing ·{" "}
            {state.queuePosition == null
              ? "queued"
              : state.queuePosition === 0
                ? "running"
                : `queue position ${state.queuePosition}`}
          </span>
          <span className="font-mono text-[11px] text-ember" data-testid="composer-eta">
            {etaCountdown == null ? "eta unknown" : etaCountdown === 0 ? "any second now" : `~${etaCountdown}s left`}
          </span>
          {state.degraded && (
            <span className="font-mono text-[10px] text-faint uppercase tracking-mono">· reconnecting</span>
          )}
          <Crumb>the card is below — it fills in when the takes land</Crumb>
        </div>
      )}
      {state.phase === "failed" && (
        <div data-testid="composer-failed" className="flex items-center gap-3 flex-wrap">
          <span className="text-[12px] text-warn">
            That one didn&rsquo;t land{state.error ? ` — ${state.error}` : ""}. The card below keeps ACE&rsquo;s words.
          </span>
          <button
            type="button"
            onClick={reset}
            className="bg-transparent border-0 p-0 cursor-pointer font-mono text-[10px] uppercase tracking-mono text-ember"
          >
            try another
          </button>
        </div>
      )}
    </div>
  );
}
