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
  static instances: FakeAudioElement[] = [];

  src = "";
  currentTime = 0;
  duration = 0;
  volume = 1;
  paused = true;
  preload = "auto";
  crossOrigin: string | null = null;
  // Listener bus so the v2.5.0.1 tests can fire a real ``ended`` event.
  _listeners: Record<string, Array<(...args: unknown[]) => void>> = {};
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
  addEventListener = vi.fn(
    (type: string, cb: (...args: unknown[]) => void) => {
      (this._listeners[type] ||= []).push(cb);
    },
  );
  removeEventListener = vi.fn();

  // Test helper — fire a registered listener.
  dispatch(type: string) {
    for (const cb of this._listeners[type] || []) {
      cb();
    }
  }

  constructor() {
    FakeAudioElement.lastInstance = this;
    FakeAudioElement.instances.push(this);
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
  FakeAudioElement.instances = [];
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

  // ── v2.5.2 — dj_chat + sendRaw ─────────────────────────────────────────
  it("appends dj_chat events to the dedicated djChat feed (separate from log)", async () => {
    const { result } = renderHook(() => useLiveSession("sid-djchat"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "dj_chat",
        text: "Heard you — staying the course.",
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "dj_chat",
        text: "Lifting the energy.",
      });
    });
    expect(result.current.djChat).toHaveLength(2);
    expect(result.current.djChat[0].text).toBe("Heard you — staying the course.");
    expect(result.current.djChat[1].text).toBe("Lifting the energy.");
    // dj_chat must NOT bleed into the user/assistant command log.
    expect(result.current.log).toHaveLength(0);
  });

  it("sendRaw publishes arbitrary JSON over the WS", async () => {
    const { result } = renderHook(() => useLiveSession("sid-raw"));
    await flushOpen();
    act(() => {
      result.current.sendRaw({
        type: "perception",
        rms_db: -42.0,
        onset_density_hz: 1.5,
        voice_likelihood: null,
        timestamp_ms: 1700000000000,
      });
    });
    const sent = FakeWebSocket.lastInstance!.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({
      type: "perception",
      rms_db: -42.0,
      onset_density_hz: 1.5,
      voice_likelihood: null,
      timestamp_ms: 1700000000000,
    });
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

  // ── v2.5.0.1 — natural end-of-track must publish track_ended ────────────
  it("publishes track_ended over WS when the active deck fires 'ended'", async () => {
    const { result } = renderHook(() => useLiveSession("sid-ended"));
    await flushOpen();
    const playlist = [
      { id: "A", display_name: "A" },
      { id: "B", display_name: "B" },
    ];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-ended",
          playlist,
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: playlist[0],
            next_track: playlist[1],
            seconds_to_crossfade: 0,
            playlist_remaining: 1,
          },
        },
      });
    });
    // engine_command load must construct the deck (which registers the
    // 'ended' listener) and then track_started locks in currentTrackId.
    await act(async () => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "load",
        track: playlist[0],
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[0],
      });
      // Let the awaited play() resolve.
      await new Promise((r) => setTimeout(r, 5));
    });
    const fakeAudio = FakeAudioElement.lastInstance!;
    expect(fakeAudio).not.toBeNull();
    // Fire the natural ``ended`` event — the hook's listener should
    // forward a synthetic ``track_ended`` WS message with the current
    // track id.
    act(() => {
      fakeAudio.dispatch("ended");
    });
    const sent = FakeWebSocket.lastInstance!.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({ type: "track_ended", track_id: "A" });

    // After backend processes that, it would emit track_started for "B".
    // Verify the hook loads "B" into the active deck (sets src to its
    // stream URL).
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "stop_deck",
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "load",
        track: playlist[1],
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[1],
      });
    });
    expect(result.current.currentTrack?.id).toBe("B");
  });

  it("does not publish track_ended when the inactive deck fires 'ended'", async () => {
    // Edge case: the previously-active deck fires 'ended' AFTER a
    // crossfade has already swapped active to the other deck. The
    // listener must guard on activeDeckRef === which to avoid posting
    // a stale track_ended that the engine would process twice.
    renderHook(() => useLiveSession("sid-ended-inactive"));
    await flushOpen();
    const playlist = [
      { id: "A", display_name: "A" },
      { id: "B", display_name: "B" },
    ];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-ended-inactive",
          playlist,
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: playlist[0],
            next_track: playlist[1],
            seconds_to_crossfade: 0,
            playlist_remaining: 1,
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
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[0],
      });
      await new Promise((r) => setTimeout(r, 5));
    });
    // Crossfade flips active deck to "b".
    await act(async () => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "crossfade",
        to_track: playlist[1],
        crossfade_sec: 1,
      });
      await new Promise((r) => setTimeout(r, 5));
    });
    // The deck-A instance is the FIRST element constructed.
    const deckA = FakeAudioElement.instances[0];
    const sentBefore = FakeWebSocket.lastInstance!.sent.length;
    act(() => {
      deckA.dispatch("ended");
    });
    const sentAfter = FakeWebSocket.lastInstance!.sent
      .slice(sentBefore)
      .map((s) => JSON.parse(s));
    // No track_ended should have been posted by the inactive deck.
    expect(
      sentAfter.find((m: { type: string }) => m.type === "track_ended"),
    ).toBeUndefined();
  });

  it("loads the new track via engine_command 'load' after track_ended advances the engine", async () => {
    // Verify the full natural-end → next-track path WITHOUT any prior
    // approaching_crossfade. This is the exact failure mode the user
    // hit in v2.5.0: track 1 ends, no crossfade, no next track.
    const { result } = renderHook(() => useLiveSession("sid-flow"));
    await flushOpen();
    const playlist = [
      { id: "A", display_name: "A" },
      { id: "B", display_name: "B" },
    ];
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "live_state",
        data: {
          session_id: "sid-flow",
          playlist,
          engine_state: {
            state: "playing",
            position_sec: 0,
            current_track: playlist[0],
            next_track: playlist[1],
            seconds_to_crossfade: 0,
            playlist_remaining: 1,
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
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[0],
      });
      await new Promise((r) => setTimeout(r, 5));
    });
    // Backend processes track_ended → emits stop_deck + load + track_started
    // for B (no crossfade_triggered in between).
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_ended",
        track: playlist[0],
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "stop_deck",
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "load",
        track: playlist[1],
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: playlist[1],
      });
    });
    expect(result.current.currentTrack?.id).toBe("B");
    expect(result.current.state).toBe("playing");
  });

  // ── v2.5.2 — Bug A1 regression: live-ticking countdown ─────────────────
  it("seeds secondsToCrossfade from track_started's cf_point_sec", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cf-1"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: { id: "A", display_name: "A" },
        // 60 s track, default cf_sec=12 + 5 buffer ⇒ cf_point at 43 s.
        cf_point_sec: 43,
      });
    });
    // currentTrackTime is 0 right after track_started, so countdown is the
    // full cf_point_sec.
    expect(result.current.secondsToCrossfade).toBe(43);
  });

  it("ticks secondsToCrossfade down as the deck's currentTime advances", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveSession("sid-cf-2"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5);
      });
      const playlist = [{ id: "A", display_name: "A" }];
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: "sid-cf-2",
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
        // Construct the deck via engine_command load.
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "load",
          track: playlist[0],
        });
        // track_started carries the authoritative cf_point.
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "track_started",
          track: playlist[0],
          cf_point_sec: 30,
        });
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      // Initial countdown: currentTrackTime=0, target=30 ⇒ 30 s.
      expect(result.current.secondsToCrossfade).toBe(30);
      // Advance the deck's currentTime by 5 s and tick the playback_pos
      // interval.
      const fakeAudio = FakeAudioElement.lastInstance!;
      fakeAudio.currentTime = 5;
      fakeAudio.duration = 60;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      // currentTrackTime now 5 ⇒ countdown 30 - 5 = 25.
      expect(result.current.secondsToCrossfade).toBe(25);
      // Tick another 10 s.
      fakeAudio.currentTime = 15;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      expect(result.current.secondsToCrossfade).toBe(15);
    } finally {
      vi.useRealTimers();
    }
  });

  it("clamps secondsToCrossfade to 0 once the deck passes cf_point_sec", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveSession("sid-cf-3"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5);
      });
      const playlist = [{ id: "A", display_name: "A" }];
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: "sid-cf-3",
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
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "load",
          track: playlist[0],
        });
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "track_started",
          track: playlist[0],
          cf_point_sec: 10,
        });
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const fakeAudio = FakeAudioElement.lastInstance!;
      fakeAudio.currentTime = 25; // past cf_point
      fakeAudio.duration = 60;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      expect(result.current.secondsToCrossfade).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("approaching_crossfade refreshes cf_point_sec mid-track (extend support)", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveSession("sid-cf-4"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5);
      });
      const playlist = [
        { id: "A", display_name: "A" },
        { id: "B", display_name: "B" },
      ];
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: "sid-cf-4",
            playlist,
            engine_state: {
              state: "playing",
              position_sec: 0,
              current_track: playlist[0],
              next_track: playlist[1],
              seconds_to_crossfade: 0,
              playlist_remaining: 1,
            },
          },
        });
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "load",
          track: playlist[0],
        });
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "track_started",
          track: playlist[0],
          cf_point_sec: 43,
        });
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      // Approaching event arrives mid-track with an UPDATED cf_point_sec
      // (e.g. an extend pushed the trigger back to 53 s).
      act(() => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "approaching_crossfade",
          track: playlist[0],
          next_track: playlist[1],
          seconds_remaining: 30,
          cf_point_sec: 53,
        });
      });
      // Tick a frame so the memo re-runs.
      const fakeAudio = FakeAudioElement.lastInstance!;
      fakeAudio.currentTime = 23;
      fakeAudio.duration = 60;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      // 53 - 23 = 30 (matches the extend-bumped trigger).
      expect(result.current.secondsToCrossfade).toBe(30);
    } finally {
      vi.useRealTimers();
    }
  });

  it("falls back to seconds_remaining when an older backend omits cf_point_sec", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cf-5"));
    await flushOpen();
    // No track_started yet — only an approaching_crossfade with the
    // legacy seconds_remaining field. The hook must surface that value
    // so old backends still produce a non-zero countdown.
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "approaching_crossfade",
        seconds_remaining: 25,
      });
    });
    expect(result.current.secondsToCrossfade).toBe(25);
  });

  it("resets secondsToCrossfade to 0 on session_ended", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cf-6"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: { id: "A", display_name: "A" },
        cf_point_sec: 43,
      });
    });
    expect(result.current.secondsToCrossfade).toBe(43);
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({ type: "session_ended" });
    });
    expect(result.current.secondsToCrossfade).toBe(0);
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
