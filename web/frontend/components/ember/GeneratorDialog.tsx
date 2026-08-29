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
 */
import * as React from "react";
import { getCatalog } from "@/lib/api";
import {
  POLL_INTERVAL_MS,
  buildEditRequest,
  buildPublishRequest,
  canEditTake,
  canPublishTake,
  chainAppended,
  chainedTaskFor,
  editRangeError,
  editSourceLabel,
  suggestDisplayName,
  takeAudioUrl,
  useGeneratorTask,
  useTakeEdit,
  useTakePublish,
  variantOptionsFor,
  type ChainedTask,
  type EditMode,
  type Take,
} from "@/lib/generator";
import { usePlayer, type Playable } from "@/lib/player";
import { Btn, Crumb } from "./primitives";
import { Dialog } from "./Dialog";
import { Banner, Spinner } from "./feedback";

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

/** G3 — the three edits, in the operator's words (API spec §3.3). */
const EDIT_MODES: ReadonlyArray<[EditMode, string, string]> = [
  [
    "repaint",
    "Repaint a stretch",
    "Regenerates only the seconds you name; the rest of the take is left alone.",
  ],
  [
    "cover",
    "Cover the whole take",
    "Keeps the shape, re-performs it. Low strength stays close to the original.",
  ],
  [
    "complete",
    "Continue the take",
    "Carries the piece on from where it ends.",
  ],
];

const LYRICS_PLACEHOLDER =
  "[Verse]\nrain on the window, tape hiss underneath\n\n[Chorus]\nstay a while longer";

function clampInt(raw: string, lo: number, hi: number, fallback: number): number {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(lo, Math.min(hi, n));
}

function formatClock(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "—";
  const total = Math.max(0, Math.round(sec));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ── Small field wrappers ──────────────────────────────────────────────────

const FIELD_CLS =
  "bg-transparent border border-line2 px-3 py-2 text-ember-text font-sans " +
  "text-sm outline-none placeholder:text-faint focus:border-ember-text " +
  "disabled:opacity-50";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <Crumb>{label}</Crumb>
      {children}
      {hint && <span className="text-[11px] text-mute leading-[1.45]">{hint}</span>}
    </label>
  );
}

// ── Takes ─────────────────────────────────────────────────────────────────

function playableFor(
  take: Take,
  taskId: string,
  genre: string,
  label: string,
): Playable {
  const metas = take.metas ?? {};
  return {
    id: `ace:${taskId}:${take.index}`,
    display_name: label,
    bpm: typeof metas.bpm === "number" ? metas.bpm : null,
    // ACE reports keyscale ("C major"); the Camelot conversion is G2's job.
    camelot_key: null,
    duration_sec: typeof metas.duration === "number" ? metas.duration : null,
    genre,
    stream_url: takeAudioUrl(take.file),
  };
}

const NO_METADATA_TITLE =
  "This take came back without a BPM or a key, so the catalog would have to " +
  "guess them — and guessed metadata is how it acquired its poisoned BPMs.";

const EDIT_TITLE =
  "Repaint, cover or continue this take. The result arrives as its own card " +
  "under this one, and can be published or edited again.";

function TakeRow({
  take,
  playable,
  queue,
  genres,
  defaultGenre,
  publishedNames,
  onPublished,
  label,
  depth,
}: {
  take: Take;
  playable: Playable;
  queue: Playable[];
  /** Real genre folders — a take lands in one of them, never a new one. */
  genres: string[];
  defaultGenre: string;
  /** Names already published, offered as `variant of` (source first). */
  publishedNames: string[];
  onPublished: (displayName: string) => void;
  /** "Take 1", or "Take 1 · repaint 2" inside a chained card. */
  label: string;
  /** How many edits deep this row sits — 0 is the original batch. */
  depth: number;
}) {
  const { play, pause, currentTrack, isPlaying } = usePlayer();
  const { state: pub, open, cancel, publish } = useTakePublish();
  const {
    state: ed,
    open: openEdit,
    cancel: cancelEdit,
    change,
    submit: submitEdit,
  } = useTakeEdit();
  const active = currentTrack?.id === playable.id;
  const playingThis = active && isPlaying;
  const metas = take.metas ?? {};
  const duration = typeof metas.duration === "number" ? metas.duration : null;
  const chips: string[] = [
    metas.bpm != null ? `${metas.bpm} BPM` : "— BPM",
    metas.keyscale ? String(metas.keyscale) : "— key",
    formatClock(metas.duration),
    take.seed_value != null ? `seed ${take.seed_value}` : "seed —",
  ];

  const [name, setName] = React.useState("");
  const [genreFolder, setGenreFolder] = React.useState(defaultGenre);
  const [variantOf, setVariantOf] = React.useState("");
  /** The edits released FROM this take, in the order they were asked for. */
  const [chain, setChain] = React.useState<ChainedTask[]>([]);

  const publishable = canPublishTake(take);
  const busy = pub.phase === "publishing";
  const confirming =
    pub.phase === "confirm" || pub.phase === "publishing" || pub.phase === "failed";

  const editable = canEditTake(take);
  const editing = ed.phase !== "idle";
  const editBusy = ed.phase === "submitting";
  const rangeError = editRangeError(ed.form, duration);
  const publishedName = pub.result?.display_name ?? null;

  // Defaults are computed when the panel OPENS, not at mount: a take
  // published from an earlier row changes what this one should suggest.
  const startConfirm = () => {
    const base = publishedNames[0] ?? null;
    setName(base ?? suggestDisplayName(take.prompt));
    setGenreFolder(defaultGenre);
    setVariantOf(base ?? "");
    open();
  };

  const onPublish = async () => {
    const result = await publish(
      buildPublishRequest(take, {
        displayName: name,
        genreFolder,
        variantOf: variantOf || null,
      }),
    );
    if (result) onPublished(result.display_name);
  };

  const onEdit = async () => {
    // Read the form BEFORE awaiting: a successful submit closes the panel
    // and resets it, and the card's lineage is written from what was sent.
    const mode = ed.form.mode;
    const res = await submitEdit(
      buildEditRequest(take, ed.form, { genreFolder: defaultGenre }),
    );
    if (!res) return;
    const source = editSourceLabel(label, publishedName);
    setChain((prev) => chainAppended(prev, chainedTaskFor(res, mode, source)));
  };

  return (
    <li
      data-testid="generator-take"
      className="flex flex-col border-b border-line"
    >
      <div className="flex items-center gap-3 py-3">
        <button
          type="button"
          onClick={() => (playingThis ? pause() : play(playable, queue))}
          data-testid="generator-take-play"
          aria-label={`${playingThis ? "Pause" : "Play"} ${label}`}
          className={
            "w-9 h-9 flex-shrink-0 flex items-center justify-center border text-sm " +
            (active
              ? "border-ember text-ember"
              : "border-line2 text-ember-text hover:border-ember hover:text-ember")
          }
        >
          {playingThis ? "❚❚" : "▶"}
        </button>

        <div className="min-w-0 flex-1">
          <div className="font-display italic text-lg leading-tight">
            {label}
          </div>
          <div className="flex flex-wrap gap-x-2 gap-y-1 mt-1">
            {chips.map((c, i) => (
              <span
                key={i}
                className="font-mono text-[10px] text-mute border border-line2 px-1.5 py-0.5"
              >
                {c}
              </span>
            ))}
          </div>
          {take.result_parse_error && (
            <div className="font-mono text-[10px] text-warn mt-1">
              metadata unreadable — audio still plays
            </div>
          )}
        </div>

        {/* Edit is a sibling of Publish, and steps aside while that take
            is being written to the catalog — one take, one request. */}
        <Btn
          kind="ghost"
          onClick={openEdit}
          disabled={!editable || busy || editing}
          data-testid="generator-edit"
          title={
            editable
              ? EDIT_TITLE
              : "This take carries no audio path, so there is nothing to edit."
          }
          className="px-3 py-[7px] text-[11px] flex-shrink-0"
        >
          Edit
        </Btn>

        {pub.phase === "published" ? (
          <Btn
            kind="ghost"
            disabled
            data-testid="generator-publish"
            title="Already in the catalog."
            className="px-3 py-[7px] text-[11px] flex-shrink-0"
          >
            Published
          </Btn>
        ) : (
          <Btn
            kind="ghost"
            onClick={startConfirm}
            disabled={!publishable || pub.phase !== "idle"}
            data-testid="generator-publish"
            title={
              publishable
                ? "Add this take to the catalog."
                : NO_METADATA_TITLE
            }
            className="px-3 py-[7px] text-[11px] flex-shrink-0"
          >
            Publish to catalog
          </Btn>
        )}
      </div>

      {editing && (
        <div
          data-testid="generator-edit-panel"
          className="flex flex-col gap-3 border border-line2 p-3 mb-3"
        >
          {ed.error && (
            <Banner tone={ed.errorStatus === 409 ? "warn" : "error"}>
              <span
                data-testid="generator-edit-error"
                className="normal-case tracking-normal font-sans text-[12px]"
              >
                {ed.error}
              </span>
            </Banner>
          )}

          <Field
            label="what to change"
            hint={EDIT_MODES.find(([m]) => m === ed.form.mode)?.[2]}
          >
            <select
              value={ed.form.mode}
              onChange={(e) => change({ mode: e.target.value as EditMode })}
              data-testid="generator-edit-mode"
              className={FIELD_CLS}
              disabled={editBusy}
            >
              {EDIT_MODES.map(([value, title]) => (
                <option key={value} value={value}>
                  {title}
                </option>
              ))}
            </select>
          </Field>

          {ed.form.mode === "repaint" && (
            <div className="grid grid-cols-2 gap-3">
              <Field
                label={
                  duration
                    ? `from · second (0–${Math.floor(duration)})`
                    : "from · second"
                }
              >
                <input
                  type="number"
                  min={0}
                  max={duration ?? undefined}
                  step={1}
                  value={ed.form.start}
                  onChange={(e) => change({ start: Number(e.target.value) })}
                  data-testid="generator-edit-start"
                  className={FIELD_CLS}
                  disabled={editBusy}
                />
              </Field>
              <Field label="to · second" hint="−1 regenerates through to the end.">
                <input
                  type="number"
                  min={-1}
                  max={duration ?? undefined}
                  step={1}
                  value={ed.form.end}
                  onChange={(e) => change({ end: Number(e.target.value) })}
                  data-testid="generator-edit-end"
                  className={FIELD_CLS}
                  disabled={editBusy}
                />
              </Field>
            </div>
          )}

          {ed.form.mode === "cover" && (
            <Field
              label={`strength · ${ed.form.strength.toFixed(2)}`}
              hint="Low keeps the original close; high lets it wander."
            >
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={ed.form.strength}
                onChange={(e) => change({ strength: Number(e.target.value) })}
                data-testid="generator-edit-strength"
                className="accent-ember"
                disabled={editBusy}
              />
            </Field>
          )}

          <Field
            label="prompt override"
            hint="Leave empty to keep this take's own prompt."
          >
            <textarea
              value={ed.form.prompt}
              onChange={(e) => change({ prompt: e.target.value })}
              rows={2}
              data-testid="generator-edit-prompt"
              placeholder={take.prompt || "same style, more energy"}
              className={FIELD_CLS + " resize-y"}
              disabled={editBusy}
            />
          </Field>

          {rangeError && (
            <span
              data-testid="generator-edit-range-error"
              className="text-[11px] text-warn leading-[1.45]"
            >
              {rangeError}
            </span>
          )}

          <div className="flex justify-end gap-2">
            <Btn
              kind="ghost"
              type="button"
              onClick={cancelEdit}
              disabled={editBusy}
              data-testid="generator-edit-cancel"
              className="px-3 py-1.5 text-[11px]"
            >
              Cancel
            </Btn>
            <Btn
              type="button"
              onClick={() => void onEdit()}
              disabled={editBusy || rangeError !== null}
              data-testid="generator-edit-submit"
              className="px-4 py-[7px] text-[11px]"
            >
              {editBusy ? (
                <>
                  <Spinner /> Sending
                </>
              ) : (
                "Send the edit"
              )}
            </Btn>
          </div>
        </div>
      )}

      {confirming && (
        <div
          data-testid="generator-publish-confirm"
          className="flex flex-col gap-3 border border-line2 p-3 mb-3"
        >
          {pub.error && (
            <Banner tone="error">
              <span
                data-testid="generator-publish-error"
                className="normal-case tracking-normal font-sans text-[12px]"
              >
                {pub.error}
              </span>
            </Banner>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field
              label="display name"
              hint="Becomes the WAV's filename and the track's name in every set."
            >
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                data-testid="generator-publish-name"
                className={FIELD_CLS}
                disabled={busy}
              />
            </Field>
            <Field label="genre folder">
              <select
                value={genreFolder}
                onChange={(e) => setGenreFolder(e.target.value)}
                data-testid="generator-publish-genre"
                className={FIELD_CLS}
                disabled={busy}
              >
                {genres.length === 0 && <option value="">No genres found</option>}
                {genres.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {publishedNames.length > 0 && (
            <Field
              label="variant of"
              hint="A second take of the same piece links to the first, so the no-repeat rules treat them as one."
            >
              <select
                value={variantOf}
                onChange={(e) => setVariantOf(e.target.value)}
                data-testid="generator-publish-variant"
                className={FIELD_CLS}
                disabled={busy}
              >
                <option value="">a new piece</option>
                {publishedNames.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <div className="flex justify-end gap-2">
            <Btn
              kind="ghost"
              type="button"
              onClick={cancel}
              disabled={busy}
              data-testid="generator-publish-cancel"
              className="px-3 py-1.5 text-[11px]"
            >
              Cancel
            </Btn>
            <Btn
              type="button"
              onClick={() => void onPublish()}
              disabled={busy || !name.trim() || !genreFolder}
              data-testid="generator-publish-submit"
              className="px-4 py-[7px] text-[11px]"
            >
              {busy ? (
                <>
                  <Spinner /> Publishing
                </>
              ) : (
                "Publish"
              )}
            </Btn>
          </div>
        </div>
      )}

      {pub.phase === "published" && pub.result && (
        <div
          data-testid="generator-published"
          className="flex flex-col gap-1 border border-line2 p-3 mb-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-ember border border-ember px-1.5 py-0.5">
              {pub.result.track_id}
            </span>
            <span className="font-mono text-[10px] text-mute">
              {pub.result.camelot_key} · {pub.result.bpm} BPM
              {pub.result.variant_of ? ` · take of ${pub.result.variant_of}` : ""}
            </span>
          </div>
          <span className="text-[11px] text-mute leading-[1.45]">
            {pub.result.note}
          </span>
        </div>
      )}

      {/* The lineage IS the nesting: an edit of this take lives inside its
          row, and an edit of that one goes a level deeper still. */}
      {chain.map((chained) => (
        <ChainedTaskCard
          key={chained.task.task_id}
          chained={chained}
          genres={genres}
          defaultGenre={defaultGenre}
          publishedNames={variantOptionsFor(publishedName, publishedNames)}
          onPublished={onPublished}
          depth={depth + 1}
        />
      ))}
    </li>
  );
}

// ── Chained card: one edit, polled exactly like an original ───────────────

/**
 * An edit's task card, rendered under the take it came from.
 *
 * It is a normal generation card in every respect — same poller, same ETA
 * countdown, same degraded-blip handling — because on the backend an edit
 * IS a normal task. The only thing that makes it an edit is the lineage
 * this component prints, which lives on the page and nowhere else.
 */
function ChainedTaskCard({
  chained,
  genres,
  defaultGenre,
  publishedNames,
  onPublished,
  depth,
}: {
  chained: ChainedTask;
  genres: string[];
  defaultGenre: string;
  publishedNames: string[];
  onPublished: (displayName: string) => void;
  depth: number;
}) {
  // The task handle is adopted as the INITIAL state (the card is keyed by
  // its task id and never re-points), so polling starts without an effect.
  const { state, etaCountdown } = useGeneratorTask(
    POLL_INTERVAL_MS,
    chained.task,
  );

  const takeLabel = React.useCallback(
    (index: number) => `${chained.source} · ${chained.mode} ${index + 1}`,
    [chained.source, chained.mode],
  );

  const playables = React.useMemo(
    () =>
      state.takes.map((t, i) =>
        playableFor(
          t,
          state.taskId ?? chained.task.task_id,
          defaultGenre,
          takeLabel(i),
        ),
      ),
    [state.takes, state.taskId, chained.task.task_id, defaultGenre, takeLabel],
  );

  return (
    <div
      data-testid="generator-chained-card"
      className="border-l-2 border-line2 pl-3 mb-3 flex flex-col gap-2"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span data-testid="generator-chained-lineage">
          <Crumb tone="ember">{chained.lineage}</Crumb>
        </span>
        {state.phase === "pending" && (
          <span className="flex items-center gap-2 font-mono text-[10px] text-mute uppercase tracking-mono">
            <Spinner />
            <span data-testid="generator-chained-eta">
              {etaCountdown == null
                ? "eta unknown"
                : etaCountdown === 0
                  ? "any second now"
                  : `~${etaCountdown}s left`}
            </span>
            {state.degraded && (
              <span
                className="text-faint"
                data-testid="generator-chained-degraded"
              >
                · reconnecting
              </span>
            )}
          </span>
        )}
      </div>

      {state.phase === "failed" && state.error && (
        <Banner tone="error">
          <span
            data-testid="generator-chained-error"
            className="normal-case tracking-normal font-sans text-[12px]"
          >
            {state.error}
          </span>
        </Banner>
      )}

      {state.takes.length > 0 && (
        <ul className="list-none m-0 p-0 flex flex-col">
          {state.takes.map((t, i) => (
            <TakeRow
              key={`${state.taskId}-${t.index}-${i}`}
              take={t}
              playable={playables[i]}
              queue={playables}
              genres={genres}
              defaultGenre={defaultGenre}
              publishedNames={publishedNames}
              onPublished={onPublished}
              label={takeLabel(i)}
              depth={depth}
            />
          ))}
        </ul>
      )}
    </div>
  );
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
        {state.taskId && (
          <Crumb>task {state.taskId.slice(0, 12)}</Crumb>
        )}
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
