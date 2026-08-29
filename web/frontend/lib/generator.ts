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

/** G2b — what the publisher sends. `file` is the take's DECODED ACE path. */
export type PublishRequest = {
  file: string;
  metas: { bpm: number; keyscale: string; duration?: number | null };
  prompt?: string;
  /** TEXT, not a filename — lands as a `.lrc` beside the WAV. */
  lyrics?: string;
  display_name: string;
  genre_folder: string;
  variant_of?: string;
};

export type PublishResponse = {
  track_id: string;
  file: string;
  display_name: string;
  camelot_key: string;
  bpm: number;
  variant_of: string | null;
  /** "run --fix-incomplete later" — rendered with the chip, not swallowed. */
  note: string;
};

/** G3 — the three edits the wizard offers (API spec §3.3). */
export type EditMode = "repaint" | "cover" | "complete";

/** What the edit sends. `file` is the SOURCE take's DECODED ACE path —
 *  no task id here either: the page owns the lineage, not the backend. */
export type EditRequest = {
  file: string;
  mode: EditMode;
  prompt?: string;
  /** SECONDS into the source, not bars and not a fraction. */
  repainting_start?: number;
  repainting_end?: number;
  audio_cover_strength?: number;
  genre_folder?: string;
  experimental?: Record<string, unknown>;
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

export const publishTake = (body: PublishRequest) =>
  gfetch<PublishResponse>("/generator/publish", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** G3 — re-release one take. Answers with a task handle like `/tasks`, so
 *  the edit is polled by the SAME loop; what makes it an edit is its
 *  source, which only the page remembers. */
export const editGeneratorTake = (body: EditRequest) =>
  gfetch<CreateTaskResponse>("/generator/edit", {
    method: "POST",
    body: JSON.stringify(body),
  });

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

/**
 * The state a freshly-released task starts in.
 *
 * Shared by `submit` and by the chained cards an edit spawns (G3), which
 * are handed a task handle rather than making one: an edit is polled by
 * exactly the same loop, so it must ENTER that loop in the same state.
 */
export function taskAdopted(
  res: CreateTaskResponse,
  nowMs: number,
): GeneratorTaskState {
  return {
    ...INITIAL_TASK_STATE,
    phase: "pending",
    taskId: res.task_id,
    queuePosition: res.queue_position ?? null,
    etaSeconds: res.eta_seconds ?? null,
    etaAtMs: nowMs,
  };
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
 *
 * `adopted` skips the submit half: the caller already has a task handle
 * (G3's chained card gets one from `POST /generator/edit`) and only wants
 * the polling. It is read ONCE, as the lazy initial state — a chained card
 * is keyed by its task id and never re-points at another task, so adopting
 * in an effect would only buy a set-state-during-render smell.
 */
export function useGeneratorTask(
  pollMs: number = POLL_INTERVAL_MS,
  adopted?: CreateTaskResponse | null,
): GeneratorTaskApi {
  const [state, setState] = useState<GeneratorTaskState>(() =>
    adopted ? taskAdopted(adopted, Date.now()) : INITIAL_TASK_STATE,
  );
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
      setState(taskAdopted(res, Date.now()));
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

// ── Publishing a take to the catalog (G2b) ────────────────────────────────

/**
 * The take's DECODED server-side path — what the publisher needs.
 *
 * ACE's `file` is `/v1/audio?path=<percent-encoded absolute path>`, encoded
 * with `quote(p, safe="")`, so every slash arrives as `%2F`. Decoded ONCE
 * here, deliberately with `decodeURIComponent` and not `URLSearchParams`:
 * the latter also turns `+` into a space, and a `+` in a filename is a real
 * character. Anything without a `path=` parameter passes through untouched.
 *
 * The page owns this value because ACE's job RECORDS expire (in-memory,
 * 24 h, and the VRAM protocol powers the box down between batches) while its
 * result FILES never do — so publish carries the path from here rather than
 * asking the backend to re-query a task that may no longer exist.
 */
export function decodedTakePath(file: string): string {
  const raw = (file ?? "").trim();
  const q = raw.indexOf("?");
  if (q === -1) return raw;
  for (const field of raw.slice(q + 1).split("&")) {
    const eq = field.indexOf("=");
    if (eq !== -1 && field.slice(0, eq) === "path") {
      try {
        return decodeURIComponent(field.slice(eq + 1));
      } catch {
        return raw;
      }
    }
  }
  return raw;
}

/** Characters the catalog can't take: `display_name` becomes the WAV's stem. */
const ILLEGAL_NAME_CHARS = /[<>:"/\\|?*]/g;

const MAX_SUGGESTED_NAME = 48;

/**
 * A publishable title guessed from the prompt.
 *
 * Only a starting point — the field is editable, and the name is what the
 * track is called in every set forever. First clause, first few words, Title
 * Case, filesystem-safe.
 */
export function suggestDisplayName(prompt: string | null | undefined): string {
  const first = (prompt ?? "").split(/[,.\n;]/)[0] ?? "";
  const words = first
    .replace(ILLEGAL_NAME_CHARS, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 5);
  const name = words
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")
    .slice(0, MAX_SUGGESTED_NAME)
    .trim();
  return name || "Untitled Take";
}

/**
 * Can this take be published at all?
 *
 * The ingest refuses to guess: `bpm` and `keyscale` come from the generator
 * that already knows them (detected metadata is how the catalog acquired its
 * poisoned BPMs). A take whose `metas` failed to parse has neither, so the
 * button says so instead of sending a request that can only 422.
 */
export function canPublishTake(take: Take): boolean {
  const metas = take.metas ?? {};
  return (
    Boolean(decodedTakePath(take.file)) &&
    typeof metas.bpm === "number" &&
    Number.isFinite(metas.bpm) &&
    Boolean(metas.keyscale && String(metas.keyscale).trim())
  );
}

export type PublishOptions = {
  displayName: string;
  genreFolder: string;
  /** Base take's display name — set when this is a second take. */
  variantOf?: string | null;
};

/** Build the wire body from the take the page PERSISTED plus the form. */
export function buildPublishRequest(
  take: Take,
  opts: PublishOptions,
): PublishRequest {
  const metas = take.metas ?? {};
  const body: PublishRequest = {
    file: decodedTakePath(take.file),
    metas: {
      bpm: Number(metas.bpm),
      keyscale: String(metas.keyscale ?? "").trim(),
      duration: typeof metas.duration === "number" ? metas.duration : null,
    },
    display_name: opts.displayName.trim(),
    genre_folder: opts.genreFolder,
  };
  if (take.prompt && take.prompt.trim()) body.prompt = take.prompt;
  if (take.lyrics && take.lyrics.trim()) body.lyrics = take.lyrics;
  if (opts.variantOf && opts.variantOf.trim()) {
    body.variant_of = opts.variantOf.trim();
  }
  return body;
}

/**
 * idle → confirm → publishing → published | failed
 *
 * `confirm` is a deliberate stop: publishing writes a WAV and a catalog entry
 * under a name that can't be changed afterwards without a rename, so the
 * genre and the title get a look before the request goes out. `failed` keeps
 * the form up (with the server's words) so the fix is one edit away.
 */
export type PublishPhase =
  | "idle"
  | "confirm"
  | "publishing"
  | "published"
  | "failed";

export type PublishState = {
  phase: PublishPhase;
  result: PublishResponse | null;
  error: string | null;
};

export const INITIAL_PUBLISH_STATE: PublishState = {
  phase: "idle",
  result: null,
  error: null,
};

/** Pure folds, so the machine is testable without fetch or a DOM. */
export function publishOpened(prev: PublishState): PublishState {
  // A published take never reopens: the entry exists, and a second publish
  // of the same take could only collide with itself.
  if (prev.phase === "published") return prev;
  return { ...prev, phase: "confirm", error: null };
}

export function publishCancelled(prev: PublishState): PublishState {
  if (prev.phase === "published" || prev.phase === "publishing") return prev;
  return INITIAL_PUBLISH_STATE;
}

export function publishStarted(prev: PublishState): PublishState {
  if (prev.phase === "published") return prev;
  return { ...prev, phase: "publishing", error: null };
}

export function publishSucceeded(
  prev: PublishState,
  result: PublishResponse,
): PublishState {
  return { ...prev, phase: "published", result, error: null };
}

export function publishFailed(prev: PublishState, err: unknown): PublishState {
  return {
    ...prev,
    phase: "failed",
    // Verbatim: an ingest refusal already names the window, the floor or
    // the colliding id — the whole point of passing it through.
    error: err instanceof Error ? err.message : "Could not publish the take.",
  };
}

export type TakePublishApi = {
  state: PublishState;
  open: () => void;
  cancel: () => void;
  publish: (body: PublishRequest) => Promise<PublishResponse | null>;
};

/** Own one take's publish flow. One instance per take row. */
export function useTakePublish(): TakePublishApi {
  const [state, setState] = useState<PublishState>(INITIAL_PUBLISH_STATE);

  const open = useCallback(() => setState(publishOpened), []);
  const cancel = useCallback(() => setState(publishCancelled), []);

  const publish = useCallback(async (body: PublishRequest) => {
    setState(publishStarted);
    try {
      const result = await publishTake(body);
      setState((prev) => publishSucceeded(prev, result));
      return result;
    } catch (err: unknown) {
      setState((prev) => publishFailed(prev, err));
      return null;
    }
  }, []);

  return { state, open, cancel, publish };
}

// ── Editing a take before publishing it (G3) ──────────────────────────────

/** `repainting_end` sentinel: regenerate through to the end of the take. */
export const REPAINT_TO_THE_END = -1;

/** API spec §3.3 — "bajo ≈ 0.2 para style transfer". */
export const DEFAULT_COVER_STRENGTH = 0.2;

/** The edit panel's fields. One shape for all three modes; which of them
 *  reach the wire is `buildEditRequest`'s decision, because the server
 *  refuses a parameter that belongs to another mode rather than dropping
 *  it (a wrongly-sent range would only show up as three minutes of the
 *  wrong music). */
export type EditForm = {
  mode: EditMode;
  /** Seconds into the source take. */
  start: number;
  /** Seconds, or `REPAINT_TO_THE_END`. */
  end: number;
  strength: number;
  /** Empty = reuse the take's own prompt, which the page still holds. */
  prompt: string;
};

export const INITIAL_EDIT_FORM: EditForm = {
  mode: "repaint",
  start: 0,
  end: REPAINT_TO_THE_END,
  strength: DEFAULT_COVER_STRENGTH,
  prompt: "",
};

export type EditPhase = "idle" | "editing" | "submitting" | "failed";

export type EditState = {
  phase: EditPhase;
  form: EditForm;
  error: string | null;
  /** So a 409 (VRAM) can be toned differently from a real error. */
  errorStatus: number | null;
};

export const INITIAL_EDIT_STATE: EditState = {
  phase: "idle",
  form: INITIAL_EDIT_FORM,
  error: null,
  errorStatus: null,
};

/**
 * Can this take be edited at all?
 *
 * Weaker than `canPublishTake` on purpose: publishing needs a bpm and a
 * key the ingest refuses to guess, but an edit only needs the audio — a
 * take whose `metas` failed to parse can still be repainted, and the
 * result may well come back with readable metadata.
 */
export function canEditTake(take: Take): boolean {
  return Boolean(decodedTakePath(take.file));
}

/** Pure folds, so the panel is testable without fetch or a DOM. */
export function editOpened(prev: EditState): EditState {
  if (prev.phase === "submitting") return prev;
  return { ...INITIAL_EDIT_STATE, phase: "editing" };
}

export function editCancelled(prev: EditState): EditState {
  if (prev.phase === "submitting") return prev;
  return INITIAL_EDIT_STATE;
}

export function editChanged(
  prev: EditState,
  patch: Partial<EditForm>,
): EditState {
  if (prev.phase === "submitting") return prev;
  return { ...prev, form: { ...prev.form, ...patch } };
}

export function editStarted(prev: EditState): EditState {
  return { ...prev, phase: "submitting", error: null, errorStatus: null };
}

/** The panel closes on success: the chained card is now the whole story. */
export function editSucceeded(): EditState {
  return INITIAL_EDIT_STATE;
}

export function editFailed(prev: EditState, err: unknown): EditState {
  return {
    ...prev,
    phase: "failed",
    // Verbatim, the same rule the 409 and the ingest refusals follow.
    error: err instanceof Error ? err.message : "Could not start the edit.",
    errorStatus: err instanceof GeneratorError ? err.status : null,
  };
}

/**
 * Why this repaint range cannot be sent, or null when it can.
 *
 * Mirrors the server's own refusals so the panel explains the problem
 * before a round trip, and adds the one check the backend cannot make:
 * the source take's duration is known HERE (the page persisted it) and
 * nowhere on the backend, which never re-queries the task.
 */
export function editRangeError(
  form: EditForm,
  durationSec?: number | null,
): string | null {
  if (form.mode !== "repaint") return null;
  const { start, end } = form;
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    return "Give the range in seconds.";
  }
  if (start < 0) return "The start cannot be negative.";
  if (end !== REPAINT_TO_THE_END) {
    if (end <= 0) return "Use -1 for “to the end”, or a positive second.";
    if (start >= end) return "The start has to come before the end.";
  }
  const total = typeof durationSec === "number" && durationSec > 0 ? durationSec : null;
  if (total !== null) {
    if (start >= total) {
      return `The take is ${Math.round(total)}s long — the start is past it.`;
    }
    if (end !== REPAINT_TO_THE_END && end > total) {
      return `The take is ${Math.round(total)}s long — the end is past it.`;
    }
  }
  return null;
}

export type EditOptions = {
  /** Only drives the server's bpm default, exactly as on a generation. */
  genreFolder?: string | null;
};

/**
 * Build the wire body from the take the page PERSISTED plus the panel.
 *
 * Only the parameters the chosen mode owns go out — the server treats a
 * stray one as a 422, which is the point: the request means what it says.
 * An empty prompt override falls back to the take's OWN prompt, held here
 * since the poll landed, because the backend never re-queries an old task.
 */
export function buildEditRequest(
  take: Take,
  form: EditForm,
  opts: EditOptions = {},
): EditRequest {
  const body: EditRequest = {
    file: decodedTakePath(take.file),
    mode: form.mode,
  };
  const override = form.prompt.trim();
  const inherited = (take.prompt ?? "").trim();
  if (override) body.prompt = override;
  else if (inherited) body.prompt = inherited;

  if (form.mode === "repaint") {
    body.repainting_start = form.start;
    body.repainting_end = form.end;
  } else if (form.mode === "cover") {
    body.audio_cover_strength = form.strength;
  }
  if (opts.genreFolder && opts.genreFolder.trim()) {
    body.genre_folder = opts.genreFolder.trim();
  }
  return body;
}

// ── Lineage: the chained cards an edit spawns ─────────────────────────────

/** One edit released from a take, as the page remembers it. */
export type ChainedTask = {
  task: CreateTaskResponse;
  mode: EditMode;
  /** The source as the operator knows it — its published catalog name
   *  when it has one, otherwise its label in this dialog. */
  source: string;
  /** What the card says at a glance. */
  lineage: string;
};

export function editLineage(source: string, mode: EditMode): string {
  return `edited from ${source} · ${mode}`;
}

/** The source's own name wins over its position once it is published. */
export function editSourceLabel(
  takeLabel: string,
  publishedName?: string | null,
): string {
  return (publishedName ?? "").trim() || takeLabel;
}

export function chainedTaskFor(
  task: CreateTaskResponse,
  mode: EditMode,
  source: string,
): ChainedTask {
  return { task, mode, source, lineage: editLineage(source, mode) };
}

/**
 * Append one chained card, ignoring a task id already on the chain.
 *
 * The dedupe is not defensive dressing: a double-clicked submit would
 * otherwise render two cards polling the same task, and both would show
 * the same takes with different publish state.
 */
export function chainAppended(
  prev: ChainedTask[],
  entry: ChainedTask,
): ChainedTask[] {
  if (prev.some((c) => c.task.task_id === entry.task.task_id)) return prev;
  return [...prev, entry];
}

/**
 * The `variant of` options a chained take is offered.
 *
 * The SOURCE take's published name comes first and becomes the default,
 * because an edit of a published take is another take of that same piece
 * — which is exactly what `variant_of` means to the no-repeat machinery.
 */
export function variantOptionsFor(
  sourcePublished: string | null | undefined,
  published: string[],
): string[] {
  const source = (sourcePublished ?? "").trim();
  const rest = published.filter((n) => n && n !== source);
  return source ? [source, ...rest] : rest;
}

export type TakeEditApi = {
  state: EditState;
  open: () => void;
  cancel: () => void;
  change: (patch: Partial<EditForm>) => void;
  submit: (body: EditRequest) => Promise<CreateTaskResponse | null>;
};

/** Own one take's edit panel. One instance per take row. */
export function useTakeEdit(): TakeEditApi {
  const [state, setState] = useState<EditState>(INITIAL_EDIT_STATE);

  const open = useCallback(() => setState(editOpened), []);
  const cancel = useCallback(() => setState(editCancelled), []);
  const change = useCallback(
    (patch: Partial<EditForm>) =>
      setState((prev) => editChanged(prev, patch)),
    [],
  );

  const submit = useCallback(async (body: EditRequest) => {
    setState(editStarted);
    try {
      const res = await editGeneratorTake(body);
      setState(editSucceeded);
      return res;
    } catch (err: unknown) {
      setState((prev) => editFailed(prev, err));
      return null;
    }
  }, []);

  return { state, open, cancel, change, submit };
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
