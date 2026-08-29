"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Track } from "./types";
import { streamUrl } from "./api";

/**
 * PlayerContext owns a single hidden <audio> element and exposes a tiny API
 * for driving it from any page. Only mounted once at the root layout, which
 * is what makes playback survive client-side route changes.
 */

/**
 * A track the player can play. Catalog tracks resolve their audio from
 * `streamUrl(id)`; anything that is not (yet) a catalog entry — G1's
 * ACE-Step takes, served through `/api/generator/audio` — carries its own
 * `stream_url` instead. `Track` is assignable to `Playable`, so every
 * existing call site is unchanged.
 */
export type Playable = Track & { stream_url?: string };

/** Where the audio for this item lives. */
function srcFor(track: Playable): string {
  return track.stream_url ?? streamUrl(track.id);
}

export interface PlayerState {
  currentTrack: Playable | null;
  isPlaying: boolean;
  progressSec: number;
  durationSec: number;
  volume: number;
  queue: Playable[];
}

export interface PlayerApi extends PlayerState {
  play: (track: Playable, queue?: Playable[]) => void;
  pause: () => void;
  resume: () => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  seek: (sec: number) => void;
  setVolume: (v: number) => void;
  close: () => void;
}

const PlayerContext = createContext<PlayerApi | null>(null);

export function usePlayer(): PlayerApi {
  const ctx = useContext(PlayerContext);
  if (!ctx) {
    throw new Error("usePlayer must be used inside <PlayerProvider>");
  }
  return ctx;
}

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTrack, setCurrentTrack] = useState<Playable | null>(null);
  const [queue, setQueue] = useState<Playable[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progressSec, setProgressSec] = useState(0);
  const [durationSec, setDurationSec] = useState(0);
  const [volume, setVolumeState] = useState(1);

  // Single audio element — created once on mount on the client only.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (audioRef.current) return;
    const el = new Audio();
    el.preload = "metadata";
    audioRef.current = el;
  }, []);

  // Wire up listeners. Re-attached when queue changes so `ended` knows the
  // latest queue to advance through.
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    const onTime = () => setProgressSec(el.currentTime || 0);
    const onLoaded = () => setDurationSec(el.duration || 0);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => {
      setIsPlaying(false);
      // Advance to the next track in queue, if any.
      const idx = currentTrack
        ? queue.findIndex((t) => t.id === currentTrack.id)
        : -1;
      if (idx >= 0 && idx < queue.length - 1) {
        const nxt = queue[idx + 1];
        setCurrentTrack(nxt);
        if (audioRef.current) {
          audioRef.current.src = srcFor(nxt);
          audioRef.current.play().catch(() => {});
        }
      }
    };

    el.addEventListener("timeupdate", onTime);
    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onEnded);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onEnded);
    };
  }, [currentTrack, queue]);

  const play = useCallback((track: Playable, list?: Playable[]) => {
    const el = audioRef.current;
    if (!el) return;
    setCurrentTrack(track);
    setQueue(list && list.length > 0 ? list : [track]);
    el.src = srcFor(track);
    el.currentTime = 0;
    el.play().catch(() => {
      // Swallow autoplay rejections — UI reflects state via `play`/`pause` events.
    });
  }, []);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const resume = useCallback(() => {
    audioRef.current?.play().catch(() => {});
  }, []);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el || !currentTrack) return;
    if (el.paused) el.play().catch(() => {});
    else el.pause();
  }, [currentTrack]);

  const next = useCallback(() => {
    if (!currentTrack) return;
    const idx = queue.findIndex((t) => t.id === currentTrack.id);
    if (idx >= 0 && idx < queue.length - 1) {
      play(queue[idx + 1], queue);
    }
  }, [currentTrack, queue, play]);

  const prev = useCallback(() => {
    if (!currentTrack) return;
    const idx = queue.findIndex((t) => t.id === currentTrack.id);
    if (idx > 0) {
      play(queue[idx - 1], queue);
    }
  }, [currentTrack, queue, play]);

  const seek = useCallback((sec: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.max(0, Math.min(sec, el.duration || sec));
    setProgressSec(el.currentTime);
  }, []);

  const setVolume = useCallback((v: number) => {
    const clamped = Math.max(0, Math.min(1, v));
    setVolumeState(clamped);
    if (audioRef.current) audioRef.current.volume = clamped;
  }, []);

  const close = useCallback(() => {
    const el = audioRef.current;
    if (el) {
      el.pause();
      el.removeAttribute("src");
      el.load();
    }
    setCurrentTrack(null);
    setQueue([]);
    setIsPlaying(false);
    setProgressSec(0);
    setDurationSec(0);
  }, []);

  const api = useMemo<PlayerApi>(
    () => ({
      currentTrack,
      isPlaying,
      progressSec,
      durationSec,
      volume,
      queue,
      play,
      pause,
      resume,
      toggle,
      next,
      prev,
      seek,
      setVolume,
      close,
    }),
    [
      currentTrack,
      isPlaying,
      progressSec,
      durationSec,
      volume,
      queue,
      play,
      pause,
      resume,
      toggle,
      next,
      prev,
      seek,
      setVolume,
      close,
    ],
  );

  return (
    <PlayerContext.Provider value={api}>{children}</PlayerContext.Provider>
  );
}
