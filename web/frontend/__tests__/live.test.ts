/**
 * Vitest unit tests for ``useLiveSession`` (web/frontend/lib/live.ts).
 *
 * The hook is exercised through ``renderHook`` with a fake WebSocket
 * implementation that lets us push messages from the test side. The
 * fake also exposes the ``send`` calls so we can assert the hook
 * forwards user commands and quit.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useLiveSession, useIsLiveActive } from "@/lib/live";

// ── Fake WebSocket ─────────────────────────────────────────────────────────
class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  readyState: number = 0;
  url: string;
  onopen: ((this: WebSocket, ev: Event) => unknown) | null = null;
  onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null;
  onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null;
  onerror: ((this: WebSocket, ev: Event) => unknown) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.lastInstance = this;
    // Simulate async open
    setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.call(this as unknown as WebSocket, new Event("open"));
    }, 0);
  }

  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.call(
      this as unknown as WebSocket,
      new CloseEvent("close"),
    );
  }
  addEventListener() {}

  // Test-side push
  pushServerEvent(payload: object) {
    const ev = { data: JSON.stringify(payload) } as MessageEvent;
    this.onmessage?.call(this as unknown as WebSocket, ev);
  }

  static lastInstance: FakeWebSocket | null = null;
}

// ── Fake Audio + AudioContext ──────────────────────────────────────────────
class FakeAudioElement {
  static nextPlayBehavior: "resolve" | "reject" = "resolve";
  static lastInstance: FakeAudioElement | null = null;

  src = "";
  currentTime = 0;
  duration = 0;
  volume = 1;
  paused = true;
  preload = "auto";
  crossOrigin: string | null = null;
  play = vi.fn(() => {
    if (FakeAudioElement.nextPlayBehavior === "reject") {
      const err = new Error("NotAllowedError: autoplay blocked") as Error & {
        name: string;
      };
      err.name = "NotAllowedError";
      return Promise.reject(err);
    }
    this.paused = false;
    return Promise.resolve();
  });
  pause = vi.fn(() => {
    this.paused = true;
  });
  load = vi.fn();
  removeAttribute = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();

  constructor() {
    FakeAudioElement.lastInstance = this;
  }
}

class FakeGainNode {
  gain = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
  };
  connect = vi.fn(() => this);
}

class FakeAudioContext {
  currentTime = 0;
  destination = {} as AudioDestinationNode;
  createMediaElementSource = vi.fn(() => ({ connect: vi.fn(() => ({ connect: vi.fn() })) }));
  createGain = vi.fn(() => new FakeGainNode());
  close = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("Audio", FakeAudioElement);
  // Provide a minimal localStorage so streamUrl() / getToken() work.
  if (!globalThis.localStorage) {
    const store: Record<string, string> = { apollo_token: "tok" };
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
  } else {
    localStorage.setItem("apollo_token", "tok");
  }
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  FakeWebSocket.lastInstance = null;
  FakeAudioElement.lastInstance = null;
  FakeAudioElement.nextPlayBehavior = "resolve";
});

async function flushOpen() {
  // Resolve the setTimeout(0) inside the FakeWebSocket constructor.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 5));
  });
}

describe("useLiveSession", () => {
  it("starts disconnected with idle state", () => {
    const { result } = renderHook(() => useLiveSession(null));
    expect(result.current.connected).toBe(false);
    expect(result.current.state).toBe("idle");
    expect(result.current.currentTrack).toBeNull();
  });

  it("opens a websocket when sessionId is provided", async () => {
    const { result } = renderHook(() => useLiveSession("sid-1"));
    await flushOpen();
    expect(FakeWebSocket.lastInstance).not.toBeNull();
    expect(FakeWebSocket.lastInstance!.url).toContain("/ws/live/sid-1");
    expect(result.current.connected).toBe(true);
  });

  it("hydrates state from an initial live_state event", async () => {
    const { result } = renderHook(() => useLiveSession("sid-2"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-2",
          playlist: [
            { id: "t1", display_name: "Track 1", bpm: 120, camelot_key: "8A" },
          ],
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: { id: "t1", display_name: "Track 1", bpm: 120, camelot_key: "8A" },
            next_track: null,
            seconds_to_crossfade: 0,
            playlist_remaining: 0,
          },
        },
      });
    });
    expect(result.current.state).toBe("playing");
    expect(result.current.currentTrack?.display_name).toBe("Track 1");
    expect(result.current.playlist).toHaveLength(1);
  });

  it("updates currentTrack on track_started", async () => {
    const { result } = renderHook(() => useLiveSession("sid-3"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: { id: "t2", display_name: "Track 2", bpm: 124 },
      });
    });
    expect(result.current.currentTrack?.id).toBe("t2");
    expect(result.current.state).toBe("playing");
  });

  it("flips state to crossfading on crossfade_triggered", async () => {
    const { result } = renderHook(() => useLiveSession("sid-4"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "crossfade_triggered",
        from_track: { id: "a", display_name: "A" },
        to_track: { id: "b", display_name: "B" },
      });
    });
    expect(result.current.state).toBe("crossfading");
  });

  it("ends the session on session_ended", async () => {
    const { result } = renderHook(() => useLiveSession("sid-5"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({ type: "session_ended" });
    });
    expect(result.current.state).toBe("ended");
  });

  it("sendCommand publishes a user_msg with the canonical text", async () => {
    const { result } = renderHook(() => useLiveSession("sid-6"));
    await flushOpen();
    act(() => {
      result.current.sendCommand({ type: "skip" });
    });
    const sent = FakeWebSocket.lastInstance!.sent;
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0])).toEqual({ type: "user_msg", text: "skip" });
    // The log should also have an entry.
    expect(result.current.log[0]).toEqual(
      expect.objectContaining({ role: "user", text: "skip" }),
    );
  });

  it("sendUserMessage trims and forwards arbitrary text", async () => {
    const { result } = renderHook(() => useLiveSession("sid-7"));
    await flushOpen();
    act(() => {
      result.current.sendUserMessage("  more groove  ");
    });
    const sent = FakeWebSocket.lastInstance!.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({ type: "user_msg", text: "more groove" });
  });

  it("quit() sends a quit message and stops audio", async () => {
    const { result } = renderHook(() => useLiveSession("sid-8"));
    await flushOpen();
    act(() => {
      result.current.quit();
    });
    const sent = FakeWebSocket.lastInstance!.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({ type: "quit" });
  });

  it("appends live_message events to the log", async () => {
    const { result } = renderHook(() => useLiveSession("sid-9"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_message",
        role: "assistant",
        content: "Crossfading now.",
      });
    });
    expect(result.current.log).toHaveLength(1);
    expect(result.current.log[0]).toEqual(
      expect.objectContaining({ role: "assistant", text: "Crossfading now." }),
    );
  });

  it("surfaces server-side errors", async () => {
    const { result } = renderHook(() => useLiveSession("sid-10"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "error",
        message: "something blew up",
      });
    });
    expect(result.current.error).toBe("something blew up");
  });

  // ── Bug-1 / Bug-2 regression — track position + nextTrack derivation ────
  it("derives currentPosition + nextTrack from playlist after track_started(A)", async () => {
    const { result } = renderHook(() => useLiveSession("sid-pos-1"));
    await flushOpen();
    const playlist = [
      { id: "A", display_name: "A", bpm: 120 },
      { id: "B", display_name: "B", bpm: 122 },
      { id: "C", display_name: "C", bpm: 124 },
      { id: "D", display_name: "D", bpm: 126 },
    ];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-pos-1",
          playlist,
          engine_state: {
            state: "idle",
            position_sec: 0,
            current_track: null,
            next_track: null,
            seconds_to_crossfade: 0,
            // Critical: the race the user hit in the browser — engine
            // playlist hasn't been hydrated yet, so this is 0 even though
            // the playlist itself is [A,B,C,D].
            playlist_remaining: 0,
          },
        },
      });
    });
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[0],
      });
    });
    expect(result.current.currentPosition).toBe(1);
    expect(result.current.playlist).toHaveLength(4);
    expect(result.current.nextTrack?.id).toBe("B");
  });

  it("yields nextTrack === null when the current track is the last one", async () => {
    const { result } = renderHook(() => useLiveSession("sid-pos-2"));
    await flushOpen();
    const playlist = [
      { id: "A", display_name: "A" },
      { id: "B", display_name: "B" },
      { id: "C", display_name: "C" },
      { id: "D", display_name: "D" },
    ];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-pos-2",
          playlist,
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: playlist[3],
            next_track: null,
            seconds_to_crossfade: 0,
            playlist_remaining: 0,
          },
        },
      });
    });
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[3],
      });
    });
    expect(result.current.currentPosition).toBe(4);
    expect(result.current.nextTrack).toBeNull();
  });

  // ── Bug-3 regression — progress bar driven by per-track elapsed time ────
  it("advances currentTrackTime as the active deck reports timeupdate ticks", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveSession("sid-time"));
      // Drive the WS open via the timer queue.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5);
      });
      const playlist = [{ id: "A", display_name: "A" }];
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: "sid-time",
            playlist,
            engine_state: {
              state: "playing",
              position_sec: 0,
              current_track: playlist[0],
              next_track: null,
              seconds_to_crossfade: 0,
              playlist_remaining: 0,
            },
          },
        });
      });
      // Trigger the load so a deck exists and is wired as active.
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "load",
          track: playlist[0],
        });
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "track_started",
          track: playlist[0],
        });
      });
      // Let any pending microtasks for play() resolve.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      // The hook reads the active deck via FakeAudioElement, which is the
      // most-recently-constructed instance (active deck = "a" by default).
      const fakeAudio = FakeAudioElement.lastInstance!;
      fakeAudio.currentTime = 5.5;
      fakeAudio.duration = 60;
      // Two ticks of the playback-pos interval (250 ms each).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      expect(result.current.currentTrackTime).toBeGreaterThan(0);
      expect(result.current.currentTrackDuration).toBe(60);
    } finally {
      vi.useRealTimers();
    }
  });

  // ── Bug-4 regression — autoplay block surfaced + recoverable ────────────
  it("flips autoplayBlocked when el.play() rejects with NotAllowedError", async () => {
    // Make the next-constructed audio element reject play().
    FakeAudioElement.nextPlayBehavior = "reject";
    const { result } = renderHook(() => useLiveSession("sid-autoplay"));
    await flushOpen();
    const playlist = [{ id: "A", display_name: "A" }];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-autoplay",
          playlist,
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: playlist[0],
            next_track: null,
            seconds_to_crossfade: 0,
            playlist_remaining: 0,
          },
        },
      });
    });
    await act(async () => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "load",
        track: playlist[0],
      });
      // Wait for the awaited play() rejection to propagate.
      await new Promise((r) => setTimeout(r, 5));
    });
    expect(result.current.autoplayBlocked).toBe(true);

    // resumePlayback must be exposed and re-attempts play() on the deck.
    FakeAudioElement.nextPlayBehavior = "resolve";
    const fakeAudio = FakeAudioElement.lastInstance!;
    const playSpy = fakeAudio.play;
    const callsBefore = playSpy.mock.calls.length;
    await act(async () => {
      result.current.resumePlayback();
      await new Promise((r) => setTimeout(r, 5));
    });
    expect(playSpy.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(result.current.autoplayBlocked).toBe(false);
  });
});

describe("useIsLiveActive", () => {
  it("flips on/off in response to the apollo:live-active CustomEvent", () => {
    const { result } = renderHook(() => useIsLiveActive());
    expect(result.current).toBe(false);
    act(() => {
      window.dispatchEvent(
        new CustomEvent("apollo:live-active", { detail: { active: true } }),
      );
    });
    expect(result.current).toBe(true);
    act(() => {
      window.dispatchEvent(
        new CustomEvent("apollo:live-active", { detail: { active: false } }),
      );
    });
    expect(result.current).toBe(false);
  });
});
