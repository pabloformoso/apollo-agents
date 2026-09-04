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
 *   - `GET  /api/generator/engines`     → what each GPU tenant is HOLDING
 *   - `POST /api/generator/tasks`       → {task_id, queue_position, eta_seconds}
 *   - `GET  /api/generator/tasks/{id}`  → {status, takes[], eta_seconds, degraded?}
 *   - `GET  /api/generator/audio?path=` → streaming proxy
 *   - `POST /api/generator/critique`    → {passed, bands, advisory, critique}
 *
 * G6 adds the library the wizard's own state was never going to survive —
 * close the tab and the history was gone (ACE's files outlive our record):
 *   - `GET   /api/generator/generations?limit&offset`        → newest-first
 *   - `PATCH /api/generator/generations/{id}/takes/{idx}`    → discard/restore
 *   - `POST  /api/generator/generations/{id}/refresh`        → the resume lane
 * The listing is read through `generationsFromPayload`, which takes a bare
 * array or a `{generations}` envelope: the plan wrote one and the router
 * answers the other, and that difference is not worth a broken feed. The
 * refresh refuses a TERMINAL generation with a 409 naming its status, which
 * is why only a `pending` card is offered the button.
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

/** G4 — one metric's band. `min`/`max` are the EFFECTIVE band (the
 *  reference range widened by the bench's own margins) — the one that
 *  decides the verdict, so a chip can never contradict it. The raw
 *  catalog range rides along as `reference_*`. */
export type CritiqueBand = {
  min: number;
  max: number;
  reference_min: number;
  reference_max: number;
};

export type CritiqueBands = {
  centroid_hz?: CritiqueBand | null;
  tilt_db_per_oct?: CritiqueBand | null;
  advisory_lufs?: CritiqueBand | null;
};

/** G4 — what the scorer sends. `file` is the take's DECODED ACE path. */
export type CritiqueRequest = {
  file: string;
  metas: {
    bpm?: number | null;
    keyscale?: string | null;
    duration?: number | null;
  };
  /** What the take was asked to be — the half the bench knows nothing of. */
  prompt?: string;
  genre_folder: string;
};

/**
 * The score, and the read of it.
 *
 * `passed` is `null` when the bench had nothing to compare against (a genre
 * with no committed references yet) — a normal answer carrying a `note`, not
 * a failure. `critique` is `null` whenever the LLM layer was off or did not
 * answer in time. Neither ever blocks publishing.
 */
export type CritiqueResponse = {
  passed: boolean | null;
  /** The bench genre the folder resolved to ("lofi - ambient" → "lofi"). */
  reference_genre: string;
  reference_informed: {
    centroid_hz?: number | null;
    tilt_db_per_oct?: number | null;
  } | null;
  advisory: {
    lufs?: number | null;
    lra?: number | null;
    crest_db?: number | null;
  } | null;
  bands: CritiqueBands | null;
  /** The bench's own words for each out-of-band metric. */
  failures: string[];
  critique: string | null;
  note: string | null;
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

/** One GPU tenant's own account of itself. */
export interface EngineStatus {
  ace: {
    /** ACESTEP_BASE_URL is set. False means the feature is off, not broken. */
    configured: boolean;
    reachable: boolean;
    /** Resident in VRAM. The number that matters for the shared-GPU protocol. */
    loaded: boolean;
    llm_loaded: boolean;
    /** What it holds, or would load on first use. */
    model: string | null;
    lm_model: string | null;
  };
  llm: {
    configured: boolean;
    reachable: boolean;
    /** Ids reported as `state=loaded`. LISTED IS NOT LOADED. */
    loaded: string[];
    /** How many it knows about — deliberately a different number. */
    known: number;
  };
  blocked_by_live: boolean;
}

// ── Endpoints ─────────────────────────────────────────────────────────────

export const getGeneratorHealth = () =>
  gfetch<GeneratorHealth>("/generator/health");

/**
 * What ACE and the local LLM server are HOLDING, as each reports about itself.
 *
 * Different question from `health`: that one answers "can we reach ACE", this
 * one "is it resident in the shared 16 GB". A box started with `--no-init` is
 * reachable and holding nothing, which is the intended resting state and is
 * invisible from `available` alone — a confusion that cost hours twice.
 */
export const getEngineStatus = () =>
  gfetch<EngineStatus>("/generator/engines");

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

/** G4 — score one take. Read-only: it downloads the take server-side, runs
 *  the quality bench over it and (when a provider is wired) asks one LLM
 *  for a paragraph. It writes nothing and gates nothing. */
export const critiqueTake = (body: CritiqueRequest) =>
  gfetch<CritiqueResponse>("/generator/critique", {
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

// ── Scoring a take against its genre's references (G4) ────────────────────

/**
 * Can this take be scored at all?
 *
 * As weak as `canEditTake` and for the same reason: the bench measures
 * AUDIO. A take whose `metas` never parsed has no bpm and no key, which
 * stops it publishing but not being listened to — and it is exactly the
 * take an operator most wants a second opinion on.
 */
export function canScoreTake(take: Take): boolean {
  return Boolean(decodedTakePath(take.file));
}

export type ScoreOptions = {
  /** Picks which reference bands the take is compared against. */
  genreFolder: string;
};

/** Build the wire body from the take the page PERSISTED plus the form. */
export function buildCritiqueRequest(
  take: Take,
  opts: ScoreOptions,
): CritiqueRequest {
  const metas = take.metas ?? {};
  const body: CritiqueRequest = {
    file: decodedTakePath(take.file),
    metas: {},
    genre_folder: opts.genreFolder,
  };
  if (typeof metas.bpm === "number" && Number.isFinite(metas.bpm)) {
    body.metas.bpm = metas.bpm;
  }
  if (metas.keyscale && String(metas.keyscale).trim()) {
    body.metas.keyscale = String(metas.keyscale).trim();
  }
  if (typeof metas.duration === "number" && Number.isFinite(metas.duration)) {
    body.metas.duration = metas.duration;
  }
  if (take.prompt && take.prompt.trim()) body.prompt = take.prompt;
  return body;
}

/**
 * `in` / `out` are the bench's verdict for that metric; `advisory` is
 * measured-and-reported, never a failure; `unknown` is a metric the bench
 * could not measure or had no band for.
 */
export type ChipTone = "in" | "out" | "advisory" | "unknown";

export type ScoreChip = {
  key: string;
  label: string;
  /** Formatted with its unit, or "—" when the metric came back empty. */
  value: string;
  /** Formatted band, or null when there is nothing to compare against. */
  band: string | null;
  tone: ChipTone;
};

/** Where a value sits relative to its band. Pure — the whole chip fold
 *  hangs off this one comparison, so it is worth testing on its own. */
export function bandTone(
  value: number | null | undefined,
  band: CritiqueBand | null | undefined,
): "in" | "out" | "unknown" {
  if (typeof value !== "number" || !Number.isFinite(value)) return "unknown";
  if (!band || !Number.isFinite(band.min) || !Number.isFinite(band.max)) {
    return "unknown";
  }
  return value >= band.min && value <= band.max ? "in" : "out";
}

function fmtValue(
  value: number | null | undefined,
  digits: number,
  unit: string,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

function fmtBand(band: CritiqueBand | null | undefined, digits: number): string | null {
  if (!band || !Number.isFinite(band.min) || !Number.isFinite(band.max)) return null;
  return `${band.min.toFixed(digits)}–${band.max.toFixed(digits)}`;
}

/** label · digits · unit, per metric. Centroid in whole Hz — a decimal of a
 *  hertz is noise at four figures. */
const REFERENCE_METRICS: ReadonlyArray<
  [keyof CritiqueBands & string, string, number, string]
> = [
  ["centroid_hz", "centroid", 0, "Hz"],
  ["tilt_db_per_oct", "tilt", 1, "dB/oct"],
];

const ADVISORY_METRICS: ReadonlyArray<[string, string, number, string]> = [
  ["lufs", "loudness", 1, "LUFS"],
  ["lra", "range", 1, "LRA"],
  ["crest_db", "crest", 1, "dB"],
];

/**
 * Fold one score into the chips the row renders.
 *
 * Pure, and the reason the UI has no arithmetic in it: reference-informed
 * metrics carry their band and read in/out of it, advisory ones carry their
 * number and say so. A response with no verdict (no references for the
 * genre) folds to NO chips — the note is the whole answer there.
 */
export function scoreChips(res: CritiqueResponse): ScoreChip[] {
  const ri = res.reference_informed;
  const adv = res.advisory;
  if (!ri && !adv) return [];

  const chips: ScoreChip[] = [];
  for (const [key, label, digits, unit] of REFERENCE_METRICS) {
    const value = ri?.[key as keyof typeof ri] as number | null | undefined;
    const band = res.bands?.[key] ?? null;
    chips.push({
      key,
      label,
      value: fmtValue(value, digits, unit),
      band: fmtBand(band, digits),
      tone: bandTone(value, band),
    });
  }
  for (const [key, label, digits, unit] of ADVISORY_METRICS) {
    const value = adv?.[key as keyof typeof adv] as number | null | undefined;
    // Only loudness has a reference range, and even that one is advisory.
    const band = key === "lufs" ? (res.bands?.advisory_lufs ?? null) : null;
    chips.push({
      key,
      label,
      value: fmtValue(value, digits, unit),
      band: fmtBand(band, digits),
      tone: "advisory",
    });
  }
  return chips;
}

/**
 * The one-line verdict above the chips.
 *
 * Deliberately not a pass/fail badge: the bench informs, the human decides,
 * and a take that reads "outside the references" is still perfectly
 * publishable — an unusual centroid is how half the good ones sound.
 */
export function scoreVerdict(res: CritiqueResponse): string {
  if (res.passed === null) return "No reference bands for this genre yet.";
  if (res.passed) return `Sits inside the ${res.reference_genre} references.`;
  const why = res.failures.length ? `: ${res.failures.join("; ")}.` : ".";
  return `Outside the ${res.reference_genre} references${why}`;
}

/** idle → scoring → scored | failed. Re-scoring is allowed: nothing is
 *  written, and a take can be measured again after an edit. */
export type ScorePhase = "idle" | "scoring" | "scored" | "failed";

export type ScoreState = {
  phase: ScorePhase;
  result: CritiqueResponse | null;
  error: string | null;
};

export const INITIAL_SCORE_STATE: ScoreState = {
  phase: "idle",
  result: null,
  error: null,
};

/** Pure folds, so the machine is testable without fetch or a DOM. */
export function scoreStarted(prev: ScoreState): ScoreState {
  // The previous result stays on screen while a re-score is in flight —
  // blanking the panel would read as "the numbers were wrong".
  return { ...prev, phase: "scoring", error: null };
}

export function scoreSucceeded(
  prev: ScoreState,
  result: CritiqueResponse,
): ScoreState {
  return { ...prev, phase: "scored", result, error: null };
}

export function scoreFailed(prev: ScoreState, err: unknown): ScoreState {
  return {
    ...prev,
    phase: "failed",
    // Verbatim, the rule every refusal in this module follows.
    error: err instanceof Error ? err.message : "Could not score the take.",
  };
}

export type TakeScoreApi = {
  state: ScoreState;
  score: (body: CritiqueRequest) => Promise<CritiqueResponse | null>;
};

/** Own one take's score. One instance per take row. */
export function useTakeScore(): TakeScoreApi {
  const [state, setState] = useState<ScoreState>(INITIAL_SCORE_STATE);

  const score = useCallback(async (body: CritiqueRequest) => {
    setState(scoreStarted);
    try {
      const result = await critiqueTake(body);
      setState((prev) => scoreSucceeded(prev, result));
      return result;
    } catch (err: unknown) {
      setState((prev) => scoreFailed(prev, err));
      return null;
    }
  }, []);

  return { state, score };
}

// ── The generations library (G6) ──────────────────────────────────────────

/**
 * A stored generation's lifecycle.
 *
 * `stale` is TERMINAL and means something very specific: ACE **answered**
 * and said it does not know this job any more (its record window has
 * passed). It is not "the box is down" — that arrives as `pending` with
 * `degraded: true`, and the two must never be conflated on screen.
 */
export type GenerationStatus = "pending" | "done" | "failed" | "stale";

/**
 * A stored take's disposition.
 *
 * `published` is only ever written by a successful publish (the PATCH
 * refuses it), so the feed never invents one: it either sees the store's
 * value or the result of a publish it just made.
 */
export type TakeState = "fresh" | "published" | "discarded";

/** A take as the STORE returns it: the poll shape plus its disposition. */
export type StoredTake = Take & {
  state?: TakeState | null;
  published_track_id?: string | null;
  /** The store's own decode of `file`. Carried, but not used: publishing
   *  still sends `decodedTakePath(file)`, which is the same string by
   *  construction (both sides resolve it through the one validator) and
   *  keeps one rule for a take that came straight off a poll. */
  decoded_path?: string | null;
};

/**
 * The outgoing release payload as it was sent, plus `genre_folder`; an edit
 * records `task_type` and its source path here, so lineage stays queryable.
 * Every field is optional — this is a RECORD of a request, not a form, and
 * a generation from an older shape must still render.
 */
export type GenerationRequest = {
  prompt?: string | null;
  genre_folder?: string | null;
  [key: string]: unknown;
};

export type Generation = {
  id: string;
  created_at: string;
  status: GenerationStatus;
  request?: GenerationRequest | null;
  takes?: StoredTake[] | null;
  /** Set by `/refresh` when ACE could not be reached — a blip, not a verdict. */
  degraded?: boolean;
  error?: string | null;
};

/** The listing, either shape. */
export type GenerationsPayload = Generation[] | { generations?: Generation[] | null };

/**
 * One page of cards, whichever way the router spells a list.
 *
 * The plan wrote `{generations: [...]}`; the router that landed answers a
 * BARE ARRAY, the way `/api/playlists` does. Both are read here rather than
 * picked, because the difference is a spelling and the feed should not
 * break on a router that changes its mind about an envelope.
 */
export function generationsFromPayload(payload: GenerationsPayload): Generation[] {
  if (Array.isArray(payload)) return payload;
  return payload?.generations ?? [];
}

/** One "load more" worth of cards. */
export const GENERATIONS_PAGE_SIZE = 10;

export const listGenerations = async (
  limit: number = GENERATIONS_PAGE_SIZE,
  offset: number = 0,
): Promise<Generation[]> =>
  generationsFromPayload(
    await gfetch<GenerationsPayload>(
      `/generator/generations?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
    ),
  );

/**
 * Flip one take between `discarded` and `fresh`.
 *
 * The answer body is deliberately ignored: the feed has already applied the
 * flip optimistically, and the authoritative reconciliation is the next
 * list fetch. What matters here is only whether the store took it.
 */
export async function setTakeState(
  generationId: string,
  index: number,
  state: Exclude<TakeState, "published">,
): Promise<void> {
  await gfetch<unknown>(
    `/generator/generations/${encodeURIComponent(generationId)}/takes/${encodeURIComponent(index)}`,
    { method: "PATCH", body: JSON.stringify({ state }) },
  );
}

/** Re-poll ACE for a `pending` generation — the resume lane. */
export const refreshGeneration = (generationId: string) =>
  gfetch<Generation>(
    `/generator/generations/${encodeURIComponent(generationId)}/refresh`,
    { method: "POST" },
  );

// ── Folds over the feed ───────────────────────────────────────────────────

/** Undated rows sort last rather than crashing the comparator. */
function createdAtMs(gen: Generation): number {
  const t = Date.parse(String(gen?.created_at ?? ""));
  return Number.isFinite(t) ? t : Number.NEGATIVE_INFINITY;
}

/**
 * Merge a freshly-fetched page into the feed, newest-first.
 *
 * Deduped by id with the INCOMING row winning — a later fetch is by
 * definition the fresher read of a generation that may have moved from
 * `pending` to `done` since the page was first seen. Sorting is by
 * `created_at` rather than by arrival, so a "load more" that overlaps the
 * first page (new work landed while the feed was open) cannot interleave
 * older cards above newer ones.
 */
export function generationsMerged(
  prev: Generation[],
  incoming: Generation[],
): Generation[] {
  const byId = new Map<string, Generation>();
  for (const g of prev ?? []) if (g?.id) byId.set(g.id, g);
  for (const g of incoming ?? []) if (g?.id) byId.set(g.id, g);
  return [...byId.values()].sort((a, b) => {
    const ta = createdAtMs(a);
    const tb = createdAtMs(b);
    // Equal (both dated the same, or both undated) keeps insertion order —
    // Array.sort is stable, so the server's own ordering survives.
    return ta === tb ? 0 : tb - ta;
  });
}

/**
 * Replace one generation in place, by id.
 *
 * Position is kept deliberately: a refresh does not change `created_at`, so
 * re-sorting could only make the card the operator just clicked jump under
 * their cursor. An id the feed does not hold is ignored — identity out, so
 * a late answer for a card that has since scrolled out of the list cannot
 * resurrect it.
 */
export function generationReplaced(
  prev: Generation[],
  updated: Generation,
): Generation[] {
  if (!updated?.id) return prev;
  let found = false;
  const next = prev.map((g) => {
    if (g.id !== updated.id) return g;
    found = true;
    return updated;
  });
  return found ? next : prev;
}

/** A missing/unknown `state` reads as `fresh` — the store's default. */
export function takeStateOf(take: StoredTake): TakeState {
  const s = take?.state;
  return s === "published" || s === "discarded" ? s : "fresh";
}

/**
 * Set one take's state, optimistically.
 *
 * Identity when the generation or the take is not in the list, so a stale
 * click (a card refreshed out from under it) cannot rewrite anything. Pass
 * `trackId` only when the publish that produced this flip returned one:
 * `undefined` leaves whatever the store already knew alone.
 */
export function takeStateSet(
  prev: Generation[],
  generationId: string,
  index: number,
  state: TakeState,
  trackId?: string | null,
): Generation[] {
  let touched = false;
  const next = prev.map((gen) => {
    if (gen.id !== generationId) return gen;
    let hit = false;
    const takes = (gen.takes ?? []).map((t) => {
      if (t.index !== index) return t;
      hit = true;
      return {
        ...t,
        state,
        ...(trackId === undefined ? {} : { published_track_id: trackId }),
      };
    });
    if (!hit) return gen;
    touched = true;
    return { ...gen, takes };
  });
  return touched ? next : prev;
}

/** The takes a card shows without being asked. */
export function visibleTakes(gen: Generation): StoredTake[] {
  return (gen.takes ?? []).filter((t) => takeStateOf(t) !== "discarded");
}

/** The takes behind the card's "N discarded" toggle. */
export function discardedTakes(gen: Generation): StoredTake[] {
  return (gen.takes ?? []).filter((t) => takeStateOf(t) === "discarded");
}

export function discardedLabel(count: number): string {
  return `${count} discarded`;
}

export function isPublishedTake(take: StoredTake): boolean {
  return takeStateOf(take) === "published" || Boolean(take?.published_track_id);
}

/** ACE answered, and no longer knows the job. Terminal, and not a fault. */
export const STALE_NOTE =
  "ACE no longer has a record of this job — its 24-hour window has passed. " +
  "Whatever it wrote is still on disk, but this card cannot be resumed.";

/** The box could not be reached. Still pending, still resumable. */
export const DEGRADED_NOTE =
  "Could not reach ACE just now, so this is still pending — try resuming " +
  "again in a moment.";

export const FAILED_NOTE = "ACE reported this one as failed.";

/**
 * What the card should say and offer.
 *
 * The three refusals stay distinct on purpose: `failed` is ACE's verdict,
 * `stale` is ACE forgetting, and `degraded` is Apollo not reaching ACE at
 * all. Only the last leaves the resume action on the card.
 */
export type GenerationRead = {
  status: GenerationStatus;
  /** Offer "resume"? Only a pending generation can be re-polled. */
  resumable: boolean;
  /** The last refresh could not reach ACE. Rendered quietly — it is a blip. */
  degraded: boolean;
  /** One line under the badge, or null when the badge says it all. */
  note: string | null;
  /** Nothing more happens to this generation on its own. */
  terminal: boolean;
};

export function readGeneration(gen: Generation): GenerationRead {
  switch (gen?.status) {
    case "done":
      return {
        status: "done",
        resumable: false,
        degraded: false,
        note: null,
        terminal: true,
      };
    case "failed":
      return {
        status: "failed",
        resumable: false,
        degraded: false,
        // Verbatim when ACE said why — the rule every refusal here follows.
        note: (gen.error ?? "").trim() || FAILED_NOTE,
        terminal: true,
      };
    case "stale":
      return {
        status: "stale",
        resumable: false,
        degraded: false,
        note: STALE_NOTE,
        terminal: true,
      };
    default: {
      const degraded = Boolean(gen?.degraded);
      return {
        status: "pending",
        resumable: true,
        degraded,
        note: degraded ? DEGRADED_NOTE : null,
        terminal: false,
      };
    }
  }
}

const MAX_CARD_TITLE = 90;

/** The prompt is the card's title — it is what the operator asked for. */
export function generationTitle(gen: Generation): string {
  const prompt = String(gen?.request?.prompt ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!prompt) return "Untitled generation";
  return prompt.length > MAX_CARD_TITLE
    ? `${prompt.slice(0, MAX_CARD_TITLE - 1).trimEnd()}…`
    : prompt;
}

function chipText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function chipNumber(value: unknown): number | null {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

/**
 * The request, read back as chips.
 *
 * Only fields that were actually recorded appear: the store keeps the
 * payload as it went out, and a generation from before a field existed
 * must render as the shorter row rather than as a row of blanks.
 */
export function generationChips(gen: Generation): string[] {
  const req = gen?.request ?? {};
  const chips: string[] = [];
  const genre = chipText(req.genre_folder);
  if (genre) chips.push(genre);
  // An edit records what kind it was; a plain generation has no task_type.
  const taskType = chipText(req.task_type);
  if (taskType) chips.push(taskType);
  const duration = chipNumber(req.audio_duration);
  if (duration !== null) chips.push(`${Math.round(duration)}s`);
  const bpm = chipNumber(req.bpm);
  if (bpm !== null) chips.push(`${Math.round(bpm)} BPM`);
  const keyScale = chipText(req.key_scale);
  if (keyScale) chips.push(keyScale);
  const batch = chipNumber(req.batch_size);
  if (batch !== null) {
    const n = Math.round(batch);
    chips.push(`${n} take${n === 1 ? "" : "s"}`);
  }
  const language = chipText(req.vocal_language);
  if (language) chips.push(language);
  return chips;
}

/**
 * Absolute local time, not "3 hours ago".
 *
 * A feed left open in a tab would keep a relative label frozen at whatever
 * it said on mount, and the one question this line answers — which of two
 * cards came first — is answered better by the clock anyway.
 */
export function formatCreatedAt(iso: string | null | undefined): string {
  const t = Date.parse(String(iso ?? ""));
  if (!Number.isFinite(t)) return "—";
  return new Date(t).toLocaleString();
}

/** A short page means the end of the feed — there is no total to compare. */
export function hasMorePages(received: number, limit: number): boolean {
  return limit > 0 && received >= limit;
}

// ── Feed state ────────────────────────────────────────────────────────────

export type FeedState = {
  generations: Generation[];
  /** The first load. The page shows a line, not an empty state. */
  loading: boolean;
  /** A "load more" is in flight. */
  loadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  /** How many rows have been REQUESTED — the next page's offset. */
  offset: number;
};

export const INITIAL_FEED_STATE: FeedState = {
  generations: [],
  loading: true,
  loadingMore: false,
  error: null,
  hasMore: false,
  offset: 0,
};

/** Pure folds, so the feed is testable without fetch or a DOM. */
export function feedLanded(
  prev: FeedState,
  incoming: Generation[],
  pageSize: number,
): FeedState {
  const list = incoming ?? [];
  return {
    generations: generationsMerged(prev.generations, list),
    loading: false,
    loadingMore: false,
    error: null,
    hasMore: hasMorePages(list.length, pageSize),
    // Advance by what the SERVER sent, not by what the merge kept: the
    // offset addresses rows in the store, and a duplicate still occupied one.
    offset: prev.offset + list.length,
  };
}

export function feedLoadingMore(prev: FeedState): FeedState {
  if (prev.loading || prev.loadingMore || !prev.hasMore) return prev;
  return { ...prev, loadingMore: true, error: null };
}

export function feedFailed(prev: FeedState, err: unknown): FeedState {
  return {
    ...prev,
    loading: false,
    loadingMore: false,
    // Verbatim, the rule every refusal in this module follows.
    error:
      err instanceof Error && err.message
        ? err.message
        : "Could not load the generations.",
  };
}

export type GenerationsFeedApi = {
  state: FeedState;
  /** Fetch the next page. No-op while one is in flight or at the end. */
  loadMore: () => Promise<void>;
  /** Optimistic, then PATCHed; rolled back with the server's words on a refusal. */
  setDiscarded: (
    generationId: string,
    index: number,
    discarded: boolean,
  ) => Promise<void>;
  /** Re-poll a pending generation and reconcile the card. */
  resume: (generationId: string) => Promise<void>;
  /** Ids with a refresh in flight. */
  resuming: string[];
  /** A publish landed: mark the take, keep the id it came back with. */
  notePublished: (
    generationId: string,
    index: number,
    trackId: string | null,
  ) => void;
};

/**
 * Own the feed: first page on mount, "load more" on demand, and the two
 * writes a card can make (discard/restore, resume).
 *
 * The mount fetch only ever calls `setState` from its own async callbacks —
 * the same shape as `useGeneratorTask`'s poll effect — so the loading flag
 * lives in the INITIAL state instead of being set from inside the effect.
 */
export function useGenerationsFeed(
  pageSize: number = GENERATIONS_PAGE_SIZE,
): GenerationsFeedApi {
  const [state, setState] = useState<FeedState>(INITIAL_FEED_STATE);
  const [resuming, setResuming] = useState<string[]>([]);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    listGenerations(pageSize, 0)
      .then((rows) => {
        if (cancelled) return;
        setState((prev) => feedLanded(prev, rows, pageSize));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState((prev) => feedFailed(prev, err));
      });
    return () => {
      cancelled = true;
    };
  }, [pageSize]);

  const { offset, hasMore, loading, loadingMore } = state;
  const loadMore = useCallback(async () => {
    // The rendered flags cannot stop a second click in the same tick — the
    // button only goes disabled on the next render — and a double fetch
    // would advance the offset twice and SKIP a page, so the ref is the
    // real guard and the flags are the readable one.
    if (inFlight.current || loading || loadingMore || !hasMore) return;
    inFlight.current = true;
    setState(feedLoadingMore);
    try {
      const rows = await listGenerations(pageSize, offset);
      setState((prev) => feedLanded(prev, rows, pageSize));
    } catch (err: unknown) {
      setState((prev) => feedFailed(prev, err));
    } finally {
      inFlight.current = false;
    }
  }, [pageSize, offset, hasMore, loading, loadingMore]);

  const setDiscarded = useCallback(
    async (generationId: string, index: number, discarded: boolean) => {
      const next: Exclude<TakeState, "published"> = discarded
        ? "discarded"
        : "fresh";
      const back: Exclude<TakeState, "published"> = discarded
        ? "fresh"
        : "discarded";
      setState((prev) => ({
        ...prev,
        error: null,
        generations: takeStateSet(prev.generations, generationId, index, next),
      }));
      try {
        await setTakeState(generationId, index, next);
      } catch (err: unknown) {
        // Put it back exactly where it was and say why — a row that stayed
        // hidden after a refused PATCH would be a lie about the store.
        setState((prev) => ({
          ...feedFailed(prev, err),
          generations: takeStateSet(prev.generations, generationId, index, back),
        }));
      }
    },
    [],
  );

  const resume = useCallback(async (generationId: string) => {
    setResuming((prev) =>
      prev.includes(generationId) ? prev : [...prev, generationId],
    );
    try {
      const updated = await refreshGeneration(generationId);
      setState((prev) => ({
        ...prev,
        error: null,
        // The id is filled in from the request when the answer omits it:
        // the card that was clicked is the card that must reconcile.
        generations: generationReplaced(prev.generations, {
          ...updated,
          id: updated?.id || generationId,
        }),
      }));
    } catch (err: unknown) {
      setState((prev) => feedFailed(prev, err));
    } finally {
      setResuming((prev) => prev.filter((id) => id !== generationId));
    }
  }, []);

  const notePublished = useCallback(
    (generationId: string, index: number, trackId: string | null) => {
      setState((prev) => ({
        ...prev,
        generations: takeStateSet(
          prev.generations,
          generationId,
          index,
          "published",
          trackId,
        ),
      }));
    },
    [],
  );

  return { state, loadMore, setDiscarded, resume, resuming, notePublished };
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
