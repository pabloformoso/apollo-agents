import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import React from "react";
import { PlayerProvider, usePlayer } from "@/lib/player";
import type { Track } from "@/lib/types";

const TRACK_A: Track = {
  id: "a",
  display_name: "Alpha",
  bpm: 120,
  camelot_key: "8A",
  duration_sec: 60,
  genre: "lofi",
};

const TRACK_B: Track = {
  id: "b",
  display_name: "Bravo",
  bpm: 125,
  camelot_key: "9A",
  duration_sec: 65,
  genre: "lofi",
};

/** Shared fake replacement for HTMLAudioElement. Drives play/pause/ended
 * events synchronously so tests don't need timers. */
class FakeAudio {
  src = "";
  currentTime = 0;
  duration = 60;
  volume = 1;
  paused = true;
  preload = "metadata";
  private listeners: Record<string, Array<(...a: unknown[]) => void>> = {};

  addEventListener(name: string, fn: (...a: unknown[]) => void) {
    (this.listeners[name] ||= []).push(fn);
  }
  removeEventListener(name: string, fn: (...a: unknown[]) => void) {
    this.listeners[name] = (this.listeners[name] || []).filter((f) => f !== fn);
  }
  play() {
    this.paused = false;
    this._emit("play");
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this._emit("pause");
  }
  load() {}
  removeAttribute(_: string) {}
  fireEnded() {
    this.paused = true;
    this._emit("ended");
  }
  fireLoadedMetadata() {
    this._emit("loadedmetadata");
  }
  private _emit(name: string) {
    for (const fn of this.listeners[name] || []) fn();
  }
}

let fakeAudio: FakeAudio;

beforeEach(() => {
  fakeAudio = new FakeAudio();
  // Patch the global Audio constructor so the provider picks up our fake
  // instance the first time it instantiates one.
  vi.stubGlobal("Audio", function () {
    return fakeAudio;
  });
  // Provide a no-op localStorage so streamUrl() doesn't blow up in happy-dom.
  if (!globalThis.localStorage) {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", {
      get length() {
        return Object.keys(store).length;
      },
      clear: () => {
        for (const k of Object.keys(store)) delete store[k];
      },
      getItem: (k: string) => (k in store ? store[k] : null),
      key: (i: number) => Object.keys(store)[i] ?? null,
      removeItem: (k: string) => {
        delete store[k];
      },
      setItem: (k: string, v: string) => {
        store[k] = String(v);
      },
    });
  }
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <PlayerProvider>{children}</PlayerProvider>;
}

describe("PlayerProvider", () => {
  it("starts with no current track", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    expect(result.current.currentTrack).toBeNull();
    expect(result.current.isPlaying).toBe(false);
  });

  it("setting a track via play() updates state", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A);
    });
    expect(result.current.currentTrack?.id).toBe("a");
    expect(result.current.isPlaying).toBe(true);
    expect(fakeAudio.src).toContain("/api/tracks/a/stream");
  });

  it("pause() flips isPlaying to false", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A);
    });
    expect(result.current.isPlaying).toBe(true);
    act(() => {
      result.current.pause();
    });
    expect(result.current.isPlaying).toBe(false);
  });

  it("resume() flips isPlaying back to true after pause", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A);
    });
    act(() => {
      result.current.pause();
    });
    act(() => {
      result.current.resume();
    });
    expect(result.current.isPlaying).toBe(true);
  });

  it("ended event advances to next track in queue", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A, [TRACK_A, TRACK_B]);
    });
    expect(result.current.currentTrack?.id).toBe("a");
    act(() => {
      fakeAudio.fireEnded();
    });
    expect(result.current.currentTrack?.id).toBe("b");
    expect(fakeAudio.src).toContain("/api/tracks/b/stream");
  });

  it("ended event with no next track keeps current track", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A);
    });
    act(() => {
      fakeAudio.fireEnded();
    });
    // Single-track queue: stays on TRACK_A but isPlaying flips to false
    expect(result.current.currentTrack?.id).toBe("a");
    expect(result.current.isPlaying).toBe(false);
  });

  it("close() clears the current track", () => {
    const { result } = renderHook(() => usePlayer(), { wrapper });
    act(() => {
      result.current.play(TRACK_A);
    });
    act(() => {
      result.current.close();
    });
    expect(result.current.currentTrack).toBeNull();
    expect(result.current.isPlaying).toBe(false);
  });
});
