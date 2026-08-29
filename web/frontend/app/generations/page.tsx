"use client";
/**
 * Apollo G6 — the Generations library.
 *
 * The wizard's dialog only ever knew about the batch you were watching:
 * close the tab and the history was gone, even though ACE's files were
 * still sitting on disk. This page is the other half — every generation the
 * backend recorded, newest first, with the SAME take rows the dialog
 * renders (`components/ember/GeneratorTakes`), so a take plays, scores,
 * edits and publishes here exactly as it does there.
 *
 * What the feed adds on top of a take row:
 *   - **Discard / Restore** — a take you don't want falls behind the card's
 *     "N discarded" toggle. Nothing is deleted: the flip is a state on the
 *     store, applied optimistically and rolled back verbatim if refused.
 *   - **Resume** — a `pending` card re-polls ACE. The three ways that can
 *     go stay distinct on screen, because they mean different things:
 *     `failed` is ACE's verdict, `stale` is ACE having forgotten the job
 *     (terminal, inside its 24-hour window it would have answered), and a
 *     degraded answer is Apollo not reaching the box at all — a blip, so
 *     the card stays pending and keeps its resume button.
 *
 * Pagination is a "load more" on `offset`, deliberately: an infinite
 * scroller would fight the audio player for the viewport and there is no
 * total to show progress against anyway.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getCatalog } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  discardedLabel,
  discardedTakes,
  formatCreatedAt,
  generationChips,
  generationTitle,
  isPublishedTake,
  readGeneration,
  useGenerationsFeed,
  visibleTakes,
  type Generation,
  type GenerationStatus,
  type PublishResponse,
  type StoredTake,
} from "@/lib/generator";
import type { Playable } from "@/lib/player";
import { Shell } from "@/components/ember/Shell";
import { Btn, Crumb } from "@/components/ember/primitives";
import { Banner, Spinner } from "@/components/ember/feedback";
import { TakeRow, playableFor } from "@/components/ember/GeneratorTakes";

/** The badge. `stale` is deliberately the quietest of the four — it is not
 *  a fault, just a record that aged out. */
const STATUS_CLS: Record<GenerationStatus, string> = {
  pending: "text-mute border-line2",
  done: "text-ember border-ember",
  failed: "text-warn border-warn",
  stale: "text-faint border-line2",
};

const DISCARD_TITLE =
  "Fold this take away behind the card's discarded toggle. Nothing is " +
  "deleted — the audio and the record both stay.";

const RESTORE_TITLE = "Put this take back among the card's takes.";

const RESUME_HINT =
  "Ask ACE for this batch again — its job records last 24 hours, and the " +
  "takes land here when they arrive.";

/** A take is numbered by its STORED index, not by its position in the list:
 *  the number has to survive its siblings being discarded around it. */
const takeLabel = (take: StoredTake) => `Take ${take.index + 1}`;

// ── One generation ────────────────────────────────────────────────────────

function GenerationCard({
  gen,
  genres,
  resuming,
  onResume,
  onDiscarded,
  onPublished,
}: {
  gen: Generation;
  /** Real genre folders, for the publish confirm inside a take row. */
  genres: string[];
  resuming: boolean;
  onResume: (generationId: string) => void;
  onDiscarded: (generationId: string, index: number, discarded: boolean) => void;
  onPublished: (
    generationId: string,
    index: number,
    trackId: string | null,
  ) => void;
}) {
  const [showDiscarded, setShowDiscarded] = useState(false);
  // Names published from THIS card, in publish order — the first is what a
  // second take of the same batch is offered as a variant OF, exactly as in
  // the wizard. The store keeps ids, not display names, so a name only
  // becomes an offer once this page has seen the publish that made it.
  const [publishedNames, setPublishedNames] = useState<string[]>([]);

  const read = readGeneration(gen);
  const chips = generationChips(gen);

  // Split and dress the takes in one pass, keyed on the generation itself:
  // the two lists and their playables always have to agree about which take
  // is where, and a take's `Playable` id is what the player matches on.
  const { genre, shown, hidden, shownPlayables, hiddenPlayables } = useMemo(() => {
    const folder = String(gen.request?.genre_folder ?? "").trim();
    const g = folder || genres[0] || "";
    const s = visibleTakes(gen);
    const h = discardedTakes(gen);
    const dress = (takes: StoredTake[]): Playable[] =>
      takes.map((t) => playableFor(t, gen.id, g, takeLabel(t)));
    return {
      genre: g,
      shown: s,
      hidden: h,
      shownPlayables: dress(s),
      hiddenPlayables: dress(h),
    };
  }, [gen, genres]);

  const renderRow = (
    take: StoredTake,
    i: number,
    queue: Playable[],
    discarded: boolean,
  ) => (
    <TakeRow
      key={`${gen.id}:${take.index}`}
      take={take}
      playable={queue[i]}
      queue={queue}
      genres={genres}
      defaultGenre={genre}
      publishedNames={publishedNames}
      onPublished={(displayName: string, result?: PublishResponse) => {
        setPublishedNames((prev) =>
          prev.includes(displayName) ? prev : [...prev, displayName],
        );
        onPublished(gen.id, take.index, result?.track_id ?? null);
      }}
      label={takeLabel(take)}
      depth={0}
      published={isPublishedTake(take)}
      publishedTrackId={take.published_track_id ?? null}
      actions={
        <Btn
          kind="ghost"
          onClick={() => onDiscarded(gen.id, take.index, !discarded)}
          data-testid={discarded ? "generation-restore" : "generation-discard"}
          title={discarded ? RESTORE_TITLE : DISCARD_TITLE}
          className="px-3 py-[7px] text-[11px] flex-shrink-0"
        >
          {discarded ? "Restore" : "Discard"}
        </Btn>
      }
    />
  );

  return (
    <article
      data-testid="generation-card"
      data-generation-id={gen.id}
      data-status={read.status}
      className="border border-line bg-surf p-5 flex flex-col gap-3"
    >
      <header className="flex items-start justify-between gap-5">
        <div className="min-w-0 flex-1">
          <h2
            data-testid="generation-title"
            className="font-display italic font-normal text-2xl leading-[1.15] m-0"
          >
            {generationTitle(gen)}
          </h2>
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-x-2 gap-y-1 mt-2">
              {chips.map((c) => (
                <span
                  key={c}
                  data-testid="generation-chip"
                  className="font-mono text-[10px] text-mute border border-line2 px-1.5 py-0.5"
                >
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          <span
            data-testid="generation-status"
            data-status={read.status}
            className={
              "font-mono text-[10px] uppercase tracking-mono border px-1.5 py-0.5 " +
              STATUS_CLS[read.status]
            }
          >
            {read.status}
          </span>
          <Crumb>{formatCreatedAt(gen.created_at)}</Crumb>
        </div>
      </header>

      {read.resumable && (
        <div className="flex items-center gap-3 flex-wrap">
          <Btn
            kind="ghost"
            onClick={() => onResume(gen.id)}
            disabled={resuming}
            data-testid="generation-resume"
            title={RESUME_HINT}
            className="px-3 py-[7px] text-[11px]"
          >
            {resuming ? (
              <>
                <Spinner /> Resuming
              </>
            ) : (
              "Resume"
            )}
          </Btn>
          <span className="text-[11px] text-mute leading-[1.45]">
            {RESUME_HINT}
          </span>
        </div>
      )}

      {/* A blip is quiet — the card is still pending and still resumable. */}
      {read.degraded && read.note && (
        <span
          data-testid="generation-degraded"
          className="text-[11px] text-faint leading-[1.45]"
        >
          {read.note}
        </span>
      )}

      {/* Terminal states say so once, in the store's own words. */}
      {!read.degraded && read.note && (
        <Banner tone={read.status === "failed" ? "error" : "info"}>
          <span
            data-testid="generation-note"
            className="normal-case tracking-normal font-sans text-[12px]"
          >
            {read.note}
          </span>
        </Banner>
      )}

      {shown.length > 0 && (
        <ul
          data-testid="generation-takes"
          className="list-none m-0 p-0 flex flex-col"
        >
          {shown.map((t, i) => renderRow(t, i, shownPlayables, false))}
        </ul>
      )}

      {shown.length === 0 && hidden.length === 0 && read.terminal && (
        <span className="text-[12px] text-mute leading-[1.45]">
          No takes were recorded for this one.
        </span>
      )}

      {hidden.length > 0 && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => setShowDiscarded((v) => !v)}
            aria-expanded={showDiscarded}
            data-testid="generation-discarded-toggle"
            className="self-start bg-transparent border-0 p-0 cursor-pointer font-mono text-[10px] uppercase tracking-mono text-faint hover:text-ember-text"
          >
            {showDiscarded ? "−" : "+"} {discardedLabel(hidden.length)}
          </button>
          {showDiscarded && (
            <ul
              data-testid="generation-discarded"
              className="list-none m-0 p-0 flex flex-col opacity-60"
            >
              {hidden.map((t, i) => renderRow(t, i, hiddenPlayables, true))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

// ── The feed ──────────────────────────────────────────────────────────────

function GenerationsFeed() {
  const { state, loadMore, setDiscarded, resume, resuming, notePublished } =
    useGenerationsFeed();
  const [genres, setGenres] = useState<string[]>([]);

  // The publish confirm inside a take row writes into a REAL genre folder,
  // so the list has to be the folders that exist — the same fetch the
  // wizard and the TrackPicker make.
  useEffect(() => {
    let cancelled = false;
    getCatalog()
      .then((cat) => {
        if (cancelled) return;
        setGenres(cat.genres ?? []);
      })
      .catch(() => {
        if (cancelled) return;
        setGenres([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onDiscarded = useCallback(
    (generationId: string, index: number, discarded: boolean) => {
      void setDiscarded(generationId, index, discarded);
    },
    [setDiscarded],
  );

  const onResume = useCallback(
    (generationId: string) => {
      void resume(generationId);
    },
    [resume],
  );

  const count = state.generations.length;

  return (
    <>
      <section className="px-[60px] pt-10 pb-6 border-b border-line">
        <Crumb>
          generations ·{" "}
          {state.loading
            ? "loading…"
            : `${count} recorded${state.hasMore ? "+" : ""}`}
        </Crumb>
        <h1 className="font-display italic font-normal text-[64px] leading-[0.95] tracking-display-tight m-0 mt-2">
          Generations<span className="text-ember">.</span>
        </h1>
        <p className="text-sm text-mute mt-4 max-w-[560px] leading-[1.55]">
          Everything ACE has written for you, newest first. The takes outlive
          the tab they were asked for in — play them, score them, edit them,
          and publish the keepers into the catalog.
        </p>
      </section>

      <section className="px-[60px] py-8 flex-1 flex flex-col gap-6">
        {state.error && (
          <Banner tone="error">
            <span
              data-testid="generations-error"
              className="normal-case tracking-normal font-sans text-[12px]"
            >
              {state.error}
            </span>
          </Banner>
        )}

        {state.loading ? (
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            loading…
          </p>
        ) : count === 0 ? (
          <div
            data-testid="generations-empty"
            className="border border-dashed border-line2 p-12 text-center"
          >
            <p className="text-mute text-sm mb-2">Nothing generated yet.</p>
            <p className="text-faint text-[12px] m-0">
              Generations start in the Editor, from the “Generate (ACE)” tile
              beside the track row.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            {state.generations.map((gen) => (
              <GenerationCard
                key={gen.id}
                gen={gen}
                genres={genres}
                resuming={resuming.includes(gen.id)}
                onResume={onResume}
                onDiscarded={onDiscarded}
                onPublished={notePublished}
              />
            ))}
          </div>
        )}

        {state.hasMore && (
          <Btn
            kind="ghost"
            onClick={() => void loadMore()}
            disabled={state.loadingMore}
            data-testid="generations-load-more"
            className="self-center px-4 py-[7px] text-[11px]"
          >
            {state.loadingMore ? (
              <>
                <Spinner /> Loading
              </>
            ) : (
              "Load more"
            )}
          </Btn>
        )}
      </section>
    </>
  );
}

export default function GenerationsPage() {
  const router = useRouter();
  const { user, hydrated } = useAuth();

  useEffect(() => {
    // Wait for the hydration tick before judging — `user` is null on the
    // first client render even for a signed-in operator.
    if (hydrated && !user) router.push("/login");
  }, [hydrated, user, router]);

  if (!user) return null;

  return (
    <Shell username={user.username}>
      <GenerationsFeed />
    </Shell>
  );
}
