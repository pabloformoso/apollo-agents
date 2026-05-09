"use client";
/**
 * mic_perception — client-side ambient mic capture + aggregated metrics.
 *
 * v2.5.2 turns LiveDJ into a real DJ that listens to the room. To keep the
 * privacy story honest the raw audio NEVER leaves the browser — this
 * module captures the mic stream, runs an ``AnalyserNode`` over it
 * locally, and publishes only the small aggregated ``PerceptionSample``
 * shape every ``intervalMs`` (default 2 s).
 *
 * Pipeline:
 *   1. ``getUserMedia`` with all the smart-processing options OFF
 *      (no echo cancel, no noise suppression, no auto-gain). We want the
 *      ambient signal, not a phone-call cleanup.
 *   2. ``AudioContext`` → ``MediaStreamSource`` → ``AnalyserNode``
 *      (FFT 2048, 0.85 smoothing).
 *   3. Every 100 ms: read time-domain bytes, compute RMS (dBFS).
 *      Every 100 ms: read frequency bytes, compute spectral flux for
 *      onset detection.
 *   4. On each ``intervalMs`` boundary aggregate the sub-buffers into a
 *      sample and call ``publish(sample)``.
 *
 * VAD: kept optional. The plan calls for a tiny WASM (e.g.
 * ``webrtcvad-wasm``) — we ship without it in v2.5.2 and surface
 * ``voice_likelihood: null``. The agent's ``get_perception_window`` tool
 * already handles the null case and the prompt only treats voice as a
 * secondary signal alongside the dB delta.
 *
 * Privacy: raw bytes stay in the browser. Only mean RMS dB, onset
 * density (Hz), and voice likelihood (currently null) are published.
 */

export interface PerceptionSample {
  /** Mean RMS of the last `intervalMs` window, in dBFS (negative). */
  rms_db: number;
  /** Onset events per second over the same window. */
  onset_density_hz: number;
  /** 0–1 voice activity likelihood, or null when no VAD is loaded. */
  voice_likelihood: number | null;
  /** Browser ``Date.now()`` when the sample was published. */
  timestamp_ms: number;
}

export interface MicPerceptionApi {
  /** Open the mic and start the aggregation pipeline. */
  start: () => Promise<void>;
  /** Stop the pipeline, disconnect nodes, release the mic stream. */
  stop: () => void;
  /** True between successful ``start()`` and ``stop()``. */
  isActive: () => boolean;
  /** Most recent instantaneous RMS in dBFS — drives the UI level meter. */
  getCurrentRmsDb: () => number;
}

export interface CreateMicPerceptionOptions {
  /** How often (ms) ``publish`` is called. Default 2 000 ms. */
  intervalMs?: number;
  /** How often (ms) the inner sub-buffers sample the analyser. Default 100. */
  subBufferMs?: number;
  /** Override for tests — defaults to ``navigator.mediaDevices``. */
  getUserMediaImpl?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  /** Override for tests — defaults to ``window.AudioContext``. */
  AudioContextCtor?: typeof AudioContext;
}

const DEFAULT_INTERVAL_MS = 2000;
const DEFAULT_SUB_BUFFER_MS = 100;
const FFT_SIZE = 2048;
const SILENCE_FLOOR_DB = -120;

/**
 * Convert a 0..1 RMS amplitude into dBFS, clamping silence to a sane
 * floor so a fully silent buffer doesn't produce ``-Infinity``.
 */
function rmsToDb(rms: number): number {
  if (!Number.isFinite(rms) || rms <= 0) return SILENCE_FLOOR_DB;
  return Math.max(SILENCE_FLOOR_DB, 20 * Math.log10(rms));
}

/**
 * Compute RMS amplitude (0..1) from a Uint8Array of time-domain samples.
 * Web Audio's ``getByteTimeDomainData`` returns 0..255 with 128 = silence.
 */
function timeDomainRms(buf: Uint8Array): number {
  if (buf.length === 0) return 0;
  let sumSq = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sumSq += v * v;
  }
  return Math.sqrt(sumSq / buf.length);
}

/**
 * Spectral flux between two frequency snapshots — sum of positive
 * magnitude differences. Used as a cheap onset proxy.
 */
function spectralFlux(prev: Uint8Array, cur: Uint8Array): number {
  if (prev.length === 0 || cur.length !== prev.length) return 0;
  let flux = 0;
  for (let i = 0; i < cur.length; i++) {
    const d = cur[i] - prev[i];
    if (d > 0) flux += d;
  }
  return flux / cur.length;
}

export function createMicPerception(
  publish: (sample: PerceptionSample) => void,
  options: CreateMicPerceptionOptions = {},
): MicPerceptionApi {
  const intervalMs = options.intervalMs ?? DEFAULT_INTERVAL_MS;
  const subBufferMs = options.subBufferMs ?? DEFAULT_SUB_BUFFER_MS;

  let active = false;
  let stream: MediaStream | null = null;
  let ctx: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let analyser: AnalyserNode | null = null;
  let subBufferTimer: ReturnType<typeof setInterval> | null = null;
  let publishTimer: ReturnType<typeof setInterval> | null = null;

  // The Web Audio analyser typings require ``Uint8Array<ArrayBuffer>`` on
  // recent TS lib.dom — declare explicitly so allocations from
  // ``new Uint8Array(N)`` (which produce ``Uint8Array<ArrayBuffer>``) line
  // up with what ``getByteTimeDomainData`` expects.
  let timeBuf: Uint8Array<ArrayBuffer> | null = null;
  let freqBuf: Uint8Array<ArrayBuffer> | null = null;
  let prevFreqBuf: Uint8Array<ArrayBuffer> | null = null;

  const rmsSamples: number[] = [];
  let onsetCount = 0;
  let currentRmsDb = SILENCE_FLOOR_DB;
  // The flux threshold is heuristic — anything large enough to feel like
  // a transient. Tuned for `getByteFrequencyData` (0..255) so threshold
  // sits around the RMS of a sustained dance kick versus background.
  const FLUX_ONSET_THRESHOLD = 6;

  function readSubBuffer() {
    if (!analyser || !timeBuf || !freqBuf) return;
    analyser.getByteTimeDomainData(timeBuf);
    const rms = timeDomainRms(timeBuf);
    const db = rmsToDb(rms);
    rmsSamples.push(db);
    currentRmsDb = db;

    analyser.getByteFrequencyData(freqBuf);
    if (prevFreqBuf) {
      const flux = spectralFlux(prevFreqBuf, freqBuf);
      if (flux >= FLUX_ONSET_THRESHOLD) onsetCount += 1;
    } else {
      prevFreqBuf = new Uint8Array(freqBuf.length);
    }
    prevFreqBuf.set(freqBuf);
  }

  function aggregateAndPublish() {
    if (!active) return;
    const meanDb =
      rmsSamples.length > 0
        ? rmsSamples.reduce((a, b) => a + b, 0) / rmsSamples.length
        : SILENCE_FLOOR_DB;
    const onsetHz = (onsetCount * 1000) / intervalMs;

    publish({
      rms_db: Number.isFinite(meanDb) ? meanDb : SILENCE_FLOOR_DB,
      onset_density_hz: Number.isFinite(onsetHz) ? onsetHz : 0,
      // VAD WASM not loaded in v2.5.2 — the agent treats null gracefully.
      voice_likelihood: null,
      timestamp_ms: Date.now(),
    });

    rmsSamples.length = 0;
    onsetCount = 0;
  }

  async function start() {
    if (active) return;
    if (typeof window === "undefined") {
      throw new Error("mic perception is only available in the browser");
    }
    const getMedia =
      options.getUserMediaImpl ??
      ((constraints) =>
        navigator.mediaDevices.getUserMedia(constraints));
    stream = await getMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });

    const Ctor =
      options.AudioContextCtor ??
      (window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext);
    if (!Ctor) {
      // Roll back the open mic — the caller should never see a partial
      // start where audio is captured but no analysis runs.
      try {
        for (const t of stream.getTracks()) t.stop();
      } catch {
        /* ignore */
      }
      stream = null;
      throw new Error("AudioContext is not available in this browser");
    }
    ctx = new Ctor();
    source = ctx.createMediaStreamSource(stream);
    analyser = ctx.createAnalyser();
    analyser.fftSize = FFT_SIZE;
    analyser.smoothingTimeConstant = 0.85;
    source.connect(analyser);

    timeBuf = new Uint8Array(analyser.fftSize);
    freqBuf = new Uint8Array(analyser.frequencyBinCount);
    prevFreqBuf = null;
    rmsSamples.length = 0;
    onsetCount = 0;
    currentRmsDb = SILENCE_FLOOR_DB;

    subBufferTimer = setInterval(readSubBuffer, subBufferMs);
    publishTimer = setInterval(aggregateAndPublish, intervalMs);
    active = true;
  }

  function stop() {
    active = false;
    if (subBufferTimer !== null) {
      clearInterval(subBufferTimer);
      subBufferTimer = null;
    }
    if (publishTimer !== null) {
      clearInterval(publishTimer);
      publishTimer = null;
    }
    try {
      source?.disconnect();
    } catch {
      /* ignore */
    }
    try {
      analyser?.disconnect();
    } catch {
      /* ignore */
    }
    if (stream) {
      try {
        for (const t of stream.getTracks()) t.stop();
      } catch {
        /* ignore */
      }
      stream = null;
    }
    if (ctx) {
      try {
        const closed = ctx.close();
        if (closed && typeof closed.catch === "function") {
          closed.catch(() => {
            /* ignore — already closed */
          });
        }
      } catch {
        /* ignore */
      }
      ctx = null;
    }
    source = null;
    analyser = null;
    timeBuf = null;
    freqBuf = null;
    prevFreqBuf = null;
  }

  return {
    start,
    stop,
    isActive: () => active,
    getCurrentRmsDb: () => currentRmsDb,
  };
}
