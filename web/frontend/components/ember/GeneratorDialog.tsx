"use client";
/**
 * Apollo G1 — ACE-Step generation dialog (the Suno surface).
 *
 * Opened from the Editor's "Generate (ACE)" tile. Same modal primitive and
 * visual voice as `TrackPicker` — the other way a track enters the set —
 * so generating material feels like a sibling of picking it.
 *
 * Two states behind one dialog:
 *   1. **The form** — prompt, lyrics, duration, language, genre, takes, and
 *      a collapsed Experimental panel (inference steps, seed, key/scale,
 *      time signature). Genres come from the catalog: ACE writes into a
 *      real genre folder, and the folder drives the server-side BPM default.
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
import { getCatalog } from "@/lib/api";
import { useGeneratorTask } from "@/lib/generator";
import { Btn, Crumb } from "./primitives";
import { Dialog } from "./Dialog";
import { Banner, Spinner } from "./feedback";
// The take row lives in its own module since G6: the generations feed
// renders exactly the same rows, and one definition is what keeps a take
// behaving identically in both frames.
import { Field, FIELD_CLS, TakeRow, playableFor } from "./GeneratorTakes";

const DURATION_MIN = 120;
const DURATION_MAX = 300;
const DURATION_DEFAULT = 180;
const BATCH_MIN = 1;
const BATCH_MAX = 8;
const BATCH_DEFAULT = 2;

/** Vocal languages ACE takes. Ignored when the lyrics box is empty. */
const LANGUAGES: ReadonlyArray<[string, string]> = [
  ["en", "English"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["it", "Italian"],
  ["pt", "Portuguese"],
  ["ja", "Japanese"],
];

const TIME_SIGNATURES = ["4/4", "3/4", "6/8", "5/4"] as const;

const LYRICS_PLACEHOLDER =
  "[Verse]\nrain on the window, tape hiss underneath\n\n[Chorus]\nstay a while longer";

function clampInt(raw: string, lo: number, hi: number, fallback: number): number {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(lo, Math.min(hi, n));
}

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

  const [genres, setGenres] = React.useState<string[] | null>(null);
  const [prompt, setPrompt] = React.useState("");
  const [lyrics, setLyrics] = React.useState("");
  const [duration, setDuration] = React.useState(String(DURATION_DEFAULT));
  const [language, setLanguage] = React.useState("en");
  const [genre, setGenre] = React.useState("");
  const [batch, setBatch] = React.useState(String(BATCH_DEFAULT));
  const [expOpen, setExpOpen] = React.useState(false);
  const [steps, setSteps] = React.useState("");
  const [seed, setSeed] = React.useState("");
  const [keyScale, setKeyScale] = React.useState("");
  const [timeSig, setTimeSig] = React.useState("");
  // Names published from THIS batch, in publish order — the first one is
  // what a second take is offered as a variant OF.
  const [publishedNames, setPublishedNames] = React.useState<string[]>([]);

  // Genres are the catalog's — ACE writes into a real genre folder, so the
  // list must be the folders that exist (same fetch TrackPicker makes).
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getCatalog()
      .then((cat) => {
        if (cancelled) return;
        const list = cat.genres ?? [];
        setGenres(list);
        const match = defaultGenre
          ? list.find(
              (g) => g.toLowerCase() === defaultGenre.trim().toLowerCase(),
            )
          : undefined;
        setGenre((prev) => prev || match || list[0] || "");
      })
      .catch(() => {
        if (cancelled) return;
        setGenres([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, defaultGenre]);

  const busy = state.phase === "submitting";
  const showForm = state.phase === "idle" || busy;
  const canSubmit = Boolean(prompt.trim()) && Boolean(genre) && !busy;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const experimental: Record<string, unknown> = {};
    if (steps.trim()) experimental.inference_steps = Number(steps);
    if (seed.trim()) experimental.seed = Number(seed);
    if (timeSig) experimental.time_signature = timeSig;
    void submit({
      prompt: prompt.trim(),
      ...(lyrics.trim() ? { lyrics } : {}),
      audio_duration: clampInt(
        duration,
        DURATION_MIN,
        DURATION_MAX,
        DURATION_DEFAULT,
      ),
      vocal_language: language,
      genre_folder: genre,
      ...(keyScale.trim() ? { key_scale: keyScale.trim() } : {}),
      batch_size: clampInt(batch, BATCH_MIN, BATCH_MAX, BATCH_DEFAULT),
      ...(Object.keys(experimental).length ? { experimental } : {}),
    });
  };

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

  // A refused submit keeps the user on the form with the server's words.
  // 409 is the VRAM protocol and 503 is "the box is off" — neither is a
  // fault the user caused, so they get a calmer tone than a real error.
  const refusalTone =
    state.errorStatus === 409
      ? "warn"
      : state.errorStatus === 503
        ? "info"
        : "error";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width="wide"
      label="Generate a track with ACE-Step"
      surfaceClassName="flex flex-col gap-4 p-5"
    >
      <div
        className="flex items-baseline justify-between"
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

      {showForm ? (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {state.error && (
            <Banner tone={refusalTone}>
              <span
                data-testid="generator-error"
                className="normal-case tracking-normal font-sans text-[12px]"
              >
                {state.error}
              </span>
            </Banner>
          )}

          <Field label="prompt">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              autoFocus
              data-testid="generator-prompt"
              placeholder="warm lofi keys, dusty tape hiss, rain on a window, slow swing"
              className={FIELD_CLS + " resize-y"}
              disabled={busy}
            />
          </Field>

          <Field
            label="lyrics"
            hint="Structure tags like [Verse] and [Chorus] guide the arrangement. Leave empty for an instrumental."
          >
            <textarea
              value={lyrics}
              onChange={(e) => setLyrics(e.target.value)}
              rows={4}
              data-testid="generator-lyrics"
              placeholder={LYRICS_PLACEHOLDER}
              className={FIELD_CLS + " resize-y font-mono text-[12px]"}
              disabled={busy}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label={`duration · ${DURATION_MIN}–${DURATION_MAX}s`}>
              <input
                type="number"
                min={DURATION_MIN}
                max={DURATION_MAX}
                step={5}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                data-testid="generator-duration"
                className={FIELD_CLS}
                disabled={busy}
              />
            </Field>

            <Field label="vocal language">
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                data-testid="generator-language"
                className={FIELD_CLS}
                disabled={busy}
              >
                {LANGUAGES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="genre folder"
              hint={
                genres !== null && genres.length === 0
                  ? "No genre folders resolved from the catalog — generation needs one to land in."
                  : genre
                    ? `BPM is left to Apollo — the server fills the centre of ${genre}'s BPM window so the take lands in range.`
                    : "The genre folder drives the BPM default the server fills in."
              }
            >
              <select
                value={genre}
                onChange={(e) => setGenre(e.target.value)}
                data-testid="generator-genre"
                className={FIELD_CLS}
                disabled={busy || genres === null || genres.length === 0}
              >
                {genres === null && <option value="">Loading genres…</option>}
                {genres !== null && genres.length === 0 && (
                  <option value="">No genres found</option>
                )}
                {(genres ?? []).map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </Field>

            <Field label={`takes · ${BATCH_MIN}–${BATCH_MAX}`}>
              <input
                type="number"
                min={BATCH_MIN}
                max={BATCH_MAX}
                step={1}
                value={batch}
                onChange={(e) => setBatch(e.target.value)}
                data-testid="generator-batch"
                className={FIELD_CLS}
                disabled={busy}
              />
            </Field>
          </div>

          {/* Experimental — collapsed by default. Nothing here is needed for
              a good take; it exists for deliberate reruns (fixed seed) and
              for pushing the model. */}
          <div className="border border-line">
            <button
              type="button"
              onClick={() => setExpOpen((v) => !v)}
              aria-expanded={expOpen}
              data-testid="generator-experimental-toggle"
              className="w-full flex items-center justify-between px-3.5 py-2.5 bg-transparent border-0 cursor-pointer text-left"
            >
              <Crumb>experimental</Crumb>
              <span className="font-mono text-[11px] text-faint">
                {expOpen ? "−" : "+"}
              </span>
            </button>
            {expOpen && (
              <div className="grid grid-cols-2 gap-4 px-3.5 pb-3.5">
                <Field label="inference steps">
                  <input
                    type="number"
                    min={1}
                    value={steps}
                    onChange={(e) => setSteps(e.target.value)}
                    data-testid="generator-inference-steps"
                    placeholder="server default"
                    className={FIELD_CLS}
                    disabled={busy}
                  />
                </Field>
                <Field label="seed">
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                    data-testid="generator-seed"
                    placeholder="random"
                    className={FIELD_CLS}
                    disabled={busy}
                  />
                </Field>
                <Field label="key / scale">
                  <input
                    value={keyScale}
                    onChange={(e) => setKeyScale(e.target.value)}
                    data-testid="generator-key-scale"
                    placeholder="e.g. A minor"
                    className={FIELD_CLS}
                    disabled={busy}
                  />
                </Field>
                <Field label="time signature">
                  <select
                    value={timeSig}
                    onChange={(e) => setTimeSig(e.target.value)}
                    data-testid="generator-time-signature"
                    className={FIELD_CLS}
                    disabled={busy}
                  >
                    <option value="">server default</option>
                    {TIME_SIGNATURES.map((ts) => (
                      <option key={ts} value={ts}>
                        {ts}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Btn
              kind="ghost"
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-[11px]"
            >
              Cancel
            </Btn>
            <Btn
              type="submit"
              disabled={!canSubmit}
              data-testid="generator-submit"
              className="px-4 py-[7px] text-[11px]"
            >
              {busy ? (
                <>
                  <Spinner /> Sending
                </>
              ) : (
                "Generate"
              )}
            </Btn>
          </div>
        </form>
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
                  genres={genres ?? []}
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
