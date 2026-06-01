/**
 * Sample-accurate two-deck audio playback for Apollo's live engine.
 *
 * v3.4 — replaces the HTMLAudioElement + MediaElementAudioSourceNode
 * substrate that v2.x and v3.0–v3.3 used. That substrate was the
 * proximate cause of the 10–50 ms "cabalgar" / phase-walk we were
 * hearing on 4/4 deep house transitions:
 *
 *   - HTMLAudioElement's currentTime seek is quantised to MP3 frame
 *     boundaries (~26 ms) — so even when the backend ships
 *     incoming_anchor_sec at sample precision, the browser landed on
 *     the nearest packet boundary, not the kick downbeat.
 *   - HTMLAudioElement.play() returns a Promise that resolves at an
 *     unknown wall-clock delay past AudioContext.currentTime. The
 *     gain ramp scheduled at currentTime *after* await therefore
 *     started a handful of milliseconds late relative to the actual
 *     audio output, drifting the two decks apart.
 *
 * The W3C Web Audio 1.1 spec (confirmed via deep-research,
 * https://www.w3.org/TR/webaudio-1.1/) defines AudioBufferSourceNode
 * with sample-accurate start(when, offset) on the dedicated audio
 * rendering thread, which shares its clock with AudioParam
 * automation (setValueAtTime, linearRampToValueAtTime, etc.). By
 * decoding tracks to memory-resident AudioBuffers (decodeAudioData
 * loses MP3 frame quantisation since the result is plain PCM at the
 * context's sample rate) and scheduling source + gain + filter
 * automation at the SAME future AudioContext time, we get all three
 * locked on the same sample clock — eliminating the cabalgar by
 * construction rather than chasing it with empirical offsets.
 *
 * The trade-off vs the prior substrate is memory: a 4-minute stereo
 * track decoded at 44.1 kHz float32 is ~84 MB. We hold at most two
 * buffers (one per deck) plus a one-track preload cache, so peak
 * usage is bounded around ~250 MB during a transition. That's
 * acceptable for the browser playback context.
 *
 * The module is intentionally framework-free — no React, no
 * Apollo-specific state. live.ts owns the WS-driven state machine
 * and uses these primitives as the bottom playback layer.
 */

/**
 * Forward-scheduling slack used when planning a transition.
 *
 * AudioBufferSourceNode.start(when, offset) is sample-accurate IF
 * ``when`` is in the future when the audio thread processes the
 * scheduling block (~128-sample = ~2.7 ms quantum @ 48 kHz). Using
 * the AudioContext's currentTime directly puts ``when`` in the past
 * the moment the call returns — leading to dropped samples or, in
 * implementation-specific cases, an immediate start (not what we
 * want). 50 ms is conservative but well below human perception of
 * latency, and gives the rendering thread plenty of slack to pick
 * up the scheduled event without missing it.
 */
export const SCHEDULE_LOOKAHEAD_SEC = 0.05;

/**
 * Decoded-buffer cache keyed by stream URL.
 *
 * decodeAudioData is async and can take 0.5–2 s for a typical
 * 3–4 minute track on slower hardware. live.ts preloads the next
 * track's buffer during the APPROACHING_CF window (~30 s before
 * the crossfade) so the actual transition can schedule synchronously
 * with no wait. The cache also de-duplicates concurrent loads for
 * the same URL — a frequent need when both the preload and the
 * actual crossfade call into load() in quick succession.
 */
export class BufferCache {
  private readonly cache = new Map<string, AudioBuffer>();
  private readonly inflight = new Map<string, Promise<AudioBuffer>>();

  constructor(private readonly audioCtx: AudioContext) {}

  /**
   * Fetch ``url`` as bytes, decode to a PCM AudioBuffer at the
   * context's native rate, and cache. Concurrent calls for the same
   * URL share a single in-flight promise.
   */
  async load(url: string): Promise<AudioBuffer> {
    const cached = this.cache.get(url);
    if (cached) return cached;
    const inflight = this.inflight.get(url);
    if (inflight) return inflight;
    const promise = (async () => {
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          throw new Error(`Buffer fetch failed: HTTP ${resp.status}`);
        }
        const arrayBuffer = await resp.arrayBuffer();
        // decodeAudioData has two signatures — the Promise form is
        // the modern one; some older Safaris still need callbacks.
        // We bridge defensively so the same call site works on both.
        const buffer = await new Promise<AudioBuffer>((resolve, reject) => {
          const maybe = this.audioCtx.decodeAudioData(
            arrayBuffer,
            resolve,
            reject,
          );
          // Modern Chromium / Firefox / Safari return a Promise
          // *and* still invoke the callbacks — the dual contract is
          // baked into the spec for back-compat. Take whichever
          // resolves first.
          if (maybe && typeof (maybe as Promise<AudioBuffer>).then === "function") {
            (maybe as Promise<AudioBuffer>).then(resolve, reject);
          }
        });
        this.cache.set(url, buffer);
        return buffer;
      } finally {
        // Always clear in-flight, success or failure — a retry should
        // not be blocked by a stale rejected promise sitting in the
        // map.
        this.inflight.delete(url);
      }
    })();
    this.inflight.set(url, promise);
    return promise;
  }

  /** Drop a single entry to free its decoded PCM (~10–100 MB). */
  evict(url: string): void {
    this.cache.delete(url);
  }

  /** Drop everything. Called on session end / hook unmount. */
  clear(): void {
    this.cache.clear();
    this.inflight.clear();
  }

  /** Test/diagnostic helper — does NOT trigger a load. */
  has(url: string): boolean {
    return this.cache.has(url);
  }
}

/**
 * One playback deck. Owns a permanent gain + highpass filter chain
 * connected to the AudioContext destination, and a single transient
 * AudioBufferSourceNode that is REPLACED on each play (sources are
 * single-use per the Web Audio spec).
 *
 * The filter defaults to a 20 Hz highpass (effectively a
 * pass-through — well below the audible / playback rolloff) so
 * SMOOTH_BLEND transitions hear no EQ artefact. The bass_swap
 * transition style automates this filter's cutoff to ~120 Hz during
 * the crossfade and snaps it back open on the drop downbeat.
 */
export class BufferDeck {
  readonly gain: GainNode;
  readonly filter: BiquadFilterNode | null;

  private source: AudioBufferSourceNode | null = null;
  private bufferRef: AudioBuffer | null = null;
  private startedAt = 0;
  private offsetAtStart = 0;
  private rateAtStart = 1;
  private trackId: string | null = null;

  /**
   * @param audioCtx The application's AudioContext. Decks share it.
   * @param initialGain Starting gain. Use 1 for the deck that begins
   *   audible, 0 for the deck that begins silent (crossfade target).
   * @param withFilter If false, skip the biquad — for test mocks
   *   that don't implement createBiquadFilter.
   */
  constructor(
    private readonly audioCtx: AudioContext,
    initialGain: number = 0,
    withFilter: boolean = true,
  ) {
    this.gain = audioCtx.createGain();
    this.gain.gain.value = initialGain;
    let filter: BiquadFilterNode | null = null;
    if (withFilter) {
      try {
        filter = audioCtx.createBiquadFilter();
        filter.type = "highpass";
        filter.frequency.value = 20;
        filter.Q.value = 0.7;
      } catch {
        // Fall through — older / mocked AudioContexts that don't
        // implement createBiquadFilter still get a usable deck via
        // the direct gain → destination wiring below.
        filter = null;
      }
    }
    this.filter = filter;
    if (filter) {
      filter.connect(this.gain);
    }
    this.gain.connect(audioCtx.destination);
  }

  /** True iff a source has been scheduled and hasn't ended/been stopped. */
  isPlaying(): boolean {
    return this.source !== null;
  }

  /** Track id of the currently scheduled source, or null. */
  getTrackId(): string | null {
    return this.trackId;
  }

  /**
   * Schedule a fresh source playing ``buffer`` from ``offsetSec``
   * within the buffer, at ``rate`` playback speed, starting at
   * AudioContext time ``whenSec``. Stops any prior source on this
   * deck first.
   *
   * The caller is responsible for ensuring ``whenSec`` is at least
   * SCHEDULE_LOOKAHEAD_SEC in the future relative to
   * audioCtx.currentTime — see the module-level constant doc for why.
   *
   * Returns the same ``whenSec`` so callers can chain gain/filter
   * automation against the exact same audio-thread time.
   */
  scheduleSource(
    buffer: AudioBuffer,
    whenSec: number,
    offsetSec: number,
    rate: number,
    trackId: string,
    onEnded?: () => void,
  ): number {
    this.stop();
    const src = this.audioCtx.createBufferSource();
    src.buffer = buffer;
    try {
      src.playbackRate.value = rate;
    } catch {
      /* mocked AudioParam may be read-only; deck still plays */
    }
    if (this.filter) {
      src.connect(this.filter);
    } else {
      src.connect(this.gain);
    }
    if (onEnded) {
      src.onended = () => {
        // The source self-clears when the buffer plays out — the
        // deck no longer holds it after this fires. Useful for both
        // natural end-of-track (forward as track_ended to the
        // backend) and post-stop cleanup.
        if (this.source === src) {
          this.source = null;
        }
        try {
          onEnded();
        } catch {
          /* swallow — UI plumbing must not kill the engine */
        }
      };
    }
    src.start(whenSec, offsetSec);
    this.source = src;
    this.bufferRef = buffer;
    this.startedAt = whenSec;
    this.offsetAtStart = offsetSec;
    this.rateAtStart = rate;
    this.trackId = trackId;
    return whenSec;
  }

  /**
   * Stop the currently scheduled source (if any). Idempotent. The
   * onended callback will NOT fire — callers use stop() to forcibly
   * end without triggering "track ended naturally" semantics.
   */
  stop(): void {
    const src = this.source;
    if (!src) return;
    try {
      src.onended = null;
    } catch {
      /* ignore */
    }
    try {
      src.stop();
    } catch {
      // Already stopped or never started; both safe.
    }
    try {
      src.disconnect();
    } catch {
      /* ignore */
    }
    this.source = null;
    this.bufferRef = null;
    this.trackId = null;
  }

  /**
   * Best-effort virtual playback position in seconds within the
   * track. Computed from the audio clock, so accurate within the
   * 128-sample render quantum (~2.7 ms @ 48 kHz). Returns 0 when no
   * source is scheduled.
   *
   * NOTE: this is *catalog-time* position — the offset within the
   * track's original timeline — which is what the backend's
   * playback_pos protocol expects. ``startedAt`` is in audio-thread
   * time, ``elapsed`` since then is wall-clock-equivalent at the
   * context's clock, and ``elapsed * rate`` converts back to catalog
   * seconds for tracks played at a non-1.0 rate.
   */
  position(): number {
    if (!this.source) return 0;
    const elapsed = Math.max(
      0,
      this.audioCtx.currentTime - this.startedAt,
    );
    return this.offsetAtStart + elapsed * this.rateAtStart;
  }

  /**
   * Catalog-time duration of the current track (buffer.duration is
   * already in seconds at the context sample rate). Returns 0 when
   * no buffer is loaded. Useful for the UI progress bar that
   * previously read HTMLMediaElement.duration.
   */
  duration(): number {
    return this.bufferRef ? this.bufferRef.duration : 0;
  }

  /**
   * Reset the deck's filter and gain to known pass-through state —
   * filter cutoff 20 Hz, no pending scheduled values on either
   * param. Called after a bass_swap transition completes (so the
   * next load on this deck inherits a clean filter chain) and on
   * any fresh load that doesn't go through a crossfade.
   */
  resetAutomation(toGain: number = 1): void {
    const now = this.audioCtx.currentTime;
    try {
      this.gain.gain.cancelScheduledValues(now);
      this.gain.gain.setValueAtTime(toGain, now);
    } catch {
      /* mocked AudioParam may be partial */
    }
    if (this.filter) {
      try {
        this.filter.frequency.cancelScheduledValues(now);
        this.filter.frequency.setValueAtTime(20, now);
      } catch {
        /* ignore */
      }
    }
  }
}
