"use client";
import { usePlayer } from "@/lib/player";

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function MiniPlayer() {
  const {
    currentTrack,
    isPlaying,
    progressSec,
    durationSec,
    volume,
    toggle,
    seek,
    setVolume,
    close,
  } = usePlayer();

  if (!currentTrack) return null;

  const cover = currentTrack.suno?.cover_url;
  const max = durationSec || 1;

  return (
    <div
      data-testid="mini-player"
      className="fixed bottom-0 left-0 right-0 z-40 bg-surface border-t border-border px-4 py-3 flex items-center gap-4 backdrop-blur"
    >
      {/* Artwork */}
      <div className="w-12 h-12 rounded overflow-hidden bg-[#0a0a0f] border border-border flex-shrink-0">
        {cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt={currentTrack.display_name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted text-[8px] font-pixel">
            NO ART
          </div>
        )}
      </div>

      {/* Title + meta */}
      <div className="min-w-0 max-w-xs">
        <p
          className="text-xs text-[#e2e2ff] truncate font-bold"
          data-testid="mini-player-title"
        >
          {currentTrack.display_name}
        </p>
        <p className="text-[10px] text-muted truncate">
          {currentTrack.camelot_key ?? "—"}
          {currentTrack.bpm ? ` · ${currentTrack.bpm} BPM` : ""}
        </p>
      </div>

      {/* Play / pause */}
      <button
        onClick={toggle}
        aria-label={isPlaying ? "Pause" : "Play"}
        data-testid="mini-player-toggle"
        className="w-9 h-9 rounded-full border border-neon text-neon hover:bg-neon hover:text-[#0a0a0f] transition-colors flex items-center justify-center text-sm flex-shrink-0"
      >
        {isPlaying ? "❚❚" : "▶"}
      </button>

      {/* Seek bar + times */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <span className="text-[10px] text-muted font-mono tabular-nums w-10 text-right">
          {formatTime(progressSec)}
        </span>
        <input
          type="range"
          min={0}
          max={max}
          step={0.1}
          value={Math.min(progressSec, max)}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="Seek"
          data-testid="mini-player-seek"
          className="flex-1 h-1 accent-neon cursor-pointer"
        />
        <span className="text-[10px] text-muted font-mono tabular-nums w-10">
          {formatTime(durationSec)}
        </span>
      </div>

      {/* Volume */}
      <div className="hidden sm:flex items-center gap-2">
        <span className="text-[10px] text-muted font-pixel">VOL</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          aria-label="Volume"
          className="w-20 h-1 accent-neon cursor-pointer"
        />
      </div>

      {/* Close */}
      <button
        onClick={close}
        aria-label="Close player"
        data-testid="mini-player-close"
        className="text-muted hover:text-danger text-sm flex-shrink-0"
      >
        ✕
      </button>
    </div>
  );
}
