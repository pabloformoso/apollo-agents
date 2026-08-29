"use client";
/**
 * Apollo G1 — ACE-Step generator client + polling state machine.
 *
 * Talks to the backend's generator router (`web/backend/generator.py`),
 * never to the ACE box on :8001 — auth and LAN isolation live server-side
 * and the audio proxy is the browser's only way to the WAVs.
 *
 * Contract (docs/acestep-wizard-plan.md, "G1 contract"):
 *   - `GET  /api/generator/health`      → {available, blocked_by_live, stats}
 *   - `POST /api/generator/tasks`       → {task_id, queue_position, eta_seconds}
 *   - `GET  /api/generator/tasks/{id}`  → {status, takes[], eta_seconds, degraded?}
 *   - `GET  /api/generator/audio?path=` → streaming proxy
 *
 * Two refusals are first-class, not crashes:
 *   - **503** the generator is off. `available: false` is a NORMAL answer
 *     (the ACE box is powered down most of the time by design), so the
 *     affordance hides rather than erroring.
 *   - **409** a set is on air. Apollo's half of the VRAM protocol — ACE
 *     retains ~12.5 GB of the shared 16 GB once loaded, which starves the
 *     live DJ's model. The server's message is rendered VERBATIM; we never
 *     paraphrase a protocol refusal.
 *
 * Polling survives blips by design: the backend already downgrades its own
 * transport errors to `{status: "pending", degraded: true}`, and this module
 * does the same for a failed browser→Apollo hop. A degraded poll is a blip,
 * not a failed task — it must never tear the card down.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { getToken } from "./auth";

const BASE = `${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api`;

/** House poll cadence for an in-flight generation (G1 contract). */
export const POLL_INTERVAL_MS = 3000;

// ── Wire types ────────────────────────────────────────────────────────────

export type GeneratorHealth = {
  available: boolean;
  blocked_by_live: boolean;
  stats: Record<string, unknown> | null;
};

/** ACE's per-take metadata block. Every field is optional — a take that
 *  carried a `result_parse_error` still renders, just without chips. */
export type TakeMetas = {
  bpm?: number | null;
  duration?: number | null;
  genres?: string | string[] | null;
  keyscale?: string | null;
  timesignature?: string | null;
};

export type Take = {
  index: number;
  /** Opaque server-side path — feed it to `takeAudioUrl`, never to :8001. */
  file: string;
  prompt?: string | null;
  lyrics?: string | null;
  metas?: TakeMetas | null;
  seed_value?: number | string | null;
  /** Carried through, not fatal (G1 contract). */
  result_parse_error?: string | null;
};

export type TaskStatus = "pending" | "done" | "failed";

export type TaskSnapshot = {
  status: TaskStatus;
  takes?: Take[] | null;
  eta_seconds?: number | null;
  degraded?: boolean;
  error?: string | null;
};

export type CreateTaskRequest = {
  prompt: string;
  lyrics?: string;
  audio_duration: number;
  vocal_language?: string;
  genre_folder: string;
  bpm?: number;
  key_scale?: string;
  batch_size?: number;
  experimental?: Record<string, unknown>;
};

export type CreateTaskResponse = {
  task_id: string;
  queue_position: number | null;
  eta_seconds: number | null;
};

// ── Errors ────────────────────────────────────────────────────────────────

/** HTTP-status-carrying error. `lib/api.ts`'s `req` throws a bare Error, so
 *  the generator keeps its own so callers can branch on 409 vs 503 vs 422. */
export class GeneratorError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "GeneratorError";
    this.status = status;
  }
  /** A live set is on air — the VRAM protocol. Message is verbatim server copy. */
  get isLiveBlocked(): boolean {
    return this.status === 409;
  }
  /** The generator is switched off — a normal state, not a fault. */
  get isDisabled(): boolean {
    return this.status === 503;
  }
}

/** FastAPI's `detail` is a string on HTTPException and a list of
 *  `{loc, msg, type}` on a 422. Flatten both into one human line. */
function detailToMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && "msg" in d) {
          const loc = (d as { loc?: unknown }).loc;
          const field = Array.isArray(loc) ? String(loc[loc.length - 1]) : null;
          const msg = String((d as { msg?: unknown }).msg ?? "");
          return field ? `${field}: ${msg}` : msg;
        }
        return null;
      })
      .filter(Boolean);
    if (parts.length) return parts.join(" · ");
  }
  return null;
}

async function gfetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((options.headers as Record<string, string>) ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new GeneratorError(
      res.status,
      detailToMessage(body) ?? `Request failed (HTTP ${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

// ── Endpoints ─────────────────────────────────────────────────────────────

export const getGeneratorHealth = () =>
  gfetch<GeneratorHealth>("/generator/health");

export const createGeneratorTask = (body: CreateTaskRequest) =>
  gfetch<CreateTaskResponse>("/generator/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getGeneratorTask = (taskId: string) =>
  gfetch<TaskSnapshot>(`/generator/tasks/${encodeURIComponent(taskId)}`);

/**
 * Audio URL for a take. `<audio>` can't set an Authorization header, so the
 * JWT rides the query string — the same trick `streamUrl` and the render SSE
 * use (the backend's `auth_query_token` helper reads it when the header is
 * absent). The `path` is opaque: pass ACE's `file` through untouched.
 */
export function takeAudioUrl(path: string): string {
  const token = getToken() ?? "";
  const q = `path=${encodeURIComponent(path)}`;
  return `${BASE}/generator/audio?${q}${token ? `&token=${encodeURIComponent(token)}` : ""}`;
}

// ── ETA maths ─────────────────────────────────────────────────────────────

/**
 * Seconds left on the ETA clock.
 *
 * `etaSeconds` is the server's estimate at the moment of the last poll
 * (`etaAtMs`); between polls we simply subtract wall time, so the countdown
 * ticks down smoothly and RESETS to the fresh server number on each poll
 * rather than drifting off a stale one. Floors at 0 — an overdue job shows
 * "any second now", never a negative.
 */
export function etaRemaining(
  etaSeconds: number | null | undefined,
  etaAtMs: number | null | undefined,
  nowMs: number,
): number | null {
  if (etaSeconds == null || !Number.isFinite(etaSeconds)) return null;
  if (etaAtMs == null || !Number.isFinite(etaAtMs)) return Math.max(0, Math.ceil(etaSeconds));
  const elapsedSec = Math.max(0, (nowMs - etaAtMs) / 1000);
  return Math.max(0, Math.ceil(etaSeconds - elapsedSec));
}

// ── Task state machine ────────────────────────────────────────────────────

export type TaskPhase = "idle" | "submitting" | "pending" | "done" | "failed";

export type GeneratorTaskState = {
  phase: TaskPhase;
  taskId: string | null;
  /** From the POST response — the GET contract doesn't re-send it. */
  queuePosition: number | null;
  /** Server ETA as of `etaAtMs`. Refreshed by every poll that carries one. */
  etaSeconds: number | null;
  etaAtMs: number | null;
  /** Last poll was a blip (server-flagged or a failed browser hop). */
  degraded: boolean;
  takes: Take[];
  error: string | null;
  /** HTTP status behind `error`, so the UI can tone a 409 differently. */
  errorStatus: number | null;
};

export const INITIAL_TASK_STATE: GeneratorTaskState = {
  phase: "idle",
  taskId: null,
  queuePosition: null,
  etaSeconds: null,
  etaAtMs: null,
  degraded: false,
  takes: [],
  error: null,
  errorStatus: null,
};

/**
 * Fold one poll response into the state.
 *
 * Pure so the transitions are unit-testable without timers or fetch:
 *   pending → pending  (ETA refreshed, degraded flag cleared/raised)
 *   pending → done     (takes land, countdown stops)
 *   pending → failed   (error surfaces)
 * A degraded snapshot NEVER fails the task and never drops the ETA it can't
 * refresh — the previous estimate keeps counting down through the blip.
 */
export function applySnapshot(
  prev: GeneratorTaskState,
  snap: TaskSnapshot,
  nowMs: number,
): GeneratorTaskState {
  const degraded = Boolean(snap.degraded);
  if (snap.status === "done") {
    return {
      ...prev,
      phase: "done",
      takes: snap.takes ?? [],
      degraded: false,
      etaSeconds: 0,
      etaAtMs: nowMs,
      error: null,
      errorStatus: null,
    };
  }
  if (snap.status === "failed") {
    return {
      ...prev,
      phase: "failed",
      takes: snap.takes ?? prev.takes,
      degraded: false,
      error: snap.error ?? "Generation failed.",
      errorStatus: null,
    };
  }
  const hasEta = snap.eta_seconds != null && Number.isFinite(snap.eta_seconds);
  return {
    ...prev,
    phase: "pending",
    takes: snap.takes ?? prev.takes,
    degraded,
    etaSeconds: hasEta ? (snap.eta_seconds as number) : prev.etaSeconds,
    etaAtMs: hasEta ? nowMs : prev.etaAtMs,
    error: null,
    errorStatus: null,
  };
}

/**
 * Fold a THROWN poll into the state.
 *
 * A transport blip on the browser→Apollo hop is the same class of event as
 * the backend's own ACE blip: degrade, keep polling. Only an answer that
 * says the task is gone or we're no longer allowed to see it (401/403/404)
 * ends the poll loop — otherwise a wrong turn would spin forever.
 */
export function applyPollError(
  prev: GeneratorTaskState,
  err: unknown,
): GeneratorTaskState {
  if (err instanceof GeneratorError && [401, 403, 404].includes(err.status)) {
    return {
      ...prev,
      phase: "failed",
      degraded: false,
      error: err.message,
      errorStatus: err.status,
    };
  }
  return { ...prev, degraded: true };
}

export type GeneratorTaskApi = {
  state: GeneratorTaskState;
  /** Seconds left, recomputed every second while pending. Null when the
   *  server couldn't estimate (stats unavailable). */
  etaCountdown: number | null;
  submit: (body: CreateTaskRequest) => Promise<void>;
  reset: () => void;
};

/**
 * Own one generation task: submit, then poll every `pollMs` until the task
 * resolves. The first poll fires immediately so the card isn't blank for
 * three seconds.
 */
export function useGeneratorTask(
  pollMs: number = POLL_INTERVAL_MS,
): GeneratorTaskApi {
  const [state, setState] = useState<GeneratorTaskState>(INITIAL_TASK_STATE);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  const { phase, taskId } = state;
  const polling = phase === "pending" && taskId !== null;

  useEffect(() => {
    if (!polling || !taskId) return;
    let cancelled = false;
    const tick = () =>
      getGeneratorTask(taskId)
        .then((snap) => {
          if (cancelled) return;
          setState((prev) => applySnapshot(prev, snap, Date.now()));
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setState((prev) => applyPollError(prev, err));
        });
    void tick();
    const id = setInterval(tick, pollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [polling, taskId, pollMs]);

  // 1 s clock for the countdown — same shape as the render screen's elapsed
  // ticker. Only runs while something is actually in flight.
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [polling]);

  const submit = useCallback(async (body: CreateTaskRequest) => {
    setState({ ...INITIAL_TASK_STATE, phase: "submitting" });
    try {
      const res = await createGeneratorTask(body);
      setState({
        ...INITIAL_TASK_STATE,
        phase: "pending",
        taskId: res.task_id,
        queuePosition: res.queue_position ?? null,
        etaSeconds: res.eta_seconds ?? null,
        etaAtMs: Date.now(),
      });
    } catch (err: unknown) {
      // A refused submit is a form-level answer, not a dead task: stay on
      // the form (phase "idle") with the server's words attached.
      setState({
        ...INITIAL_TASK_STATE,
        error: err instanceof Error ? err.message : "Could not start the task.",
        errorStatus: err instanceof GeneratorError ? err.status : null,
      });
    }
  }, []);

  const reset = useCallback(() => setState(INITIAL_TASK_STATE), []);

  const etaCountdown = useMemo(
    () =>
      phase === "pending"
        ? etaRemaining(state.etaSeconds, state.etaAtMs, nowMs)
        : null,
    [phase, state.etaSeconds, state.etaAtMs, nowMs],
  );

  return { state, etaCountdown, submit, reset };
}

// ── Health / feature flag ─────────────────────────────────────────────────

export type GeneratorHealthState =
  | { status: "loading" }
  /** Env unset, box down, or the endpoint itself unreachable. The
   *  affordance HIDES — "unavailable" is a normal answer here. */
  | { status: "unavailable" }
  | { status: "ready"; health: GeneratorHealth };

/**
 * Read the generator feature flag once on mount.
 *
 * Deliberately not polled: `blocked_by_live` can flip while the screen is
 * open, and the authoritative guard for that is the 409 the POST returns —
 * which we render verbatim. A background poll would only make the button
 * grey out a few seconds earlier at the cost of a timer on every Editor
 * mount.
 */
export function useGeneratorHealth(): GeneratorHealthState {
  const [state, setState] = useState<GeneratorHealthState>({
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    getGeneratorHealth()
      .then((health) => {
        if (cancelled) return;
        setState(
          health.available ? { status: "ready", health } : { status: "unavailable" },
        );
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: "unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
