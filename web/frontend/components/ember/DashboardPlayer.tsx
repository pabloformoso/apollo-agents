"use client";

import { useIsLiveActive } from "@/lib/live";
import { artworkFor, usePlayer } from "@/lib/player";
import { Crumb, Stripe } from "./primitives";

function clock(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const value = Math.floor(seconds);
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

/** The persistent listening dock for the product home — and for Generations,
 * where a take plays through the same bar a catalog track does. It stays
 * present even before a track is selected, so the page always has a clear
 * lower edge and the player never feels like a page-specific afterthought. */
export function DashboardPlayer() {
  const player = usePlayer();
  const liveActive = useIsLiveActive();
  const track = player.currentTrack;
  const max = player.durationSec > 0 ? player.durationSec : 1;
  const cover = artworkFor(track);
  const hasQueue = player.queue.length > 1;

  return (
    <section
      aria-label="Apollo player"
      data-testid="dashboard-player"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line2 bg-ink/95 px-4 py-3 shadow-2xl backdrop-blur-md sm:px-8"
    >
      <div className="mx-auto flex max-w-screen-2xl items-center gap-3 sm:gap-5">
        <div className="h-11 w-11 shrink-0 overflow-hidden border border-line2 bg-surf sm:h-12 sm:w-12">
          {cover ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={cover} alt="" className="h-full w-full object-cover" />
          ) : (
            <Stripe alpha={0.22} className="h-full w-full" />
          )}
        </div>

        <div className="min-w-0 w-40 shrink-0 sm:w-56">
          <p className="truncate font-display text-lg italic leading-none text-cream" data-testid="dashboard-player-title">
            {track?.display_name ?? "Nothing playing"}
          </p>
          <p className="mt-1 truncate font-mono text-[10px] uppercase tracking-mono text-mute">
            {liveActive
              ? "Live session on air"
              : track
                ? `${track.genre ?? "Apollo catalog"}${track.bpm ? ` · ${track.bpm} BPM` : ""}`
                : "Choose a track from Catalog"}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button type="button" onClick={player.prev} disabled={!track || !hasQueue || liveActive} aria-label="Previous track" className="text-cream disabled:opacity-25">⏮</button>
          <button
            type="button"
            onClick={() => track && player.toggle()}
            disabled={!track || liveActive}
            aria-label={player.isPlaying ? "Pause" : "Play"}
            data-testid="dashboard-player-toggle"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-ember text-ember transition-colors hover:bg-ember hover:text-cream disabled:opacity-30"
          >
            {player.isPlaying ? "❚❚" : "▶"}
          </button>
          <button type="button" onClick={player.next} disabled={!track || !hasQueue || liveActive} aria-label="Next track" className="text-cream disabled:opacity-25">⏭</button>
        </div>

        <div className="hidden min-w-0 flex-1 items-center gap-2 sm:flex">
          <span className="w-9 text-right font-mono text-[10px] text-mute">{clock(player.progressSec)}</span>
          <input
            type="range"
            min={0}
            max={max}
            step={0.1}
            value={Math.min(player.progressSec, max)}
            disabled={!track || liveActive}
            onChange={(event) => player.seek(Number(event.target.value))}
            aria-label="Seek"
            className="min-w-0 flex-1 accent-ember disabled:opacity-30"
          />
          <span className="w-9 font-mono text-[10px] text-mute">{clock(player.durationSec)}</span>
        </div>

        <Crumb className="ml-auto hidden sm:inline-flex" tone="ember">apollo player</Crumb>
      </div>
    </section>
  );
}
