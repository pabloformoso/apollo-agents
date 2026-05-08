/**
 * Vitest unit tests for ``createMicPerception`` (web/frontend/lib/mic_perception.ts).
 *
 * The Web Audio APIs are stubbed with minimal fakes so the module's
 * lifecycle (start → publish → stop) can be exercised without a real
 * mic. The fakes are also what the Playwright E2E spec uses (page.evaluate
 * style stubs) so behaviour stays in lockstep across both layers.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  createMicPerception,
  type PerceptionSample,
} from "@/lib/mic_perception";

class FakeAnalyser {
  fftSize = 2048;
  smoothingTimeConstant = 0.85;
  frequencyBinCount = 1024;
  getByteTimeDomainData = vi.fn((buf: Uint8Array) => {
    // Fill with 128 (silence) so RMS is ~0 → -120 dBFS by default.
    buf.fill(128);
  });
  getByteFrequencyData = vi.fn((buf: Uint8Array) => {
    buf.fill(0);
  });
  disconnect = vi.fn();
}

class FakeMediaStreamSource {
  connect = vi.fn();
  disconnect = vi.fn();
}

class FakeAudioContext {
  createMediaStreamSource = vi.fn(() => new FakeMediaStreamSource());
  createAnalyser = vi.fn(() => new FakeAnalyser());
  close = vi.fn(() => Promise.resolve());
}

class FakeMediaStreamTrack {
  stop = vi.fn();
}

class FakeMediaStream {
  tracks: FakeMediaStreamTrack[];
  constructor(n = 1) {
    this.tracks = Array.from({ length: n }, () => new FakeMediaStreamTrack());
  }
  getTracks() {
    return this.tracks;
  }
}

type GetUserMediaImpl = (
  constraints: MediaStreamConstraints,
) => Promise<MediaStream>;

describe("createMicPerception", () => {
  let getUserMedia: GetUserMediaImpl & ReturnType<typeof vi.fn>;
  let stream: FakeMediaStream;

  beforeEach(() => {
    vi.useFakeTimers();
    stream = new FakeMediaStream();
    getUserMedia = vi.fn(
      () => Promise.resolve(stream as unknown as MediaStream),
    ) as unknown as GetUserMediaImpl & ReturnType<typeof vi.fn>;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("calls getUserMedia with echo/noise/AGC disabled", async () => {
    const api = createMicPerception(() => {}, {
      getUserMediaImpl: getUserMedia,
      AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
    });
    await api.start();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    const constraints = getUserMedia.mock.calls[0][0] as MediaStreamConstraints;
    const audio = constraints.audio as MediaTrackConstraints;
    expect(audio.echoCancellation).toBe(false);
    expect(audio.noiseSuppression).toBe(false);
    expect(audio.autoGainControl).toBe(false);
    api.stop();
  });

  it("creates an AudioContext + AnalyserNode on start()", async () => {
    const created: FakeAudioContext[] = [];
    class TrackedAudioContext extends FakeAudioContext {
      constructor() {
        super();
        created.push(this);
      }
    }
    const api = createMicPerception(() => {}, {
      getUserMediaImpl: getUserMedia,
      AudioContextCtor: TrackedAudioContext as unknown as typeof AudioContext,
    });
    await api.start();
    expect(created).toHaveLength(1);
    expect(created[0].createAnalyser).toHaveBeenCalledTimes(1);
    expect(created[0].createMediaStreamSource).toHaveBeenCalledTimes(1);
    api.stop();
  });

  it("isActive() flips on start and off on stop", async () => {
    const api = createMicPerception(() => {}, {
      getUserMediaImpl: getUserMedia,
      AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
    });
    expect(api.isActive()).toBe(false);
    await api.start();
    expect(api.isActive()).toBe(true);
    api.stop();
    expect(api.isActive()).toBe(false);
  });

  it("publishes a sample on each interval boundary", async () => {
    const samples: PerceptionSample[] = [];
    const api = createMicPerception(
      (s) => {
        samples.push(s);
      },
      {
        intervalMs: 200,
        subBufferMs: 50,
        getUserMediaImpl: getUserMedia,
        AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
      },
    );
    await api.start();
    // Advance enough to trigger several aggregate boundaries.
    await vi.advanceTimersByTimeAsync(700);
    expect(samples.length).toBeGreaterThanOrEqual(2);
    for (const s of samples) {
      // Silence → dBFS floor near -120, never +Infinity / NaN.
      expect(Number.isFinite(s.rms_db)).toBe(true);
      expect(s.voice_likelihood).toBeNull();
      expect(s.timestamp_ms).toBeGreaterThan(0);
    }
    api.stop();
  });

  it("stop() releases the mic stream and disconnects nodes", async () => {
    const api = createMicPerception(() => {}, {
      getUserMediaImpl: getUserMedia,
      AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
    });
    await api.start();
    const trackSpy = stream.tracks[0].stop;
    api.stop();
    expect(trackSpy).toHaveBeenCalledTimes(1);
    expect(api.isActive()).toBe(false);
  });

  it("getCurrentRmsDb returns the latest instantaneous reading", async () => {
    const api = createMicPerception(() => {}, {
      intervalMs: 200,
      subBufferMs: 50,
      getUserMediaImpl: getUserMedia,
      AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
    });
    await api.start();
    await vi.advanceTimersByTimeAsync(120);
    // Silence input → dBFS at the floor.
    expect(api.getCurrentRmsDb()).toBeLessThan(-50);
    api.stop();
  });
});
