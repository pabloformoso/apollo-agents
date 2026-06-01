/**
 * Tests for v3.4 BufferDeck + BufferCache — the sample-accurate
 * playback substrate that replaces HTMLAudioElement + MediaElementAudioSourceNode.
 *
 * Verifies the contract live.ts will rely on:
 *   - sources are single-use (replaced on each scheduleSource)
 *   - start(when, offset) is called with the exact lookahead-shifted time
 *   - virtual position math matches catalog-time semantics
 *   - filter + gain default to pass-through state for SMOOTH_BLEND
 *   - resetAutomation restores known state after a bass_swap
 *   - BufferCache de-duplicates concurrent loads of the same URL
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

import {
  BufferCache,
  BufferDeck,
  SCHEDULE_LOOKAHEAD_SEC,
} from "../lib/audio_buffer_decks";

// ── Fakes ────────────────────────────────────────────────────────────────

class FakeBufferSource {
  static instances: FakeBufferSource[] = [];
  static onendedHandlers: Map<FakeBufferSource, (() => void) | null> = new Map();

  buffer: AudioBuffer | null = null;
  playbackRate = { value: 1 };
  onended: (() => void) | null = null;
  start = vi.fn() as Mock;
  stop = vi.fn() as Mock;
  connect = vi.fn(() => this) as Mock;
  disconnect = vi.fn() as Mock;

  constructor() {
    FakeBufferSource.instances.push(this);
  }

  /** Test helper — fire onended as if the buffer played out. */
  endNaturally() {
    if (this.onended) this.onended();
  }
}

class FakeGain {
  gain = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    setValueCurveAtTime: vi.fn(),
  };
  connect = vi.fn(() => this);
}

class FakeBiquad {
  type: BiquadFilterType = "highpass";
  Q = { value: 0.7 };
  frequency = {
    value: 20,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
  };
  connect = vi.fn(() => this);
}

class FakeAudioBuffer {
  constructor(public duration: number) {}
}

class FakeAudioCtx {
  currentTime = 0;
  destination = {};
  createBufferSource = vi.fn(() => new FakeBufferSource());
  createGain = vi.fn(() => new FakeGain());
  createBiquadFilter = vi.fn(() => new FakeBiquad());
  decodeAudioData = vi.fn(
    (_buf: ArrayBuffer, _ok?: (b: AudioBuffer) => void, _err?: (e: Error) => void) => {
      const ab = new FakeAudioBuffer(240) as unknown as AudioBuffer;
      if (_ok) _ok(ab);
      return Promise.resolve(ab);
    },
  );
}

let audioCtx: FakeAudioCtx;

beforeEach(() => {
  FakeBufferSource.instances = [];
  audioCtx = new FakeAudioCtx();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── BufferDeck — wiring + scheduling ──────────────────────────────────────

describe("BufferDeck", () => {
  it("connects filter -> gain -> destination at construction time", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    expect(audioCtx.createGain).toHaveBeenCalledOnce();
    expect(audioCtx.createBiquadFilter).toHaveBeenCalledOnce();
    expect(deck.filter).not.toBeNull();
    // Filter feeds the gain.
    expect((deck.filter as unknown as FakeBiquad).connect).toHaveBeenCalledWith(deck.gain);
    // Gain feeds the destination.
    expect((deck.gain as unknown as FakeGain).connect).toHaveBeenCalledWith(audioCtx.destination);
  });

  it("starts with the requested initialGain (0 for inactive deck)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    expect(deck.gain.gain.value).toBe(0);
  });

  it("starts with the requested initialGain (1 for active deck)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 1);
    expect(deck.gain.gain.value).toBe(1);
  });

  it("defaults the filter to a 20 Hz pass-through highpass", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 1);
    expect(deck.filter?.type).toBe("highpass");
    expect(deck.filter?.frequency.value).toBe(20);
  });

  it("scheduleSource creates a fresh AudioBufferSourceNode and starts it at the lookahead time", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 10.0;
    const whenSec = audioCtx.currentTime + SCHEDULE_LOOKAHEAD_SEC;
    deck.scheduleSource(buf, whenSec, 1.875, 1.0, "track-A");
    const src = FakeBufferSource.instances[0];
    expect(src).toBeDefined();
    expect(src.buffer).toBe(buf);
    expect(src.start).toHaveBeenCalledWith(whenSec, 1.875);
    expect(src.playbackRate.value).toBe(1.0);
    expect(deck.getTrackId()).toBe("track-A");
    expect(deck.isPlaying()).toBe(true);
  });

  it("scheduleSource applies the requested playback rate", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 1.0, 0, 0.95, "track-X");
    expect(FakeBufferSource.instances[0].playbackRate.value).toBe(0.95);
  });

  it("scheduleSource connects the new source to the filter (not directly to the gain)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t");
    expect(FakeBufferSource.instances[0].connect).toHaveBeenCalledWith(deck.filter);
  });

  it("scheduleSource stops the prior source before creating a new one (single-use contract)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf1 = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const buf2 = new FakeAudioBuffer(180) as unknown as AudioBuffer;
    deck.scheduleSource(buf1, 1.0, 0, 1.0, "t1");
    deck.scheduleSource(buf2, 5.0, 0, 1.0, "t2");
    expect(FakeBufferSource.instances).toHaveLength(2);
    expect(FakeBufferSource.instances[0].stop).toHaveBeenCalled();
    expect(deck.getTrackId()).toBe("t2");
  });

  it("stop() ends the current source and clears state, idempotent on repeated calls", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t");
    expect(deck.isPlaying()).toBe(true);
    deck.stop();
    expect(deck.isPlaying()).toBe(false);
    expect(deck.getTrackId()).toBeNull();
    expect(FakeBufferSource.instances[0].stop).toHaveBeenCalled();
    // Calling stop again is a no-op, not a crash.
    deck.stop();
    expect(FakeBufferSource.instances[0].stop).toHaveBeenCalledOnce();
  });

  it("stop() clears onended so it does NOT fire the track-ended callback", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const onEnded = vi.fn();
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t", onEnded);
    deck.stop();
    // Simulate a late onended firing post-stop — the deck's wrapper
    // cleared the handler, so this is a no-op now.
    const src = FakeBufferSource.instances[0];
    if (src.onended) src.onended();
    expect(onEnded).not.toHaveBeenCalled();
  });

  it("forwards natural source.onended to the user callback", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const onEnded = vi.fn();
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t", onEnded);
    FakeBufferSource.instances[0].endNaturally();
    expect(onEnded).toHaveBeenCalledOnce();
    // And the deck self-clears, so a follow-up scheduleSource works.
    expect(deck.isPlaying()).toBe(false);
  });
});

// ── Virtual position math ─────────────────────────────────────────────────

describe("BufferDeck.position()", () => {
  it("returns 0 when no source has been scheduled", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    expect(deck.position()).toBe(0);
  });

  it("returns the catalog-time offset right after start (elapsed == 0)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 10.0;
    deck.scheduleSource(buf, 10.05, 1.875, 1.0, "t");
    // Audio thread hasn't advanced past start time yet.
    expect(deck.position()).toBeCloseTo(1.875, 3);
  });

  it("advances at native rate when playback rate is 1.0", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 10.0;
    deck.scheduleSource(buf, 10.0, 0, 1.0, "t");
    audioCtx.currentTime = 13.0; // 3 s of wall clock past start
    expect(deck.position()).toBeCloseTo(3.0, 3);
  });

  it("advances at the slowed rate when playback rate < 1.0 (tempo-match)", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 10.0;
    deck.scheduleSource(buf, 10.0, 0, 0.95, "t");
    audioCtx.currentTime = 20.0; // 10 s wall clock at 0.95x = 9.5 s catalog
    expect(deck.position()).toBeCloseTo(9.5, 3);
  });

  it("respects the offset when the source was started mid-track", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 10.0;
    deck.scheduleSource(buf, 10.0, 30.0, 1.0, "t"); // start at catalog-time 30
    audioCtx.currentTime = 15.0; // 5 s later
    expect(deck.position()).toBeCloseTo(35.0, 3);
  });
});

// ── Duration + resetAutomation ────────────────────────────────────────────

describe("BufferDeck.duration() and resetAutomation()", () => {
  it("duration returns the buffer's native duration when a source is loaded", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    expect(deck.duration()).toBe(0);
    const buf = new FakeAudioBuffer(123.45) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t");
    expect(deck.duration()).toBe(123.45);
  });

  it("resetAutomation restores filter cutoff to 20 Hz and gain to the given value", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 1);
    audioCtx.currentTime = 5.0;
    deck.resetAutomation(1);
    expect(deck.gain.gain.cancelScheduledValues).toHaveBeenCalledWith(5.0);
    expect(deck.gain.gain.setValueAtTime).toHaveBeenCalledWith(1, 5.0);
    expect(deck.filter?.frequency.cancelScheduledValues).toHaveBeenCalledWith(5.0);
    expect(deck.filter?.frequency.setValueAtTime).toHaveBeenCalledWith(20, 5.0);
  });
});

// ── BufferCache ───────────────────────────────────────────────────────────

describe("BufferCache", () => {
  beforeEach(() => {
    // Provide a fake fetch global for the cache to use.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(8),
      })),
    );
  });

  it("caches a successful load — second call returns the same buffer without re-fetching", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    const b1 = await cache.load("/api/tracks/abc/stream");
    const b2 = await cache.load("/api/tracks/abc/stream");
    expect(b1).toBe(b2);
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(1);
    expect(cache.has("/api/tracks/abc/stream")).toBe(true);
  });

  it("de-duplicates concurrent loads of the same URL into one in-flight fetch", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    const [b1, b2, b3] = await Promise.all([
      cache.load("/api/tracks/xyz/stream"),
      cache.load("/api/tracks/xyz/stream"),
      cache.load("/api/tracks/xyz/stream"),
    ]);
    expect(b1).toBe(b2);
    expect(b2).toBe(b3);
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(1);
  });

  it("evict() removes a single entry so a subsequent load re-fetches", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/k/stream");
    cache.evict("/api/tracks/k/stream");
    expect(cache.has("/api/tracks/k/stream")).toBe(false);
    await cache.load("/api/tracks/k/stream");
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(2);
  });

  it("clear() empties everything", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/a/stream");
    await cache.load("/api/tracks/b/stream");
    cache.clear();
    expect(cache.has("/api/tracks/a/stream")).toBe(false);
    expect(cache.has("/api/tracks/b/stream")).toBe(false);
  });

  it("propagates fetch failures and does not poison the in-flight slot for retries", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    (globalThis.fetch as Mock).mockResolvedValueOnce({ ok: false, status: 500 });
    await expect(cache.load("/api/tracks/broken/stream")).rejects.toThrow(/HTTP 500/);
    // Subsequent retry must succeed (the failed in-flight entry was
    // cleared, so we go through the fresh fetch path).
    await expect(cache.load("/api/tracks/broken/stream")).resolves.toBeDefined();
  });
});
