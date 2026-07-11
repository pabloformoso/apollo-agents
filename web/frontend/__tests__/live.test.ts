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

import {
  buildEqualPowerCurve,
  useIsLiveActive,
  useLiveSession,
  type PhaseLockPayload,
} from "@/lib/live";

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
  close(code?: number) {
    this.readyState = 3;
    // jsdom's ``CloseEvent`` constructor in our test env does not
    // honour the ``code`` init field (always reads back as 0), which
    // breaks the v2.7.3 reconnect logic that branches on
    // ``event.code === 4001``. Hand the production handler a plain
    // object — its only contract is reading ``event.code``.
    this.onclose?.call(this as unknown as WebSocket, {
      code: code ?? 1000,
      reason: "",
      wasClean: code == null || code === 1000,
    } as unknown as CloseEvent);
  }
  /**
   * v2.7.3 — test-side helper to simulate a server-initiated close
   * (vs cleanup-initiated). Production code never calls this; tests
   * use it to drive the reconnect loop with specific close codes
   * (1006 = abnormal / triggers retry, 4001 = displaced / no retry).
   */
  triggerClose(code: number) {
    this.close(code);
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
// v3.4 — substrate moved from HTMLAudioElement + MediaElementAudioSourceNode
// to AudioBufferSourceNode. The new mocks below mirror the Web Audio
// spec surface area the live hook actually exercises. The "deck" no
// longer has DOM-element flags like paused / muted / readyState — its
// state is { source: AudioBufferSourceNode | null, gain, filter,
// startedAt, offset, rate, trackId } owned by BufferDeck in
// audio_buffer_decks.ts. Tests assert against source.start(when, offset),
// source.playbackRate.value, and the gain/filter automation calls.

class FakeAudioBuffer {
  constructor(public duration: number = 240) {}
}

class FakeBufferSource {
  static instances: FakeBufferSource[] = [];
  /** Test knob — when set to "throw", the NEXT start() call raises a
   * NotAllowedError. Auto-resets after one fire so subsequent sources
   * play normally without manual cleanup. Mirrors the prior
   * FakeAudioElement.nextPlayBehavior pattern. */
  static nextStartBehavior: "resolve" | "throw" = "resolve";

  buffer: AudioBuffer | null = null;
  playbackRate = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
  };
  onended: (() => void) | null = null;
  start = vi.fn(() => {
    if (FakeBufferSource.nextStartBehavior === "throw") {
      FakeBufferSource.nextStartBehavior = "resolve";
      const err = new Error("autoplay blocked") as Error & { name: string };
      err.name = "NotAllowedError";
      throw err;
    }
  });
  stop = vi.fn();
  connect = vi.fn(() => this);
  disconnect = vi.fn();
  constructor() {
    FakeBufferSource.instances.push(this);
  }
  /** Test helper — fire the wrapped onended (post-BufferDeck-wrap). */
  endNaturally() {
    if (this.onended) this.onended();
  }
}

class FakeGainNode {
  static instances: FakeGainNode[] = [];
  gain = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    // v3.0 — equal-power phase-lock curves go through this method
    // instead of linearRampToValueAtTime.
    setValueCurveAtTime: vi.fn(),
  };
  connect = vi.fn(() => this);
  constructor() {
    FakeGainNode.instances.push(this);
  }
}

class FakeBiquadFilterNode {
  static instances: FakeBiquadFilterNode[] = [];
  type = "highpass";
  Q = { value: 0.7 };
  frequency = {
    value: 20,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
  };
  connect = vi.fn(() => this);
  constructor() {
    FakeBiquadFilterNode.instances.push(this);
  }
}

// Shared mutable for the FakeAudioContext.currentTime getter — tests
// bump this to simulate the audio clock advancing (the spec-defined
// way the renderer's clock moves; we can't await real audio in JSDOM).
const _NEXT_AUDIO_TIME = { value: 0 };

class FakeAudioContext {
  // Getter so tests can bump _NEXT_AUDIO_TIME between scheduling and
  // the playback_pos tick to simulate the audio thread advancing.
  get currentTime(): number {
    return _NEXT_AUDIO_TIME.value;
  }
  state: AudioContextState = "running";
  destination = {} as AudioDestinationNode;
  createBufferSource = vi.fn(() => new FakeBufferSource());
  createGain = vi.fn(() => new FakeGainNode());
  createBiquadFilter = vi.fn(() => new FakeBiquadFilterNode());
  decodeAudioData = vi.fn(
    async (
      _buf: ArrayBuffer,
      ok?: (b: AudioBuffer) => void,
      _err?: (e: Error) => void,
    ) => {
      const ab = new FakeAudioBuffer(240) as unknown as AudioBuffer;
      if (ok) ok(ab);
      return ab;
    },
  );
  resume = vi.fn(() => Promise.resolve());
  close = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  // v3.4 — BufferCache.load() goes through window.fetch to download
  // the MP3 bytes before decode. Stub a default that returns 8 bytes
  // of arbitrary buffer data; individual tests can override per case
  // via globalThis.fetch's Mock chain (mockResolvedValueOnce, etc.).
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => new ArrayBuffer(8),
    })),
  );
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
  FakeGainNode.instances = [];
  FakeBiquadFilterNode.instances = [];
  FakeBufferSource.instances = [];
  FakeBufferSource.nextStartBehavior = "resolve";
  _NEXT_AUDIO_TIME.value = 0;
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
    // v2.6.0 — canonical path moved under /api/sessions/{id}/live/stream.
    expect(FakeWebSocket.lastInstance!.url).toContain(
      "/api/sessions/sid-1/live/stream",
    );
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

  it("caps the djChat feed at 200 entries (keeps the tail)", async () => {
    const { result } = renderHook(() => useLiveSession("sid-djchat-cap"));
    await flushOpen();
    act(() => {
      // Push 250 messages — the first 50 should fall off the head; the
      // surviving array should start at "msg-50" and end at "msg-249".
      for (let i = 0; i < 250; i++) {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "dj_chat",
          text: `msg-${i}`,
        });
      }
    });
    expect(result.current.djChat).toHaveLength(200);
    expect(result.current.djChat[0].text).toBe("msg-50");
    expect(result.current.djChat[199].text).toBe("msg-249");
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

  // ── v3.0.1 — critic_warning surfacing ─────────────────────────────────
  it("appends critic_warning events to criticWarnings with mapped payload", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cw-1"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "critic_warning",
        kind: "phase_lock_fallback",
        reason: "no_beatgrid_either_side",
        outgoing_track: { id: "a", display_name: "Track A" },
        incoming_track: { id: "b", display_name: "Track B" },
        phrase_tier: "fallback",
        message: "regenerate beatgrid",
      });
    });
    expect(result.current.criticWarnings).toHaveLength(1);
    const w = result.current.criticWarnings[0];
    expect(w.reason).toBe("no_beatgrid_either_side");
    expect(w.message).toBe("regenerate beatgrid");
    // snake_case → camelCase mapping happens in the hook.
    expect(w.outgoingTrack.id).toBe("a");
    expect(w.outgoingTrack.displayName).toBe("Track A");
    expect(w.incomingTrack.id).toBe("b");
    expect(w.incomingTrack.displayName).toBe("Track B");
    // Every warning gets a stable client-generated id so the UI can
    // dismiss them individually.
    expect(w.id).toMatch(/^cw-/);
  });

  it("falls back to the reason enum when message is missing", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cw-2"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "critic_warning",
        kind: "phase_lock_fallback",
        reason: "no_phrase_anchor_in_window",
        outgoing_track: { id: "a" },
        incoming_track: { id: "b" },
        // message intentionally omitted — older backend, partial payload
      });
    });
    expect(result.current.criticWarnings[0].message).toBe(
      "no_phrase_anchor_in_window",
    );
  });

  it("caps criticWarnings at 10 entries (drops oldest first)", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cw-3"));
    await flushOpen();
    act(() => {
      for (let i = 0; i < 15; i++) {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "critic_warning",
          kind: "phase_lock_fallback",
          reason: "no_beatgrid_either_side",
          outgoing_track: { id: `out-${i}`, display_name: `O ${i}` },
          incoming_track: { id: `in-${i}`, display_name: `I ${i}` },
          message: `msg-${i}`,
        });
      }
    });
    // Capped at 10; the oldest five (msg-0..msg-4) must be evicted so
    // a sloppy catalog session doesn't accumulate dozens in memory.
    expect(result.current.criticWarnings).toHaveLength(10);
    expect(result.current.criticWarnings[0].message).toBe("msg-5");
    expect(result.current.criticWarnings[9].message).toBe("msg-14");
  });

  it("dismissCriticWarning removes a warning by id and is no-op for unknown id", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cw-4"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "critic_warning",
        kind: "phase_lock_fallback",
        reason: "no_beatgrid_either_side",
        outgoing_track: { id: "a" },
        incoming_track: { id: "b" },
        message: "msg-1",
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "critic_warning",
        kind: "phase_lock_fallback",
        reason: "no_beatgrid_incoming",
        outgoing_track: { id: "a" },
        incoming_track: { id: "c" },
        message: "msg-2",
      });
    });
    expect(result.current.criticWarnings).toHaveLength(2);
    const firstId = result.current.criticWarnings[0].id;
    act(() => {
      result.current.dismissCriticWarning(firstId);
    });
    expect(result.current.criticWarnings).toHaveLength(1);
    expect(result.current.criticWarnings[0].message).toBe("msg-2");
    // Calling with a stale id must be a safe no-op (banner code may
    // race a fresh emit + a dismiss click).
    act(() => {
      result.current.dismissCriticWarning("does-not-exist");
    });
    expect(result.current.criticWarnings).toHaveLength(1);
  });

  it("does not bleed critic_warning into the log or djChat feeds", async () => {
    const { result } = renderHook(() => useLiveSession("sid-cw-5"));
    await flushOpen();
    act(() => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "critic_warning",
        kind: "phase_lock_fallback",
        reason: "no_beatgrid_either_side",
        outgoing_track: { id: "a" },
        incoming_track: { id: "b" },
        message: "msg-1",
      });
    });
    // The warning routes to criticWarnings only — the command log and
    // dj_chat feeds are separate UI surfaces that should not get
    // cross-contaminated.
    expect(result.current.criticWarnings).toHaveLength(1);
    expect(result.current.log).toHaveLength(0);
    expect(result.current.djChat).toHaveLength(0);
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
  it("advances currentTrackTime as the active deck's virtual position advances", async () => {
    // v3.4 — substrate moved to AudioBufferSourceNode. Position is
    // computed as offsetAtStart + (audioCtx.currentTime - startedAt) *
    // rate, so we exercise the math by bumping the FakeAudioContext's
    // currentTime and asserting the playback_pos tick picks it up.
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useLiveSession("sid-time"));
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
        // Let the async cache.load + scheduleSource chain resolve.
        await vi.advanceTimersByTimeAsync(10);
      });
      // After load(): exactly one source created on the active deck.
      // startedAt = audioCtx.currentTime + lookahead (~0.05s). Bump
      // the shared audio clock by 5s — deck.position() reads as
      // ~4.95s and the next playback_pos tick surfaces it.
      expect(FakeBufferSource.instances.length).toBeGreaterThan(0);
      _NEXT_AUDIO_TIME.value = 5.0;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      // The shim's currentTime > 0 indicates the playback_pos tick ran
      // and read deck.position() which used the bumped clock.
      expect(result.current.currentTrackTime).toBeGreaterThan(0);
      expect(result.current.currentTrackDuration).toBe(240);
    } finally {
      vi.useRealTimers();
      _NEXT_AUDIO_TIME.value = 0;
    }
  });

  // ── Bug-4 regression — autoplay block surfaced + recoverable ────────────
  it("flips autoplayBlocked when AudioBufferSourceNode.start throws", async () => {
    // v3.4 — the new substrate's autoplay-block signal is a thrown
    // error on AudioBufferSourceNode.start() (typically
    // InvalidStateError when the AudioContext is "suspended" without
    // a user gesture, or NotAllowedError in stricter browsers).
    // Arm the next source's start() to throw NotAllowedError via the
    // FakeBufferSource.nextStartBehavior knob (auto-resets after one
    // fire) and assert the hook surfaces autoplayBlocked = true.
    FakeBufferSource.nextStartBehavior = "throw";

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
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(result.current.autoplayBlocked).toBe(true);

    // resumePlayback is the user-gesture re-attempt: it calls
    // ctx.resume() and clears the blocked flag. With the new
    // substrate the engine drives the next scheduleSource on its
    // own engine_command — resumePlayback itself doesn't have to
    // re-trigger playback, the audio thread picks up any pending
    // scheduled events once the context resumes.
    await act(async () => {
      result.current.resumePlayback();
      await new Promise((r) => setTimeout(r, 5));
    });
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
    // v3.4 — natural end-of-track now flows through
    // AudioBufferSourceNode.onended (wrapped by BufferDeck). Fire it
    // and assert the hook forwards a synthetic track_ended WS message.
    const src = FakeBufferSource.instances[0];
    expect(src).toBeDefined();
    act(() => {
      src.endNaturally();
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
    // v3.4 — the first source created (deck A's track A) is the now
    // "inactive" deck after the crossfade swapped to B. Firing its
    // onended must NOT publish track_ended because activeDeckRef
    // is now "b".
    const deckASource = FakeBufferSource.instances[0];
    const sentBefore = FakeWebSocket.lastInstance!.sent.length;
    act(() => {
      deckASource.endNaturally();
    });
    const sentAfter = FakeWebSocket.lastInstance!.sent
      .slice(sentBefore)
      .map((s) => JSON.parse(s));
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
      // v3.4 — advance the audio clock by 5 s and tick playback_pos.
      // deck.position() = offsetAtStart + (currentTime - startedAt) * rate
      // startedAt ≈ 0 + SCHEDULE_LOOKAHEAD_SEC (0.05).
      _NEXT_AUDIO_TIME.value = 5.05;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(260);
      });
      // currentTrackTime now ~5 ⇒ countdown 30 - 5 = 25.
      expect(result.current.secondsToCrossfade).toBe(25);
      _NEXT_AUDIO_TIME.value = 15.05;
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
      // v3.4 — bump the audio clock past cf_point_sec (10) so
      // deck.position() reads as ~25 and the derived countdown
      // clamps to 0.
      _NEXT_AUDIO_TIME.value = 25.05;
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
      // v3.4 — bump audio clock to ~23s so deck.position() ≈ 23.
      _NEXT_AUDIO_TIME.value = 23.05;
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

  // ── v2.7.2 — viewer mode (OBS Browser Source / embed) ──────────────────
  it("viewer mode opens the /viewer WS path (not /stream)", async () => {
    renderHook(() => useLiveSession("sid-viewer-1", { viewer: true }));
    await flushOpen();
    expect(FakeWebSocket.lastInstance).not.toBeNull();
    expect(FakeWebSocket.lastInstance!.url).toContain(
      "/api/sessions/sid-viewer-1/live/viewer",
    );
    expect(FakeWebSocket.lastInstance!.url).not.toContain("/live/stream");
  });

  it("viewer mode suppresses outbound user_msg / commands / endless", async () => {
    const { result } = renderHook(() =>
      useLiveSession("sid-viewer-2", { viewer: true }),
    );
    await flushOpen();
    const ws = FakeWebSocket.lastInstance!;
    expect(ws.sent).toEqual([]);
    act(() => {
      result.current.sendCommand({ type: "skip" });
      result.current.sendUserMessage("hello");
      result.current.sendRaw({ type: "perception", rms_db: 0 });
      result.current.setEndlessMode(true);
    });
    // Nothing should have left the wire — viewers are read-only.
    expect(ws.sent).toEqual([]);
  });

  it("viewer mode quit() does not send a quit frame", async () => {
    const { result } = renderHook(() =>
      useLiveSession("sid-viewer-3", { viewer: true }),
    );
    await flushOpen();
    const ws = FakeWebSocket.lastInstance!;
    act(() => {
      result.current.quit();
    });
    expect(ws.sent).toEqual([]);
  });

  it("primary mode (default) still sends user_msg as before", async () => {
    const { result } = renderHook(() => useLiveSession("sid-primary"));
    await flushOpen();
    act(() => {
      result.current.sendUserMessage("hi");
    });
    const ws = FakeWebSocket.lastInstance!;
    const userMsgs = ws.sent
      .map((s) => JSON.parse(s))
      .filter((m) => m.type === "user_msg");
    expect(userMsgs).toHaveLength(1);
    expect(userMsgs[0].text).toBe("hi");
  });

  // ── v3.6.2 — late viewer-flag flip must abandon the primary socket ─────
  it("reconnects to the /viewer path when the viewer flag flips after mount", async () => {
    // The /live page resolves ?viewer=1 in a post-mount effect, so the
    // hook can mount with viewer=false and flip a tick later. Pre-fix
    // the WS effect ignored the flip (viewerMode wasn't a dep) and an
    // OBS Browser Source stayed connected as PRIMARY — its eventual
    // disconnect tore the whole session down (finally → engine.stop()).
    const { rerender } = renderHook(
      ({ viewer }: { viewer: boolean }) =>
        useLiveSession("sid-late-viewer", { viewer }),
      { initialProps: { viewer: false } },
    );
    await flushOpen();
    expect(FakeWebSocket.lastInstance!.url).toContain("/live/stream");

    rerender({ viewer: true });
    await flushOpen();
    expect(FakeWebSocket.lastInstance!.url).toContain(
      "/api/sessions/sid-late-viewer/live/viewer",
    );
    expect(FakeWebSocket.lastInstance!.url).not.toContain("/live/stream");
  });

  // ── v3.6.2 — a failed buffer load stays inert (E2E substrate contract) ──
  it("does not send anything when the buffer fetch 404s", async () => {
    // Deliberate: an unplayable track leaves the deck inert (warn only).
    // Stale playlists are filtered server-side before the engine starts;
    // the E2E suite drives the UI against 404ing mock streams and
    // depends on the deck staying quiet. If this behavior changes,
    // playable E2E audio must land first.
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(
      async (url: unknown) =>
        String(url).includes("/api/tracks/ghost-1/stream")
          ? { ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0) }
          : { ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(8) },
    );
    renderHook(() => useLiveSession("sid-404"));
    await flushOpen();
    const ghost = { id: "ghost-1", display_name: "Deleted" };
    await act(async () => {
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "engine_command",
        command: "load",
        track: ghost,
      });
      FakeWebSocket.lastInstance!.pushServerEvent({
        type: "track_started",
        track: ghost,
      });
      await new Promise((r) => setTimeout(r, 5));
    });
    const sent = FakeWebSocket.lastInstance!.sent.map((s) => JSON.parse(s));
    expect(
      sent.filter((m: { type: string }) => m.type === "track_ended"),
    ).toEqual([]);
  });

  // ── v2.7.3 — WS auto-reconnect with exponential backoff ────────────────
  // Backoff schedule mirrors the prod constant in lib/live.ts:
  // 1s / 2s / 4s / 8s / 15s, 5 attempts max.
  describe("WS reconnect", () => {
    const BACKOFFS = [1_000, 2_000, 4_000, 8_000, 15_000];

    async function burnRetries(advance: typeof vi.advanceTimersByTimeAsync) {
      // Caller must have already triggered the FIRST close (which sets
      // wsRetryAttempt=1 and schedules connect(1)). This walks through
      // attempts 1..5: advance past the backoff so connect() fires,
      // flush the new WS's open setTimeout(0), then close it again to
      // queue the next attempt. After the loop the hook is in
      // wsExhausted=true.
      for (let i = 0; i < BACKOFFS.length; i++) {
        await act(async () => {
          await advance(BACKOFFS[i] + 50);
        });
        await act(async () => {
          await advance(5);
        });
        act(() => {
          FakeWebSocket.lastInstance!.triggerClose(1006);
        });
      }
    }

    it("retries with backoff after a non-4001 close and clears state on reopen", async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveSession("sid-r1"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        expect(result.current.connected).toBe(true);
        const ws1 = FakeWebSocket.lastInstance!;

        // Server drops the connection (e.g. uvicorn --reload).
        act(() => {
          ws1.triggerClose(1006);
        });
        expect(result.current.connected).toBe(false);
        expect(result.current.wsRetryAttempt).toBe(1);
        expect(result.current.wsExhausted).toBe(false);
        // No new WS has been constructed yet — the backoff is still
        // pending. Advancing JUST under the first backoff must not
        // create one either.
        expect(FakeWebSocket.lastInstance).toBe(ws1);
        await act(async () => {
          await vi.advanceTimersByTimeAsync(900);
        });
        expect(FakeWebSocket.lastInstance).toBe(ws1);

        // Cross the 1s backoff threshold — connect() fires.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(200);
        });
        const ws2 = FakeWebSocket.lastInstance!;
        expect(ws2).not.toBe(ws1);
        // FakeWebSocket constructor schedules onopen via setTimeout(0).
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        expect(result.current.connected).toBe(true);
        expect(result.current.wsRetryAttempt).toBe(0);
        expect(result.current.wsExhausted).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("exposes wsRetryMax matching the production constant", () => {
      const { result } = renderHook(() => useLiveSession("sid-r-max"));
      expect(result.current.wsRetryMax).toBe(5);
    });

    it("flips wsExhausted after MAX_WS_RETRIES consecutive failures", async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveSession("sid-r2"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        // Initial failure that kicks off the retry loop.
        act(() => {
          FakeWebSocket.lastInstance!.triggerClose(1006);
        });
        expect(result.current.wsRetryAttempt).toBe(1);

        await burnRetries(vi.advanceTimersByTimeAsync);

        expect(result.current.wsExhausted).toBe(true);
        expect(result.current.wsRetryAttempt).toBe(0);
        expect(result.current.connected).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("schedules ONE delayed reclaim after a 4001 close (no immediate error)", async () => {
      // v2.7.4 — the prior behaviour gave up on the first 4001. That
      // stranded OBS Browser Sources (which the operator cannot
      // refresh) on a permanent displaced banner whenever a
      // transient HMR remount briefly stole primary. The new path
      // schedules one delayed reclaim so the displaced tab can take
      // primary back if the displacing connection has since gone
      // away.
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveSession("sid-r3"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        const ws1 = FakeWebSocket.lastInstance!;
        act(() => {
          ws1.triggerClose(4001);
        });
        // No error yet — we're in the 30 s reclaim wait. Banner
        // surfaces via wsRetryAttempt=1 ("Reconnecting…").
        expect(result.current.error).toBeNull();
        expect(result.current.wsRetryAttempt).toBe(1);
        expect(result.current.connected).toBe(false);
        expect(FakeWebSocket.lastInstance).toBe(ws1);

        // Cross the 30 s reclaim delay — connect() fires.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(30_100);
        });
        const ws2 = FakeWebSocket.lastInstance!;
        expect(ws2).not.toBe(ws1);
        // FakeWebSocket constructor schedules onopen via setTimeout(0).
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        expect(result.current.connected).toBe(true);
        expect(result.current.wsRetryAttempt).toBe(0);
      } finally {
        vi.useRealTimers();
      }
    });

    it("gives up after a SECOND 4001 (genuine other primary still alive)", async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveSession("sid-r3b"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        // First displacement → schedules 30 s reclaim.
        act(() => {
          FakeWebSocket.lastInstance!.triggerClose(4001);
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(30_100);
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        expect(result.current.connected).toBe(true);

        // Second displacement on the reclaim — give up. No third WS
        // is constructed, error surfaces.
        const reclaimWs = FakeWebSocket.lastInstance!;
        act(() => {
          reclaimWs.triggerClose(4001);
        });
        expect(result.current.error).toContain("moved to another window");
        expect(result.current.wsRetryAttempt).toBe(0);
        expect(result.current.connected).toBe(false);

        // No more WS attempts — looping would kick the genuine
        // other primary off forever.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(60_000);
        });
        expect(FakeWebSocket.lastInstance).toBe(reclaimWs);
      } finally {
        vi.useRealTimers();
      }
    });

    it("reconnectNow() recovers from wsExhausted by opening a fresh WS", async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveSession("sid-r4"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        // Push the hook into the exhausted state via the same helper.
        act(() => {
          FakeWebSocket.lastInstance!.triggerClose(1006);
        });
        await burnRetries(vi.advanceTimersByTimeAsync);
        expect(result.current.wsExhausted).toBe(true);
        const exhaustedWs = FakeWebSocket.lastInstance;

        // Manual click on the Reconnect button.
        act(() => {
          result.current.reconnectNow();
        });
        expect(result.current.wsExhausted).toBe(false);
        expect(result.current.wsRetryAttempt).toBe(0);

        // The effect re-runs (reconnectKey bumped), opening a new WS.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        expect(FakeWebSocket.lastInstance).not.toBe(exhaustedWs);
        expect(result.current.connected).toBe(true);
      } finally {
        vi.useRealTimers();
      }
    });

    it("cleanup cancels a pending retry timer (no new WS after unmount)", async () => {
      vi.useFakeTimers();
      try {
        const { unmount } = renderHook(() => useLiveSession("sid-r5"));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5);
        });
        const ws1 = FakeWebSocket.lastInstance!;
        act(() => {
          ws1.triggerClose(1006);
        });
        // Unmount BEFORE the 1s backoff fires.
        unmount();
        await act(async () => {
          await vi.advanceTimersByTimeAsync(20_000);
        });
        expect(FakeWebSocket.lastInstance).toBe(ws1);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  // =======================================================================
  // v3.0 — phase-lock wiring on the engine_command:crossfade path.
  //
  // These tests pin the surface that pairs with agent/live_engine.py's
  // LiveEngineBrowser phase-lock emit. The whole reason this WS payload
  // exists is so the frontend's WebAudio scheduler stops disagreeing
  // with what main.build_mix and LiveEngineLocal already do. A
  // regression here would silently push /live back to its pre-v3.0
  // off-grid linear-fade behaviour.
  // =======================================================================

  describe("v3.0 phase-lock crossfade", () => {
    const v2Track = (id: string, name: string) => ({
      id,
      display_name: name,
      bpm: 128,
      camelot_key: "8A",
      duration_sec: 60,
      beatgrid: {
        version: 2,
        bpm: 128,
        first_beat_sec: 0,
        downbeats_sec: [0, 1.875, 3.75, 5.625],
        beats_per_bar: 4,
        source: "madmom" as const,
      },
    });

    const phaseLockPayload = {
      outgoing_anchor_sec: 48.0,
      incoming_anchor_sec: 1.875,
      xfade_sec: 12.0,
      phrase_tier: "16-bar",
      incoming_pickup_skipped: true,
      edge_guard_samples: 64,
      sample_rate: 44100,
    };

    async function bootstrapAndStart(sessionId: string) {
      const { result } = renderHook(() => useLiveSession(sessionId));
      await flushOpen();
      const playlist = [v2Track("A", "Track A"), v2Track("B", "Track B")];
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: sessionId,
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
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      return { result, playlist };
    }

    it("uses setValueCurveAtTime (equal-power) when phase_lock is present", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-1");
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLockPayload,
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // Both gain nodes received the equal-power curve, not a linear ramp.
      const curveCalls = FakeGainNode.instances.flatMap((g) =>
        g.gain.setValueCurveAtTime.mock.calls,
      );
      expect(curveCalls.length).toBeGreaterThanOrEqual(2);
      // Two ramps wired: one fading out, one fading in. The first sample of
      // a fade-out curve is 1 (cos(0)); first sample of fade-in is 0 (sin(0)).
      const firstSamples = curveCalls
        .map((call) => (call[0] as Float32Array)[0])
        .sort();
      expect(firstSamples[0]).toBeLessThan(0.01); // fade-in starts at 0
      expect(firstSamples[1]).toBeGreaterThan(0.99); // fade-out starts at 1
      // Linear ramp must NOT be invoked when phase-lock is in play.
      const linearCalls = FakeGainNode.instances.flatMap((g) =>
        g.gain.linearRampToValueAtTime.mock.calls,
      );
      expect(linearCalls).toHaveLength(0);
    });

    it("falls back to linearRampToValueAtTime when phase_lock is missing", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-2");
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          // no phase_lock — legacy catalog without v2 beatgrid
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      const linearCalls = FakeGainNode.instances.flatMap((g) =>
        g.gain.linearRampToValueAtTime.mock.calls,
      );
      expect(linearCalls.length).toBeGreaterThanOrEqual(2);
      const curveCalls = FakeGainNode.instances.flatMap((g) =>
        g.gain.setValueCurveAtTime.mock.calls,
      );
      expect(curveCalls).toHaveLength(0);
    });

    it("starts the incoming source at the incoming_anchor_sec offset", async () => {
      // v3.4 — anchor is now the SAMPLE-ACCURATE second argument to
      // AudioBufferSourceNode.start(when, offset). No more
      // HTMLAudioElement.currentTime seek (which was MP3-frame
      // quantised), no more loadedmetadata listener. This single
      // source.start() with the right offset is the textbook
      // sample-accurate scheduling primitive per W3C Web Audio 1.1.
      const { playlist } = await bootstrapAndStart("sid-pl-3");
      const sourcesBefore = FakeBufferSource.instances.length;
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLockPayload, // incoming_anchor_sec = 1.875
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      // The incoming source is the one created after the crossfade event.
      const incomingSource = FakeBufferSource.instances[sourcesBefore];
      expect(incomingSource).toBeDefined();
      // start(when, offset) — offset is the catalog-time anchor.
      expect(incomingSource.start).toHaveBeenCalledTimes(1);
      const [, offsetArg] = incomingSource.start.mock.calls[0] as unknown as [
        number,
        number,
      ];
      expect(offsetArg).toBeCloseTo(1.875, 3);
    });

    it("starts the incoming source at offset 0 when incoming_anchor_sec is 0", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-4");
      const baselinePayload = {
        ...phaseLockPayload,
        incoming_anchor_sec: 0,
        incoming_pickup_skipped: false,
      };
      const sourcesBefore = FakeBufferSource.instances.length;
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: baselinePayload,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incomingSource = FakeBufferSource.instances[sourcesBefore];
      expect(incomingSource).toBeDefined();
      const [, offsetArg] = incomingSource.start.mock.calls[0] as unknown as [
        number,
        number,
      ];
      expect(offsetArg).toBe(0);
    });

    it("applies the v3.5 beat_rate_schedule as playbackRate automation on the incoming source", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-gw1");
      const schedulePayload = {
        ...phaseLockPayload,
        incoming_rate: 1.0,
        beat_rate_schedule: [
          { at_sec: 0, rate: 1.0667, ramp: false },
          { at_sec: 1.875, rate: 1.0667, ramp: false },
          { at_sec: 12.0, rate: 1.0667, ramp: false },
          { at_sec: 28.0, rate: 1.0, ramp: true },
        ],
      };
      const sourcesBefore = FakeBufferSource.instances.length;
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: schedulePayload,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incoming = FakeBufferSource.instances[sourcesBefore];
      expect(incoming).toBeDefined();
      // Source started at the first segment's rate (first bar already locked).
      expect(incoming.playbackRate.value).toBeCloseTo(1.0667, 4);
      // Stepped per-bar lock segments scheduled.
      expect(incoming.playbackRate.setValueAtTime).toHaveBeenCalledWith(
        1.0667,
        expect.any(Number),
      );
      // Release glide back to native rate.
      expect(incoming.playbackRate.linearRampToValueAtTime).toHaveBeenCalledWith(
        1.0,
        expect.any(Number),
      );
    });

    it("keeps the static incoming_rate when no beat_rate_schedule is present", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-gw2");
      const staticRatePayload = { ...phaseLockPayload, incoming_rate: 0.94 };
      const sourcesBefore = FakeBufferSource.instances.length;
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: staticRatePayload,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incoming = FakeBufferSource.instances[sourcesBefore];
      expect(incoming.playbackRate.value).toBeCloseTo(0.94, 4);
      // No per-bar automation without a schedule.
      expect(incoming.playbackRate.setValueAtTime).not.toHaveBeenCalled();
      expect(incoming.playbackRate.linearRampToValueAtTime).not.toHaveBeenCalled();
    });

    it("falls back to crossfade_sec when phase_lock.xfade_sec is missing", async () => {
      const { playlist } = await bootstrapAndStart("sid-pl-5");
      const partialPayload = {
        incoming_anchor_sec: 1.875,
        // xfade_sec missing — payload is partial / malformed
        phrase_tier: "16-bar",
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 7,
          phase_lock: partialPayload as unknown as PhaseLockPayload,
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // Missing xfade_sec → linear-ramp fallback at the engine's
      // crossfade_sec (7 here, not the payload-default 12). Verifies the
      // partial-payload defensive branch.
      const linearCalls = FakeGainNode.instances.flatMap((g) =>
        g.gain.linearRampToValueAtTime.mock.calls,
      );
      expect(linearCalls.length).toBeGreaterThan(0);
    });
  });

  // =======================================================================
  // v3.3 — bass_swap transition style (HPF cutoff automation on incoming).
  //
  // When the backend's pick_transition_style fires BASS_SWAP, the
  // phase_lock payload carries:
  //   transition_style: "bass_swap"
  //   bass_swap: { hpf_cutoff_during_hz, hpf_cutoff_after_hz,
  //                drop_at_incoming_sec }
  //
  // The deck schedules two AudioParam.setValueAtTime calls on the
  // incoming filter's frequency: cutoff_during at currentTime,
  // cutoff_after at currentTime + (drop_at_incoming - incoming_anchor)
  // / incoming_rate. SMOOTH_BLEND (or missing payload) must NOT touch
  // the filter beyond the defensive reset to 20 Hz.
  // =======================================================================

  describe("v3.3 bass_swap automation", () => {
    const v2Track = (id: string, name: string) => ({
      id,
      display_name: name,
      bpm: 122,
      camelot_key: "8A",
      duration_sec: 200,
      beatgrid: {
        version: 2,
        bpm: 122,
        first_beat_sec: 0,
        downbeats_sec: [0, 1.967, 3.934, 5.902, 7.869, 9.836, 11.803],
        beats_per_bar: 4,
        source: "madmom" as const,
      },
    });

    const bassSwapPayload = {
      outgoing_anchor_sec: 100.0,
      incoming_anchor_sec: 0,
      xfade_sec: 12.0,
      phrase_tier: "16-bar",
      incoming_pickup_skipped: false,
      edge_guard_samples: 64,
      sample_rate: 44100,
      incoming_rate: 1.0,
      outgoing_rate: 1.0,
      transition_style: "bass_swap" as const,
      bass_swap: {
        hpf_cutoff_during_hz: 120,
        hpf_cutoff_after_hz: 20,
        drop_at_incoming_sec: 5.902,
      },
    };

    async function bootstrapAndStart(sessionId: string) {
      const { result } = renderHook(() => useLiveSession(sessionId));
      await flushOpen();
      const playlist = [v2Track("A", "Track A"), v2Track("B", "Track B")];
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: sessionId,
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
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      return { result, playlist };
    }

    it("schedules HPF cutoff at hpf_cutoff_during_hz when bass_swap fires", async () => {
      const { playlist } = await bootstrapAndStart("sid-bs-1");
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: bassSwapPayload,
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // Exactly two filter instances exist (deck A + deck B) once
      // ensureDeck has wired both decks. The incoming filter (deck B)
      // is the one whose `frequency.setValueAtTime` was called with the
      // bass_swap parameters.
      const cutoffCalls = FakeBiquadFilterNode.instances.flatMap((f) =>
        f.frequency.setValueAtTime.mock.calls.map(
          (c) => c[0] as number,
        ),
      );
      expect(cutoffCalls).toContain(120);
      expect(cutoffCalls).toContain(20);
    });

    it("schedules the drop at when + drop_offset / incoming_rate", async () => {
      // v3.4 — the drop time anchors against the SAME `when` as the
      // source's start() and the gain ramps, not against
      // ctx.currentTime. Because audio rendering is sample-accurate
      // against that single `when`, the filter snap and the source's
      // first samples and the gain crossover all hit the same audio
      // frame. drop_at_incoming_sec=5.902, anchor=0, rate=1.0,
      // when=currentTime + SCHEDULE_LOOKAHEAD_SEC (=0.05) →
      // drop schedules at 0.05 + 5.902 = 5.952s.
      const { playlist } = await bootstrapAndStart("sid-bs-2");
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: bassSwapPayload,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incomingFilter = FakeBiquadFilterNode.instances.find((f) =>
        f.frequency.setValueAtTime.mock.calls.some(
          (c) => c[0] === 120,
        ),
      );
      expect(incomingFilter).toBeDefined();
      const dropCall = incomingFilter!.frequency.setValueAtTime.mock.calls.find(
        (c) => c[0] === 20,
      );
      expect(dropCall).toBeDefined();
      // Drop schedules at when + dropDelay. With the fake context's
      // currentTime starting at 0 and SCHEDULE_LOOKAHEAD_SEC=0.05,
      // when=0.05, dropDelay=5.902/1.0=5.902 → expected 5.952.
      expect(dropCall![1] as number).toBeCloseTo(5.952, 2);
    });

    it("does NOT schedule bass_swap automation when transition_style is smooth_blend", async () => {
      const { playlist } = await bootstrapAndStart("sid-bs-3");
      const smoothPayload = {
        ...bassSwapPayload,
        transition_style: "smooth_blend" as const,
        bass_swap: undefined,
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: smoothPayload,
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // The 120 Hz cutoff is bass_swap-specific. Smooth blend may
      // still re-assert the 20 Hz default for safety, so we only
      // forbid the during-cutoff scheduling.
      const cutoffCalls = FakeBiquadFilterNode.instances.flatMap((f) =>
        f.frequency.setValueAtTime.mock.calls.map(
          (c) => c[0] as number,
        ),
      );
      expect(cutoffCalls).not.toContain(120);
    });

    it("resets incoming filter to 20 Hz on smooth_blend after a prior bass_swap", async () => {
      const { playlist } = await bootstrapAndStart("sid-bs-4");
      // First a bass_swap to "dirty" the filter state.
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: bassSwapPayload,
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // Now a smooth_blend on the same deck pair — verify a 20 Hz
      // reset is asserted on the incoming filter so the next track
      // doesn't inherit the 120 Hz cutoff.
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[0],
          crossfade_sec: 12,
          phase_lock: {
            ...bassSwapPayload,
            transition_style: "smooth_blend" as const,
            bass_swap: undefined,
          },
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      // At least one of the filters must have been reset to 20 Hz
      // *after* the bass_swap calls landed on it.
      const allResets = FakeBiquadFilterNode.instances.flatMap((f) =>
        f.frequency.setValueAtTime.mock.calls.filter(
          (c) => c[0] === 20,
        ),
      );
      expect(allResets.length).toBeGreaterThanOrEqual(1);
    });
  });

  // =======================================================================
  // v3.1 — tempo matching on the incoming deck via playbackRate.
  //
  // The browser path can't run pyrubberband, so when ``incoming_rate``
  // arrives in the phase_lock payload the hook applies it as the
  // incoming deck's ``playbackRate`` (with ``preservesPitch=true`` so
  // pitch/key doesn't shift). These tests pin the wiring: rate gets
  // applied before play, ``preservesPitch`` is set, and a subsequent
  // plain ``load`` resets the rate back to 1.0.
  // =======================================================================

  describe("v3.1 tempo matching", () => {
    const v2Track = (id: string, name: string, bpm = 128) => ({
      id,
      display_name: name,
      bpm,
      camelot_key: "8A",
      duration_sec: 60,
      beatgrid: {
        version: 2,
        bpm,
        first_beat_sec: 0,
        downbeats_sec: [0, 1.875, 3.75, 5.625],
        beats_per_bar: 4,
        source: "madmom" as const,
      },
    });

    async function bootstrapAndStart(sessionId: string) {
      const { result } = renderHook(() => useLiveSession(sessionId));
      await flushOpen();
      const playlist = [v2Track("A", "Track A", 120), v2Track("B", "Track B", 130)];
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "live_state",
          data: {
            session_id: sessionId,
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
        });
        await new Promise((r) => setTimeout(r, 5));
      });
      return { result, playlist };
    }

    it("applies incoming_rate to the incoming source during crossfade", async () => {
      // v3.4 — playbackRate is set on the new AudioBufferSourceNode's
      // AudioParam (sample-accurate, audio-thread-scheduled). The
      // legacy preservesPitch flag only existed on HTMLMediaElement;
      // BufferSource preserves pitch natively because it's an
      // in-memory PCM resampler. No "preservesPitch" assertion needed.
      const { playlist } = await bootstrapAndStart("sid-tempo-1");
      const sourcesBefore = FakeBufferSource.instances.length;
      const phaseLock = {
        outgoing_anchor_sec: 48.0,
        incoming_anchor_sec: 0,
        xfade_sec: 12.0,
        phrase_tier: "16-bar",
        incoming_pickup_skipped: false,
        edge_guard_samples: 64,
        sample_rate: 44100,
        incoming_rate: 120 / 130,
        outgoing_rate: 1.0,
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLock,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incomingSource = FakeBufferSource.instances[sourcesBefore];
      expect(incomingSource).toBeDefined();
      expect(incomingSource.playbackRate.value).toBeCloseTo(120 / 130, 6);
    });

    it("keeps playbackRate at 1.0 when incoming_rate is missing", async () => {
      const { playlist } = await bootstrapAndStart("sid-tempo-2");
      const sourcesBefore = FakeBufferSource.instances.length;
      const phaseLockNoRate = {
        outgoing_anchor_sec: 48.0,
        incoming_anchor_sec: 0,
        xfade_sec: 12.0,
        phrase_tier: "16-bar",
        incoming_pickup_skipped: false,
        edge_guard_samples: 64,
        sample_rate: 44100,
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLockNoRate,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incomingSource = FakeBufferSource.instances[sourcesBefore];
      expect(incomingSource).toBeDefined();
      expect(incomingSource.playbackRate.value).toBe(1.0);
    });

    it("keeps playbackRate at 1.0 when incoming_rate is exactly 1.0", async () => {
      const { playlist } = await bootstrapAndStart("sid-tempo-3");
      const sourcesBefore = FakeBufferSource.instances.length;
      const phaseLock = {
        outgoing_anchor_sec: 48.0,
        incoming_anchor_sec: 0,
        xfade_sec: 12.0,
        phrase_tier: "16-bar",
        incoming_pickup_skipped: false,
        edge_guard_samples: 64,
        sample_rate: 44100,
        incoming_rate: 1.0,
        outgoing_rate: 1.0,
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLock,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const incomingSource = FakeBufferSource.instances[sourcesBefore];
      expect(incomingSource.playbackRate.value).toBe(1.0);
    });

    it("resets playbackRate to 1.0 on a plain load (post-crossfade hand-off)", async () => {
      // v3.4 — each play creates a FRESH source with rate set
      // explicitly. A plain load passes rate=1.0; a crossfade passes
      // the incoming_rate from the phase_lock payload. There's no
      // "stale rate inherited" failure mode like HTMLAudioElement
      // had because BufferDeck.scheduleSource() never reuses a source.
      const { playlist } = await bootstrapAndStart("sid-tempo-4");
      const sourcesBeforeXf = FakeBufferSource.instances.length;
      const phaseLock = {
        outgoing_anchor_sec: 48.0,
        incoming_anchor_sec: 0,
        xfade_sec: 12.0,
        phrase_tier: "16-bar",
        incoming_pickup_skipped: false,
        edge_guard_samples: 64,
        sample_rate: 44100,
        incoming_rate: 0.9,
        outgoing_rate: 1.0,
      };
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "crossfade",
          to_track: playlist[1],
          crossfade_sec: 12,
          phase_lock: phaseLock,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const xfSource = FakeBufferSource.instances[sourcesBeforeXf];
      expect(xfSource.playbackRate.value).toBeCloseTo(0.9, 6);

      // Engine advances to track C via plain load (no crossfade) — the
      // new source created on the active deck must have rate=1.0.
      const trackC = v2Track("C", "Track C", 130);
      const sourcesBeforeLoad = FakeBufferSource.instances.length;
      await act(async () => {
        FakeWebSocket.lastInstance!.pushServerEvent({
          type: "engine_command",
          command: "load",
          track: trackC,
        });
        await new Promise((r) => setTimeout(r, 10));
      });
      const trackCSource = FakeBufferSource.instances[sourcesBeforeLoad];
      expect(trackCSource).toBeDefined();
      expect(trackCSource.playbackRate.value).toBe(1.0);
    });
  });
});

// ───────────────────────────────────────────────────────────────────────────
// v3.0 — buildEqualPowerCurve helper (pure function, no React/WS state)
// ───────────────────────────────────────────────────────────────────────────

describe("buildEqualPowerCurve", () => {
  it("fade-out curve starts at 1 and ends at 0", () => {
    const curve = buildEqualPowerCurve("out");
    expect(curve[0]).toBeCloseTo(1.0, 5);
    expect(curve[curve.length - 1]).toBeCloseTo(0.0, 5);
  });

  it("fade-in curve starts at 0 and ends at 1", () => {
    const curve = buildEqualPowerCurve("in");
    expect(curve[0]).toBeCloseTo(0.0, 5);
    expect(curve[curve.length - 1]).toBeCloseTo(1.0, 5);
  });

  it("squared sum stays at unity power across the overlap", () => {
    // cos²(t·π/2) + sin²(t·π/2) = 1 — the whole point of "equal-power"
    // crossfading. If a future contributor switches to e.g. linear ramps
    // here, the perceived loudness will dip in the middle of the overlap
    // and this assertion catches it.
    const fadeOut = buildEqualPowerCurve("out");
    const fadeIn = buildEqualPowerCurve("in");
    for (let i = 0; i < fadeOut.length; i++) {
      const power = fadeOut[i] ** 2 + fadeIn[i] ** 2;
      expect(power).toBeCloseTo(1.0, 4);
    }
  });

  it("midpoint is √2/2 for both curves (45° on the cos/sin arc)", () => {
    const mid = Math.floor(257 / 2);
    expect(buildEqualPowerCurve("out")[mid]).toBeCloseTo(Math.SQRT1_2, 2);
    expect(buildEqualPowerCurve("in")[mid]).toBeCloseTo(Math.SQRT1_2, 2);
  });

  it("custom sample count produces matching length", () => {
    expect(buildEqualPowerCurve("out", 64)).toHaveLength(64);
    expect(buildEqualPowerCurve("in", 1024)).toHaveLength(1024);
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
