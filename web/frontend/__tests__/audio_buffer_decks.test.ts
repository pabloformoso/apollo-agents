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
  BufferDecodeError,
  BufferFetchError,
  BufferLoadTimeoutError,
  SCHEDULE_LOOKAHEAD_SEC,
  isSkippableLoadFailure,
} from "../lib/audio_buffer_decks";

// ── Fakes ────────────────────────────────────────────────────────────────

class FakeBufferSource {
  static instances: FakeBufferSource[] = [];
  static onendedHandlers: Map<FakeBufferSource, (() => void) | null> = new Map();

  buffer: AudioBuffer | null = null;
  playbackRate = {
    value: 1,
    cancelScheduledValues: vi.fn(),
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
  };
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

  // ── v3.9.10: position() integrates the rate curve ──────────────────
  //
  // It used to extrapolate from rateAtStart forever. Under grid-warp the
  // deck starts on the FIRST BAR's lock rate, steps per bar through the
  // overlap, then ramps back to native — so holding that first value
  // biased every reported position for the rest of the track. The backend
  // uses that position to decide when to fire the next crossfade and
  // whether a deck has stalled, so the bias was not cosmetic.

  it("position follows a stepped schedule instead of holding rateAtStart", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 10.0;
    audioCtx.currentTime = when;
    deck.scheduleSource(buf, when, 0, 0.5, "t");
    deck.applyRateSchedule(
      [
        { at_sec: 0, rate: 0.5, ramp: false },
        { at_sec: 10, rate: 1.5, ramp: false },
      ],
      when,
    );
    // 10 s at 0.5 = 5 media-seconds, then 10 s at 1.5 = 15 more.
    audioCtx.currentTime = when + 10;
    expect(deck.position()).toBeCloseTo(5.0, 6);
    audioCtx.currentTime = when + 20;
    expect(deck.position()).toBeCloseTo(20.0, 6);
  });

  it("position averages a linear ramp rather than jumping at its end", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 4.0;
    audioCtx.currentTime = when;
    deck.scheduleSource(buf, when, 0, 1.0, "t");
    // Glide 1.0 -> 2.0 across 10 s: mean 1.5, so 15 media-seconds.
    deck.applyRateSchedule([{ at_sec: 10, rate: 2.0, ramp: true }], when);
    audioCtx.currentTime = when + 10;
    expect(deck.position()).toBeCloseTo(15.0, 6);
    // Halfway in, the rate has only reached 1.5 — mean 1.25 over 5 s.
    audioCtx.currentTime = when + 5;
    expect(deck.position()).toBeCloseTo(6.25, 6);
  });

  it("position holds the last segment's rate past the end of the schedule", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 0.0;
    audioCtx.currentTime = when;
    deck.scheduleSource(buf, when, 0, 2.0, "t");
    deck.applyRateSchedule([{ at_sec: 2, rate: 1.0, ramp: false }], when);
    // 2 s at 2.0 = 4, then 8 s at 1.0 = 8.
    audioCtx.currentTime = when + 10;
    expect(deck.position()).toBeCloseTo(12.0, 6);
  });

  it("position respects the start offset when a schedule is present", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 1.0;
    audioCtx.currentTime = when;
    deck.scheduleSource(buf, when, 30.0, 1.0, "t");
    deck.applyRateSchedule([{ at_sec: 5, rate: 1.0, ramp: false }], when);
    audioCtx.currentTime = when + 10;
    expect(deck.position()).toBeCloseTo(40.0, 6);
  });

  it("position keeps the plain rateAtStart path when no schedule was applied", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 2.0;
    audioCtx.currentTime = when;
    deck.scheduleSource(buf, when, 1.875, 1.0667, "t");
    audioCtx.currentTime = when + 10;
    expect(deck.position()).toBeCloseTo(1.875 + 10 * 1.0667, 6);
  });

  it("a fresh source drops the previous source's schedule", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf1 = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const buf2 = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 0;
    deck.scheduleSource(buf1, 0, 0, 1.0, "t1");
    deck.applyRateSchedule([{ at_sec: 1, rate: 0.5, ramp: false }], 0);
    // New track on the same deck: back to the plain path at its own rate.
    deck.scheduleSource(buf2, 0, 0, 1.0, "t2");
    audioCtx.currentTime = 10;
    expect(deck.position()).toBeCloseTo(10.0, 6);
  });

  it("applyRateSchedule schedules stepped per-bar rates against the same when clock", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    const when = 10.05;
    deck.scheduleSource(buf, when, 1.875, 1.0667, "track-A");
    const src = FakeBufferSource.instances[0];
    deck.applyRateSchedule(
      [
        { at_sec: 0, rate: 1.0667, ramp: false },
        { at_sec: 1.875, rate: 1.0667, ramp: false },
        { at_sec: 3.75, rate: 1.0667, ramp: false },
      ],
      when,
    );
    expect(src.playbackRate.cancelScheduledValues).toHaveBeenCalledWith(when);
    expect(src.playbackRate.setValueAtTime).toHaveBeenCalledWith(1.0667, when + 0);
    expect(src.playbackRate.setValueAtTime).toHaveBeenCalledWith(1.0667, when + 1.875);
    expect(src.playbackRate.setValueAtTime).toHaveBeenCalledWith(1.0667, when + 3.75);
    expect(src.playbackRate.linearRampToValueAtTime).not.toHaveBeenCalled();
  });

  it("applyRateSchedule uses linearRamp for the release glide segment", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 5.0, 0, 1.05, "t");
    const src = FakeBufferSource.instances[0];
    deck.applyRateSchedule(
      [
        { at_sec: 0, rate: 1.05, ramp: false },
        { at_sec: 12, rate: 1.05, ramp: false },
        { at_sec: 28, rate: 1.0, ramp: true },
      ],
      5.0,
    );
    // Release glide back to native rate at when + xfade + ramp.
    expect(src.playbackRate.linearRampToValueAtTime).toHaveBeenCalledWith(1.0, 5.0 + 28);
  });

  it("applyRateSchedule is a no-op with no source or an empty schedule", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    // No source scheduled yet — must not throw.
    expect(() => deck.applyRateSchedule([{ at_sec: 0, rate: 1.1 }], 1.0)).not.toThrow();
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    deck.scheduleSource(buf, 1.0, 0, 1.0, "t");
    const src = FakeBufferSource.instances[0];
    deck.applyRateSchedule([], 1.0);
    deck.applyRateSchedule(undefined, 1.0);
    expect(src.playbackRate.setValueAtTime).not.toHaveBeenCalled();
  });

  // --- W3: momentary pitch-bend (nudgeRate) -------------------------------
  it("nudgeRate bumps the live source rate then ramps back to base", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 3.0;
    deck.scheduleSource(buf, 3.0, 0, 1.0, "t"); // base rate 1.0
    const src = FakeBufferSource.instances[0];
    deck.nudgeRate(1.02, 0.25);
    // Bumps to base*rate now, ramps back to base after hold.
    expect(src.playbackRate.setValueAtTime).toHaveBeenCalledWith(1.02, 3.0);
    expect(src.playbackRate.linearRampToValueAtTime).toHaveBeenCalledWith(1.0, 3.25);
  });

  it("nudgeRate scales against the deck's base rate, not absolute", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    const buf = new FakeAudioBuffer(240) as unknown as AudioBuffer;
    audioCtx.currentTime = 0;
    deck.scheduleSource(buf, 0, 0, 1.05, "t"); // base rate 1.05 (tempo-matched)
    const src = FakeBufferSource.instances[0];
    deck.nudgeRate(1.02, 0.25);
    expect(src.playbackRate.setValueAtTime).toHaveBeenCalledWith(1.05 * 1.02, 0);
    expect(src.playbackRate.linearRampToValueAtTime).toHaveBeenCalledWith(1.05, 0.25);
  });

  it("nudgeRate is a no-op with no source playing", () => {
    const deck = new BufferDeck(audioCtx as unknown as AudioContext, 0);
    expect(() => deck.nudgeRate(1.02)).not.toThrow();
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

// ── v3.9 — load-failure taxonomy ──────────────────────────────────────────

describe("BufferCache load-failure taxonomy (v3.9)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(8),
      })),
    );
  });

  it("HTTP errors reject with BufferFetchError (NOT skip-worthy)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    (globalThis.fetch as Mock).mockResolvedValueOnce({ ok: false, status: 404 });
    const err = await cache.load("/api/tracks/e404/stream").catch((e) => e);
    expect(err).toBeInstanceOf(BufferFetchError);
    expect(String(err)).toMatch(/HTTP 404/);
    expect(isSkippableLoadFailure(err)).toBe(false);
  });

  it("network-level fetch rejections reject with BufferFetchError", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    (globalThis.fetch as Mock).mockRejectedValueOnce(new TypeError("net down"));
    const err = await cache.load("/api/tracks/net/stream").catch((e) => e);
    expect(err).toBeInstanceOf(BufferFetchError);
    expect(isSkippableLoadFailure(err)).toBe(false);
  });

  it("decode rejections reject with BufferDecodeError (skip-worthy)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    audioCtx.decodeAudioData.mockImplementationOnce(
      (_buf: ArrayBuffer, _ok?: (b: AudioBuffer) => void, errCb?: (e: Error) => void) => {
        const failure = new Error("EncodingError: Unable to decode audio data");
        if (errCb) errCb(failure);
        return Promise.reject(failure);
      },
    );
    const err = await cache.load("/api/tracks/undecodable/stream").catch((e) => e);
    expect(err).toBeInstanceOf(BufferDecodeError);
    expect(isSkippableLoadFailure(err)).toBe(true);
    // A retry is not poisoned by the failed entry.
    await expect(cache.load("/api/tracks/undecodable/stream")).resolves.toBeDefined();
  });

  it("isSkippableLoadFailure is false for arbitrary errors", () => {
    expect(isSkippableLoadFailure(new Error("boom"))).toBe(false);
    expect(isSkippableLoadFailure(undefined)).toBe(false);
    expect(isSkippableLoadFailure("string")).toBe(false);
  });
});

// ── v3.9 — decode timeout ─────────────────────────────────────────────────

describe("BufferCache.load timeout (v3.9)", () => {
  /** decodeAudioData that never settles until told to — the 2026-08-01
   *  wedge in miniature. */
  let releaseDecode: ((b: AudioBuffer) => void) | null;

  beforeEach(() => {
    releaseDecode = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(8),
      })),
    );
    audioCtx.decodeAudioData.mockImplementation(
      (_buf: ArrayBuffer, ok?: (b: AudioBuffer) => void) => {
        return new Promise<AudioBuffer>((resolve) => {
          releaseDecode = (b: AudioBuffer) => {
            if (ok) ok(b);
            resolve(b);
          };
        });
      },
    );
  });

  it("a hung decode rejects with BufferLoadTimeoutError after timeoutMs", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    const err = await cache.load("/api/tracks/hung/stream", 20).catch((e) => e);
    expect(err).toBeInstanceOf(BufferLoadTimeoutError);
    expect(isSkippableLoadFailure(err)).toBe(true);
  });

  it("timeoutMs = 0 disables the deadline (caller waits for the decode)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    const pending = cache.load("/api/tracks/slow/stream", 0);
    // Give fetch+arrayBuffer microtasks time to reach the decode stage.
    await new Promise((r) => setTimeout(r, 10));
    releaseDecode!(new FakeAudioBuffer(240) as unknown as AudioBuffer);
    await expect(pending).resolves.toBeDefined();
  });

  it("a retry after timeout joins the SAME in-flight load (no duplicate fetch)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await expect(cache.load("/api/tracks/wedge/stream", 20)).rejects.toBeInstanceOf(
      BufferLoadTimeoutError,
    );
    const retry = cache.load("/api/tracks/wedge/stream", 1000);
    await new Promise((r) => setTimeout(r, 10));
    releaseDecode!(new FakeAudioBuffer(240) as unknown as AudioBuffer);
    await expect(retry).resolves.toBeDefined();
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(1);
  });

  it("a load that resolves late (after a caller timed out) still lands in the cache", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await expect(cache.load("/api/tracks/late/stream", 20)).rejects.toBeInstanceOf(
      BufferLoadTimeoutError,
    );
    releaseDecode!(new FakeAudioBuffer(240) as unknown as AudioBuffer);
    // Let the underlying load's continuation run.
    await new Promise((r) => setTimeout(r, 10));
    expect(cache.has("/api/tracks/late/stream")).toBe(true);
    // And a fresh load is a pure cache hit — no second fetch.
    await expect(cache.load("/api/tracks/late/stream", 20)).resolves.toBeDefined();
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(1);
  });
});

// ── v3.9 — prune (working-set bound) ──────────────────────────────────────

describe("BufferCache.prune (v3.9)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(8),
      })),
    );
  });

  it("evicts everything not in keepUrls and reports the count", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/t1/stream");
    await cache.load("/api/tracks/t2/stream");
    await cache.load("/api/tracks/t3/stream");
    const evicted = cache.prune(["/api/tracks/t2/stream"]);
    expect(evicted).toBe(2);
    expect(cache.has("/api/tracks/t1/stream")).toBe(false);
    expect(cache.has("/api/tracks/t2/stream")).toBe(true);
    expect(cache.has("/api/tracks/t3/stream")).toBe(false);
  });

  it("keeps multiple URLs (current + preloaded next)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/cur/stream");
    await cache.load("/api/tracks/next/stream");
    await cache.load("/api/tracks/old/stream");
    cache.prune(["/api/tracks/cur/stream", "/api/tracks/next/stream"]);
    expect(cache.has("/api/tracks/cur/stream")).toBe(true);
    expect(cache.has("/api/tracks/next/stream")).toBe(true);
    expect(cache.has("/api/tracks/old/stream")).toBe(false);
  });

  it("is a no-op (returns 0) when everything is in the keep set", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/only/stream");
    expect(cache.prune(["/api/tracks/only/stream"])).toBe(0);
    expect(cache.has("/api/tracks/only/stream")).toBe(true);
  });

  it("an evicted URL re-fetches on the next load (no stale poisoning)", async () => {
    const cache = new BufferCache(audioCtx as unknown as AudioContext);
    await cache.load("/api/tracks/gone/stream");
    cache.prune([]);
    await cache.load("/api/tracks/gone/stream");
    expect((globalThis.fetch as Mock).mock.calls.length).toBe(2);
  });
});
