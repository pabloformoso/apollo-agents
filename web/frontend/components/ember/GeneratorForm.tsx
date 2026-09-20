"use client";
/**
 * The ACE-Step request form — ONE definition behind two frames.
 *
 * Lifted out of `GeneratorDialog` so the Generations page can put a prompt
 * box front and centre (the Suno shape: describe a song, press Generate,
 * the song lands in the feed below) without a second copy of the fields,
 * the caption arithmetic or the genre-preset plumbing. The dialog — the
 * editor's "fill THIS slot" door — renders the `dialog` variant, which is
 * byte-for-byte the form it always had, same test ids included. The
 * `composer` variant is the same state and the same submit body in a
 * layout that leads with the description and folds the rest away.
 *
 * What the two variants share is everything that decides what ACE gets:
 * the genre preset seeds the style prompt and the BPM default, the combined
 * caption is capped at `PROMPT_MAX` without cutting anyone's words, and an
 * empty lyrics box means an instrumental.
 */
import * as React from "react";
import { getCatalog, getGeneratorGenres } from "@/lib/api";
import type { CreateTaskRequest, GeneratorGenre } from "@/lib/generator";
import { Btn, Crumb } from "./primitives";
import { Banner, Spinner } from "./feedback";
import { Field, FIELD_CLS } from "./GeneratorTakes";

export const DURATION_MIN = 120;
export const DURATION_MAX = 600;
const BPM_MIN = 30;
const BPM_MAX = 300;
const BPM_DEFAULT = 120;
export const PROMPT_MAX = 512;
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

const TIME_SIGNATURES = [["4", "4/4"], ["3", "3/4"], ["2", "2/4"], ["6", "6/8"]] as const;

const LYRICS_PLACEHOLDER =
  "[Verse]\nrain on the window, tape hiss underneath\n\n[Chorus]\nstay a while longer";

function clampInt(raw: string, lo: number, hi: number, fallback: number): number {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(lo, Math.min(hi, n));
}

export type GeneratorFormContext = {
  /** The genre folder currently selected — the takes are dressed with it. */
  genre: string;
  /** Every real genre folder, for the publish confirm inside a take row. */
  genres: string[];
};

export type GeneratorFormProps = {
  /** Load the genre lists (the dialog passes `open`; the composer `true`). */
  active: boolean;
  /** A submit is in flight. */
  busy: boolean;
  /** The composer while ACE is off or a set is on air: inert, with a reason. */
  disabled?: boolean;
  disabledReason?: string | null;
  /** The server's refusal, verbatim. */
  error?: string | null;
  errorStatus?: number | null;
  /** Preselected when it matches a real genre folder. */
  defaultGenre?: string | null;
  onSubmit: (body: CreateTaskRequest) => void;
  /** Dialog only. */
  onCancel?: () => void;
  /** The dialog's layout, or the page's. */
  variant?: "dialog" | "composer";
  /** Lets the frame know the genre and the list — the dialog dresses takes with them. */
  onContext?: (ctx: GeneratorFormContext) => void;
};

export function GeneratorForm({
  active,
  busy,
  disabled = false,
  disabledReason = null,
  error = null,
  errorStatus = null,
  defaultGenre,
  onSubmit,
  onCancel,
  variant = "dialog",
  onContext,
}: GeneratorFormProps) {
  const [genres, setGenres] = React.useState<string[] | null>(null);
  const [genreMeta, setGenreMeta] = React.useState<Record<string, GeneratorGenre>>({});
  const [prompt, setPrompt] = React.useState("");
  const [lyrics, setLyrics] = React.useState("");
  const [withLyrics, setWithLyrics] = React.useState(false);
  const [duration, setDuration] = React.useState(String(DURATION_DEFAULT));
  const [bpm, setBpm] = React.useState("");
  const [style, setStyle] = React.useState<string | null>(null);
  const [language, setLanguage] = React.useState("en");
  const [genre, setGenre] = React.useState("");
  const [batch, setBatch] = React.useState(String(BATCH_DEFAULT));
  const [expOpen, setExpOpen] = React.useState(false);
  const [steps, setSteps] = React.useState("");
  const [seed, setSeed] = React.useState("");
  const [keyScale, setKeyScale] = React.useState("");
  const [timeSig, setTimeSig] = React.useState("");
  const [useFormat, setUseFormat] = React.useState(false);

  // Include configured genres even before they have their first catalog track.
  React.useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.allSettled([getCatalog(), getGeneratorGenres()]).then(
      ([catalogResult, metadataResult]) => {
        if (cancelled) return;
        const catalogGenres =
          catalogResult.status === "fulfilled" ? catalogResult.value.genres ?? [] : [];
        const metadata =
          metadataResult.status === "fulfilled" ? metadataResult.value.genres ?? [] : [];
        const byId = Object.fromEntries(
          metadata.map((entry) => [entry.id.toLowerCase(), entry]),
        );
        setGenreMeta(byId);
        const list = [...new Map(
          [...catalogGenres, ...metadata.map((entry) => entry.id)]
            .map((name) => [name.toLowerCase(), name]),
        ).values()].sort();
        setGenres(list);
        const match = defaultGenre
          ? list.find(
              (g) => g.toLowerCase() === defaultGenre.trim().toLowerCase(),
            )
          : undefined;
        const initialGenre = match || list[0] || "";
        setGenre((prev) => prev || initialGenre);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [active, defaultGenre]);

  React.useEffect(() => {
    onContext?.({ genre, genres: genres ?? [] });
  }, [genre, genres, onContext]);

  const selectedGenre = genreMeta[genre.trim().toLowerCase()] ?? null;
  const selectedBpmDefault = selectedGenre?.bpm_default ?? BPM_DEFAULT;
  const bpmValue = bpm || String(selectedBpmDefault);
  const styleValue = style ?? selectedGenre?.style_prompt ?? "";
  const caption = [styleValue.trim(), prompt.trim()].filter(Boolean).join(". ");
  const captionLength = Array.from(caption).length;

  const inert = busy || disabled;
  const composer = variant === "composer";
  const lyricsShown = composer ? withLyrics : true;
  const canSubmit =
    Boolean(prompt.trim()) && Boolean(genre) && captionLength <= PROMPT_MAX && !inert;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const experimental: Record<string, unknown> = {};
    if (steps.trim()) experimental.inference_steps = Number(steps);
    if (seed.trim()) {
      experimental.seed = Number(seed);
      experimental.use_random_seed = false;
    }
    if (timeSig) experimental.time_signature = timeSig;
    const lyricsSent = lyricsShown && lyrics.trim() ? { lyrics } : {};
    onSubmit({
      prompt: prompt.trim(),
      style_prompt: styleValue.trim(),
      ...lyricsSent,
      audio_duration: clampInt(duration, DURATION_MIN, DURATION_MAX, DURATION_DEFAULT),
      bpm: clampInt(bpmValue, BPM_MIN, BPM_MAX, selectedBpmDefault),
      vocal_language: language,
      genre_folder: genre,
      ...(keyScale.trim() ? { key_scale: keyScale.trim() } : {}),
      batch_size: clampInt(batch, BATCH_MIN, BATCH_MAX, BATCH_DEFAULT),
      use_format: useFormat,
      ...(Object.keys(experimental).length ? { experimental } : {}),
    });
  };

  // A refused submit keeps the user on the form with the server's words.
  // 409 is the VRAM protocol and 503 is "the box is off" — neither is a
  // fault the user caused, so they get a calmer tone than a real error.
  const refusalTone = errorStatus === 409 ? "warn" : errorStatus === 503 ? "info" : "error";

  const errorBanner = error && (
    <Banner tone={refusalTone}>
      <span data-testid="generator-error" className="normal-case tracking-normal font-sans text-[12px]">
        {error}
      </span>
    </Banner>
  );

  const styleField = (
    <Field label="musical style" hint="Starts from the genre preset. Edit or clear it to choose your own sound.">
      <textarea
        value={styleValue}
        onChange={(e) => setStyle(e.target.value)}
        rows={2}
        maxLength={PROMPT_MAX}
        data-testid="generator-style"
        className={FIELD_CLS + " resize-y"}
        disabled={inert}
      />
    </Field>
  );

  const captionPreview = (
    <>
      <details className="text-xs text-mute">
        <summary className="cursor-pointer">Combined description · {captionLength}/{PROMPT_MAX}</summary>
        <p className="mt-2 whitespace-pre-wrap" data-testid="generator-caption-preview">
          {caption || "Your style and song description will appear here."}
        </p>
      </details>
      {captionLength > PROMPT_MAX && (
        <p role="alert" className="text-sm text-ember">
          Shorten the style or description by {captionLength - PROMPT_MAX} characters. Your words will not be cut off.
        </p>
      )}
    </>
  );

  const lyricsField = (
    <Field
      label="lyrics · optional"
      hint="Structure tags like [Verse] and [Chorus] guide the arrangement. Leave empty for an instrumental."
    >
      <textarea
        value={lyrics}
        onChange={(e) => setLyrics(e.target.value)}
        rows={4}
        data-testid="generator-lyrics"
        placeholder={LYRICS_PLACEHOLDER}
        className={FIELD_CLS + " resize-y font-mono text-[12px]"}
        disabled={inert}
      />
    </Field>
  );

  const durationField = (
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
        disabled={inert}
      />
    </Field>
  );

  const bpmField = (
    <Field
      label="tempo · BPM"
      hint={
        selectedGenre?.bpm_min != null && selectedGenre?.bpm_max != null
          ? `Catalog range: ${selectedGenre.bpm_min}–${selectedGenre.bpm_max} BPM. Targets outside it may need another genre when publishing.`
          : "Set a target between 30 and 300 BPM. The generated tempo may vary."
      }
    >
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={BPM_MIN}
          max={BPM_MAX}
          value={clampInt(bpmValue, BPM_MIN, BPM_MAX, selectedBpmDefault)}
          onChange={(e) => setBpm(e.target.value)}
          data-testid="generator-bpm-slider"
          aria-label="Tempo slider"
          className="accent-ember min-w-0 flex-1"
          disabled={inert}
        />
        <input
          type="number"
          min={BPM_MIN}
          max={BPM_MAX}
          value={bpmValue}
          onChange={(e) => setBpm(e.target.value)}
          data-testid="generator-bpm"
          aria-label="Tempo in BPM"
          className={FIELD_CLS + " w-20"}
          disabled={inert}
        />
      </div>
    </Field>
  );

  const languageField = (
    <Field label="vocal language">
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value)}
        data-testid="generator-language"
        className={FIELD_CLS}
        disabled={inert}
      >
        {LANGUAGES.map(([code, name]) => (
          <option key={code} value={code}>{name}</option>
        ))}
      </select>
    </Field>
  );

  const genreField = (
    <Field
      label="genre preset"
      hint={composer ? undefined : "Choosing a preset loads its style and suggested tempo. You can edit both."}
    >
      <select
        value={genre}
        onChange={(e) => {
          setGenre(e.target.value);
          setBpm("");
          setStyle(null);
        }}
        data-testid="generator-genre"
        className={FIELD_CLS}
        disabled={inert || genres === null || genres.length === 0}
      >
        {genres === null && <option value="">Loading genres…</option>}
        {genres !== null && genres.length === 0 && <option value="">No genres found</option>}
        {(genres ?? []).map((g) => (
          <option key={g} value={g}>{g}</option>
        ))}
      </select>
    </Field>
  );

  const batchField = (
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
        disabled={inert}
      />
    </Field>
  );

  const keyField = (
    <Field label="key / scale">
      <input
        value={keyScale}
        onChange={(e) => setKeyScale(e.target.value)}
        data-testid="generator-key-scale"
        placeholder="e.g. A minor"
        className={FIELD_CLS}
        disabled={inert}
      />
    </Field>
  );

  const timeSigField = (
    <Field label="time signature">
      <select
        value={timeSig}
        onChange={(e) => setTimeSig(e.target.value)}
        data-testid="generator-time-signature"
        className={FIELD_CLS}
        disabled={inert}
      >
        <option value="">Auto</option>
        {TIME_SIGNATURES.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
    </Field>
  );

  const advancedFields = (
    <>
      <label className="sm:col-span-2 flex items-center gap-2 text-[11px] text-mute">
        <input
          type="checkbox"
          checked={useFormat}
          onChange={(e) => setUseFormat(e.target.checked)}
          data-testid="generator-use-format"
          disabled={inert}
        />
        Let AI rewrite the description and lyrics (may also change musical settings)
      </label>
      <Field label="inference steps">
        <input
          type="number"
          min={1}
          value={steps}
          onChange={(e) => setSteps(e.target.value)}
          max={200}
          data-testid="generator-inference-steps"
          placeholder="server default"
          className={FIELD_CLS}
          disabled={inert}
        />
      </Field>
      <Field label="seed">
        <input
          type="number"
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          min={0}
          step={1}
          data-testid="generator-seed"
          placeholder="random"
          className={FIELD_CLS}
          disabled={inert}
        />
      </Field>
    </>
  );

  const submitButton = (
    <Btn
      type="submit"
      disabled={!canSubmit}
      data-testid="generator-submit"
      className={composer ? "px-6 py-3 font-display italic text-lg" : "px-4 py-[7px] text-[11px]"}
      title={disabled && disabledReason ? disabledReason : undefined}
    >
      {busy ? (
        <>
          <Spinner /> Sending
        </>
      ) : (
        "Generate"
      )}
    </Btn>
  );

  if (composer) {
    return (
      <form onSubmit={submit} data-testid="generator-composer" className="flex flex-col gap-4">
        {errorBanner}
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={PROMPT_MAX}
          rows={3}
          data-testid="generator-prompt"
          placeholder="Describe a song — the mood, the instruments, how it moves…"
          className="bg-transparent border-0 text-cream font-display italic text-[28px] sm:text-[34px] leading-[1.2] tracking-[-0.015em] resize-none outline-none p-0 placeholder:text-faint disabled:opacity-50"
          disabled={inert}
        />
        <div className="h-px bg-line2" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
          {genreField}
          {durationField}
          {batchField}
          <div className="col-span-2 sm:col-span-1 flex justify-end">{submitButton}</div>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <button
            type="button"
            onClick={() => setWithLyrics((v) => !v)}
            aria-expanded={withLyrics}
            data-testid="generator-lyrics-toggle"
            className="bg-transparent border-0 p-0 cursor-pointer font-mono text-[10px] uppercase tracking-mono text-mute hover:text-ember-text"
            disabled={inert}
          >
            {withLyrics ? "− instrumental instead" : "+ add lyrics"}
          </button>
          <button
            type="button"
            onClick={() => setExpOpen((v) => !v)}
            aria-expanded={expOpen}
            data-testid="generator-experimental-toggle"
            className="bg-transparent border-0 p-0 cursor-pointer font-mono text-[10px] uppercase tracking-mono text-mute hover:text-ember-text"
          >
            {expOpen ? "− style & advanced" : "+ style & advanced"}
          </button>
          <span className="font-mono text-[10px] uppercase tracking-mono text-faint">
            {captionLength}/{PROMPT_MAX}
          </span>
          {disabled && disabledReason && (
            <span data-testid="generator-composer-disabled" className="font-mono text-[10px] uppercase tracking-mono text-warn">
              {disabledReason}
            </span>
          )}
        </div>
        {withLyrics && (
          <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-4">
            {lyricsField}
            {languageField}
          </div>
        )}
        {expOpen && (
          <div className="flex flex-col gap-4 border border-line p-4">
            {styleField}
            {captionPreview}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {bpmField}
              {keyField}
              {timeSigField}
              {advancedFields}
            </div>
          </div>
        )}
      </form>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      {errorBanner}

      <div>
        <h3 className="font-display text-3xl italic">Create a song<span className="text-ember">.</span></h3>
        <p className="mt-1 text-sm text-mute">Shape the sound, set the tempo and make it yours.</p>
      </div>

      <Field label="song description">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={PROMPT_MAX}
          rows={3}
          autoFocus
          data-testid="generator-prompt"
          placeholder="Describe the mood, instruments and how the song evolves…"
          className={FIELD_CLS + " resize-y"}
          disabled={inert}
        />
      </Field>

      {styleField}
      {captionPreview}
      {lyricsField}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {durationField}
        {bpmField}
        {languageField}
        {genreField}
        {batchField}
        {keyField}
        {timeSigField}
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
          <Crumb>advanced options</Crumb>
          <span className="font-mono text-[11px] text-faint">{expOpen ? "−" : "+"}</span>
        </button>
        {expOpen && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 px-3.5 pb-3.5">{advancedFields}</div>
        )}
      </div>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Btn kind="ghost" type="button" onClick={onCancel} className="px-3 py-1.5 text-[11px]">
            Cancel
          </Btn>
        )}
        {submitButton}
      </div>
    </form>
  );
}
