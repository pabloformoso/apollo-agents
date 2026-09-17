"use client";

import { useEffect } from "react";
import { usePlayer } from "@/lib/player";
import { useIsLiveActive } from "@/lib/live";
import type { Track } from "@/lib/types";

function time(seconds: number) {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export function CatalogPlayer({ tracks, loading, label }: { tracks: Track[]; loading: boolean; label: string }) {
  const player = usePlayer();
  const liveActive = useIsLiveActive();
  const { updateQueue, queueSource } = player;
  useEffect(() => {
    // Browsing must not replace a queue started on another page. Once a
    // catalog track is played, results become the live queue without seeking
    // or interrupting its current song. Empty results stop auto-advance.
    if (queueSource === "catalog") updateQueue(loading ? [] : tracks);
  }, [tracks, loading, queueSource, updateQueue]);

  const ownsQueue = queueSource === "catalog";
  const index = ownsQueue ? tracks.findIndex((t) => t.id === player.currentTrack?.id) : -1;
  const hasResults = !loading && tracks.length > 0;
  const max = Number.isFinite(player.durationSec) && player.durationSec > 0 ? player.durationSec : 0;
  const blocked = liveActive || loading;

  return (
    <section aria-label="Catalog player" data-testid="catalog-player" className="fixed bottom-0 inset-x-0 z-40 border-t border-line2 bg-ink px-4 py-3 sm:px-8 shadow-lg">
      <div className="mx-auto max-w-screen-2xl flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="min-w-0 flex-1 basis-40">
          <p className="font-display italic text-lg text-cream truncate" data-testid="catalog-player-title">
            {player.currentTrack?.display_name ?? "Play the catalog"}
          </p>
          <p className="font-mono text-[10px] text-mute" data-testid="catalog-queue-summary">
            {liveActive ? "Playback unavailable during a live session" : loading ? "Loading results…" : `${label} · ${tracks.length} tracks${index >= 0 ? ` · ${index + 1} of ${tracks.length}` : ""}`}
          </p>
          {ownsQueue && player.currentTrack && index < 0 && !loading && (
            <p className="text-xs text-mute">Current song is outside these results. Next follows the results.</p>
          )}
          {!ownsQueue && player.currentTrack && (
            <p className="text-xs text-mute">Playing another queue. Play results switches to this list.</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button type="button" onClick={player.prev} disabled={blocked || !ownsQueue || index <= 0} aria-label="Previous track" className="text-cream disabled:opacity-30">⏮</button>
          <button type="button" onClick={() => player.currentTrack ? player.toggle() : hasResults && player.play(tracks[0], tracks, "catalog")} disabled={liveActive || (!player.currentTrack && !hasResults)} aria-label={player.isPlaying ? "Pause" : "Play"} className="h-10 w-10 rounded-full border border-ember text-ember disabled:opacity-30">
            {player.isPlaying ? "❚❚" : "▶"}
          </button>
          <button type="button" onClick={player.next} disabled={blocked || !ownsQueue || !player.currentTrack || !hasResults || index >= tracks.length - 1} aria-label="Next track" className="text-cream disabled:opacity-30">⏭</button>
          <button type="button" onClick={() => player.play(tracks[0], tracks, "catalog")} disabled={blocked || !hasResults} className="font-mono text-xs text-ember disabled:opacity-30">Play results</button>
        </div>
        <div className="flex items-center gap-2 basis-full md:basis-64 md:flex-1 min-w-0">
          <span className="font-mono text-xs text-mute">{time(player.progressSec)}</span>
          <input type="range" min={0} max={max || 1} step={0.1} value={Math.min(player.progressSec, max)} disabled={liveActive || !max} onChange={(e) => player.seek(Number(e.target.value))} aria-label="Seek" className="min-w-0 flex-1 accent-ember" />
          <span className="font-mono text-xs text-mute">{time(max)}</span>
        </div>
        <label className="hidden sm:flex items-center gap-2 text-xs text-mute">
          Volume
          <input type="range" min={0} max={1} step={0.01} value={player.volume} onChange={(e) => player.setVolume(Number(e.target.value))} aria-label="Volume" className="w-20 accent-ember" />
        </label>
      </div>
    </section>
  );
}
