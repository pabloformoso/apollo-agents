/**
 * audio_features — what the shader visuals "hear", as pure functions.
 *
 * Two sources feed the same ``AudioFeatures`` shape:
 *
 *   - ``bandsFromSpectrum``: a real ``AnalyserNode`` spectrum (the live
 *     master-bus tap in ``useLiveSession``, or the mic in the lab).
 *   - ``syntheticFeatures``: the beat clock alone, for surfaces with no
 *     analyser (a viewer before its first deck, the lab without a mic).
 *
 * Then ``followFeatures`` smooths them (fast attack, slow release) and
 * auto-gains each band against a slowly decaying peak, so a quiet healing
 * drone moves the picture as much as a techno kick does.
 *
 * ``beatEnvelopes`` turns the beat clock into the two pulses the shaders
 * use: ``kick`` on every beat and ``accent`` on every bar. ``accent`` is
 * the only thing allowed to brighten a large area of the screen, and it
 * fires once per bar — under 3 Hz for any tempo below 720 BPM, which keeps
 * the public broadcast inside the photosensitivity threshold the old
 * strobe enforced with a rate cap.
 *
 * No DOM, no three.js: everything here is unit-tested directly.
 */

import type { BeatClockResult } from "./beat_clock";

export interface AudioFeatures {
  /** 0..1 — kick / sub energy (~20-150 Hz). */
  bass: number;
  /** 0..1 — body: pads, vocals, chords (~150-2000 Hz). */
  mid: number;
  /** 0..1 — air: hats, shimmer (~2-10 kHz). */
  high: number;
  /** 0..1 — overall loudness. */
  level: number;
}

export const SILENT: AudioFeatures = { bass: 0, mid: 0, high: 0, level: 0 };

const BANDS = {
  bass: [20, 150],
  mid: [150, 2000],
  high: [2000, 10000],
} as const;

function bandMean(
  spectrum: ArrayLike<number>,
  hzPerBin: number,
  lo: number,
  hi: number,
): number {
  // Half-open [lo, hi): adjacent bands never share a bin. Bin 0 is DC.
  const from = Math.max(1, Math.floor(lo / hzPerBin));
  const to = Math.min(spectrum.length - 1, Math.floor(hi / hzPerBin) - 1);
  if (to < from) return 0;
  let sum = 0;
  for (let i = from; i <= to; i++) sum += spectrum[i];
  return sum / (to - from + 1) / 255;
}

/**
 * Average a byte spectrum (``getByteFrequencyData``) into three bands.
 * ``sampleRate / fftSize`` is the width of one bin.
 */
export function bandsFromSpectrum(
  spectrum: ArrayLike<number>,
  sampleRate: number,
  fftSize: number,
): AudioFeatures {
  if (!spectrum.length || !(sampleRate > 0) || !(fftSize > 0)) return SILENT;
  const hzPerBin = sampleRate / fftSize;
  const bass = bandMean(spectrum, hzPerBin, BANDS.bass[0], BANDS.bass[1]);
  const mid = bandMean(spectrum, hzPerBin, BANDS.mid[0], BANDS.mid[1]);
  const high = bandMean(spectrum, hzPerBin, BANDS.high[0], BANDS.high[1]);
  return { bass, mid, high, level: bass * 0.5 + mid * 0.35 + high * 0.15 };
}

export interface BeatEnvelopes {
  /** Continuous beat position (beat_index + phase) — drives motion. */
  beat: number;
  /** 1 on each beat, decaying through it. */
  kick: number;
  /** 1 on each bar's downbeat, decaying over ~a beat; 0 otherwise. */
  accent: number;
}

export function beatEnvelopes(beat: BeatClockResult, beatsPerBar = 4): BeatEnvelopes {
  const phase = Math.min(1, Math.max(0, beat.phase_in_beat));
  const onBar = beat.beat_index % Math.max(1, beatsPerBar) === 0;
  return {
    beat: beat.beat_index + phase,
    kick: Math.exp(-phase * 5),
    accent: onBar ? Math.exp(-phase * 3.5) : 0,
  };
}

/** What the picture should do when nothing is listening: breathe on the beat. */
export function syntheticFeatures(env: BeatEnvelopes): AudioFeatures {
  return {
    bass: 0.3 + 0.45 * env.kick,
    mid: 0.4 + 0.1 * Math.sin(env.beat * 0.25),
    high: 0.15 + 0.25 * env.kick,
    level: 0.45 + 0.2 * env.kick,
  };
}

export interface FollowerState {
  value: AudioFeatures;
  peak: AudioFeatures;
}

export function createFollower(): FollowerState {
  return { value: { ...SILENT }, peak: { bass: 0.2, mid: 0.2, high: 0.2, level: 0.2 } };
}

const KEYS = ["bass", "mid", "high", "level"] as const;
/** Seconds for the envelope to rise / fall ~63% of the way. */
const ATTACK_SEC = 0.03;
const RELEASE_SEC = 0.25;
/** Peak memory for auto-gain: decays ~to a third in ~8 s. */
const PEAK_DECAY_PER_SEC = 0.87;
const PEAK_FLOOR = 0.08;

/**
 * Advance the follower by ``dtSec`` towards ``raw`` and return features
 * normalised against each band's recent peak (so every band spans ~0..1
 * whatever the mastering level of the track).
 */
export function followFeatures(
  state: FollowerState,
  raw: AudioFeatures,
  dtSec: number,
): AudioFeatures {
  const dt = Math.min(0.25, Math.max(0, dtSec));
  const out = { ...SILENT };
  for (const k of KEYS) {
    const target = Math.min(1, Math.max(0, raw[k]));
    const cur = state.value[k];
    const tau = target > cur ? ATTACK_SEC : RELEASE_SEC;
    const next = cur + (target - cur) * (1 - Math.exp(-dt / tau));
    state.value[k] = next;
    const decayed = state.peak[k] * Math.pow(PEAK_DECAY_PER_SEC, dt);
    state.peak[k] = Math.max(PEAK_FLOOR, decayed, next);
    out[k] = Math.min(1, next / state.peak[k]);
  }
  return out;
}
