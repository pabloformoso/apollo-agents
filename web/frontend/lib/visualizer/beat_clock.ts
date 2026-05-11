/**
 * beat_clock — pure functions that turn a track's beatgrid + the active
 * deck's ``audio.currentTime`` into a per-frame beat phase.
 *
 * The visualizer reads `BeatClockResult` every frame and uses ``phase_in_beat``
 * (a 0..1 ramp that resets on every beat) to drive particle pulses, strobe
 * flashes and fractal zoom. ``is_downbeat`` lets effects emphasise the bar
 * boundary (default 4 beats / bar).
 *
 * This module is a pure-function island — no DOM, no Three.js, no
 * ``window`` access — so it's trivial to unit-test.
 */

export interface BeatgridSpec {
  /** Track tempo in beats per minute. */
  bpm: number;
  /** Time (seconds) of the first beat downbeat in the audio file. */
  first_beat_sec: number;
}

export interface BeatClockResult {
  /** Integer count of beats elapsed since ``first_beat_sec``. */
  beat_index: number;
  /** Position within the current beat, in 0..1. */
  phase_in_beat: number;
  /** True at the start of each bar (every ``beats_per_bar`` beats). */
  is_downbeat: boolean;
}

/** Fallback no-op result used when inputs are unusable. */
const ZERO_BEAT: BeatClockResult = {
  beat_index: 0,
  phase_in_beat: 0,
  is_downbeat: false,
};

/**
 * Compute the beat clock for a given audio time.
 *
 * Edge cases:
 * - ``bpm <= 0``                     → returns zeros.
 * - ``current_time_sec`` < first beat → returns zeros (we haven't hit the
 *   first beat yet, so beat_index 0 is the natural answer).
 * - ``first_beat_sec`` in the future → handled by the same branch as above.
 *
 * The downbeat detection uses a tolerance window (~12% of the beat) so
 * effects can latch onto it even when the animation frame falls a frame or
 * two after the boundary. The 5% window we shipped originally was too tight
 * — at 120 BPM that's only 25 ms, less than 2 frames at 60 fps, so rAF
 * regularly missed it. 12% (~60 ms at 120 BPM) is still tight enough that
 * the flash feels musical but wide enough that no real downbeat slips
 * through. Any phase below the tolerance counts as the downbeat moment;
 * effects requiring a strict edge must dedupe by ``beat_index`` themselves.
 *
 * See issue #44 for the regression report.
 */
export const DOWNBEAT_PHASE_TOLERANCE = 0.12;

export function computeBeatClock(
  bpm: number,
  first_beat_sec: number,
  current_time_sec: number,
  beats_per_bar: number = 4,
): BeatClockResult {
  if (!Number.isFinite(bpm) || bpm <= 0) return ZERO_BEAT;
  if (!Number.isFinite(current_time_sec)) return ZERO_BEAT;
  if (!Number.isFinite(first_beat_sec)) return ZERO_BEAT;

  const seconds_per_beat = 60 / bpm;
  const elapsed = current_time_sec - first_beat_sec;
  if (elapsed < 0) return ZERO_BEAT;

  const total_beats = elapsed / seconds_per_beat;
  const beat_index = Math.floor(total_beats);
  const phase_in_beat = total_beats - beat_index;
  const bars = Math.max(1, beats_per_bar);
  const is_downbeat =
    beat_index % bars === 0 && phase_in_beat <= DOWNBEAT_PHASE_TOLERANCE;

  return { beat_index, phase_in_beat, is_downbeat };
}

/**
 * Convenience wrapper — returns the zero result when the beatgrid is
 * missing entirely. The visualizer falls back to onset detection (Web
 * Audio AnalyserNode) in that case; this stub keeps the call site clean.
 */
export function safeComputeBeatClock(
  beatgrid: BeatgridSpec | null | undefined,
  current_time_sec: number,
  beats_per_bar: number = 4,
): BeatClockResult {
  if (!beatgrid) return ZERO_BEAT;
  return computeBeatClock(
    beatgrid.bpm,
    beatgrid.first_beat_sec,
    current_time_sec,
    beats_per_bar,
  );
}
