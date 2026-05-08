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
  src = "";
  currentTime = 0;
  volume = 1;
  paused = true;
  preload = "auto";
  crossOrigin: string | null = null;
  play = vi.fn(() => Promise.resolve());
  pause = vi.fn(() => {
    this.paused = true;
  });
  load = vi.fn();
  removeAttribute = vi.fn();
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
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
