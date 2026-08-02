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
 * v3.9 — upper bound on one load() (fetch + decode). decodeAudioData
 * carries no timeout of its own and CAN hang forever: in the
 * 2026-08-01 30 h endless session, renderer memory pressure wedged
 * the decoder and 22 queued loads sat pending for hours (all
 * rejecting with EncodingError only at page teardown) while the
 * stream played nothing. 20 s is an order of magnitude above the
 * worst observed healthy decode (~2 s) so a trip is a real wedge,
 * not a slow machine.
 */
export const BUFFER_LOAD_TIMEOUT_MS = 20_000;

/**
 * Load-failure taxonomy. live.ts routes on the stage:
 *
 *  - ``BufferFetchError`` — network / HTTP stage. Deliberately NOT
 *    skip-worthy: the E2E substrate drives the UI against 404ing mock
 *    streams and relies on a failed fetch leaving the deck inert, and
 *    a transient network blip shouldn't burn a track.
 *  - ``BufferDecodeError`` — decodeAudioData rejected. The bytes
 *    arrived but can't become PCM; retrying the same track can't
 *    succeed, so the session should skip past it.
 *  - ``BufferLoadTimeoutError`` — the load exceeded its deadline
 *    (in practice: a wedged decoder). Skip-worthy for the same reason.
 */
export class BufferFetchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BufferFetchError";
  }
}

export class BufferDecodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BufferDecodeError";
  }
}

export class BufferLoadTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BufferLoadTimeoutError";
  }
}

/**
 * True when a load failure means the track itself is unplayable
 * (decode failure / wedged decoder) and the session should advance
 * past it rather than sit inert. Fetch-stage failures return false —
 * see the taxonomy note above.
 */
export function isSkippableLoadFailure(err: unknown): boolean {
  return (
    err instanceof BufferDecodeError || err instanceof BufferLoadTimeoutError
  );
}

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
 *
 * v3.9 — the cache is a working set, NOT an archive: callers must
 * prune() it down to the tracks still in play after every track
 * advance. Decoded PCM is ~50–100 MB per track; the 2026-08-01
 * incident showed an endless session that never evicts grows by
 * hundreds of tracks until the renderer can no longer allocate and
 * every subsequent decode fails.
 */
export class BufferCache {
  private readonly cache = new Map<string, AudioBuffer>();
  private readonly inflight = new Map<string, Promise<AudioBuffer>>();

  constructor(private readonly audioCtx: AudioContext) {}

  /**
   * Fetch ``url`` as bytes, decode to a PCM AudioBuffer at the
   * context's native rate, and cache. Concurrent calls for the same
   * URL share a single in-flight promise.
   *
   * v3.9 — each call races the shared in-flight load against its own
   * ``timeoutMs`` deadline (default BUFFER_LOAD_TIMEOUT_MS; pass 0 to
   * wait forever). A timeout rejects THIS caller with
   * ``BufferLoadTimeoutError`` but leaves the underlying load running:
   * if it eventually resolves the buffer is cached for the next hit,
   * and a retry re-joins the same in-flight promise under a fresh
   * deadline instead of stacking a second fetch.
   */
  async load(
    url: string,
    timeoutMs: number = BUFFER_LOAD_TIMEOUT_MS,
  ): Promise<AudioBuffer> {
    const cached = this.cache.get(url);
    if (cached) return cached;
    let inner = this.inflight.get(url);
    if (!inner) {
      inner = this.loadUncached(url);
      this.inflight.set(url, inner);
      // A timed-out caller stops awaiting ``inner``; without a spare
      // handler its eventual rejection would surface as an unhandled
      // promise rejection. This derived promise absorbs that case and
      // does not swallow the rejection for real awaiters.
      inner.catch(() => {});
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) return inner;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        inner,
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () =>
              reject(
                new BufferLoadTimeoutError(
                  `Buffer load timed out after ${timeoutMs} ms: ${url}`,
                ),
              ),
            timeoutMs,
          );
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  /** The actual fetch + decode, with stage-tagged failures. */
  private async loadUncached(url: string): Promise<AudioBuffer> {
    try {
      let resp: Response;
      try {
        resp = await fetch(url);
      } catch (err) {
        throw new BufferFetchError(`Buffer fetch failed: ${String(err)}`);
      }
      if (!resp.ok) {
        throw new BufferFetchError(`Buffer fetch failed: HTTP ${resp.status}`);
      }
      let arrayBuffer: ArrayBuffer;
      try {
        arrayBuffer = await resp.arrayBuffer();
      } catch (err) {
        throw new BufferFetchError(
          `Buffer fetch failed reading body: ${String(err)}`,
        );
      }
      // decodeAudioData has two signatures — the Promise form is
      // the modern one; some older Safaris still need callbacks.
      // We bridge defensively so the same call site works on both.
      let buffer: AudioBuffer;
      try {
        buffer = await new Promise<AudioBuffer>((resolve, reject) => {
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
      } catch (err) {
        throw new BufferDecodeError(`decodeAudioData failed: ${String(err)}`);
      }
      this.cache.set(url, buffer);
      return buffer;
    } finally {
      // Always clear in-flight, success or failure — a retry should
      // not be blocked by a stale rejected promise sitting in the
      // map.
      this.inflight.delete(url);
    }
  }

  /** Drop a single entry to free its decoded PCM (~10–100 MB). */
  evict(url: string): void {
    this.cache.delete(url);
  }

  /**
   * v3.9 — evict every cached buffer whose URL is NOT in ``keepUrls``,
   * returning how many were dropped. Called by live.ts after each
   * track advance with {current, preloaded-next} so the cache stays a
   * bounded two-ish-track working set instead of accumulating one
   * ~50–100 MB PCM buffer per played track (the leak behind the
   * 2026-08-01 30 h session collapse). In-flight loads are untouched —
   * only settled cache entries are dropped. Evicting a buffer that a
   * deck is still playing is safe: the source node keeps its own
   * reference until it ends.
   */
  prune(keepUrls: Iterable<string>): number {
    const keep = new Set(keepUrls);
    let evicted = 0;
    for (const url of Array.from(this.cache.keys())) {
      if (!keep.has(url)) {
        this.cache.delete(url);
        evicted += 1;
      }
    }
    return evicted;
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
   * v3.5 — apply a feed-forward beat-lock grid-warp schedule to the
   * current source's playbackRate.
   *
   * Each segment is scheduled against the SAME ``whenSec`` audio-thread
   * clock passed to scheduleSource(), so the per-bar rate steps land on
   * the exact samples the backend computed from both madmom beatgrids.
   * ``ramp: false`` segments are stepped (``setValueAtTime`` — the per-bar
   * lock corrections that hold until the next bar); ``ramp: true``
   * segments glide (``linearRampToValueAtTime`` — the release back to
   * native rate after the overlap). This is the software equivalent of a
   * DJ riding the pitch fader for the whole blend.
   *
   * No-op when there is no scheduled source or the schedule is empty —
   * the deck then keeps the static rate it was started with.
   */
  applyRateSchedule(
    schedule: { at_sec: number; rate: number; ramp?: boolean }[] | undefined,
    whenSec: number,
  ): void {
    const src = this.source;
    if (!src || !schedule || schedule.length === 0) return;
    const param = src.playbackRate;
    try {
      param.cancelScheduledValues(whenSec);
    } catch {
      /* mocked AudioParam without cancelScheduledValues — segments below
         still apply individually where supported */
    }
    for (const seg of schedule) {
      const at = whenSec + seg.at_sec;
      try {
        if (seg.ramp) {
          param.linearRampToValueAtTime(seg.rate, at);
        } else {
          param.setValueAtTime(seg.rate, at);
        }
      } catch {
        /* partial AudioParam mock — skip this segment, keep going */
      }
    }
  }

  /**
   * W3 — momentary pitch-bend: multiply the live source's playbackRate by
   * ``rate`` now, then ramp back to the deck's base rate after
   * ``holdSec``. The DJ presses a nudge button; this is the audible
   * correction. No-op when no source is playing. Best-effort against mocked
   * AudioParams (tests).
   */
  nudgeRate(rate: number, holdSec = 0.25): void {
    const src = this.source;
    if (!src) return;
    const now = this.audioCtx.currentTime;
    const base = this.rateAtStart || 1;
    try {
      src.playbackRate.cancelScheduledValues(now);
    } catch {
      /* mocked AudioParam without cancelScheduledValues */
    }
    try {
      src.playbackRate.setValueAtTime(base * rate, now);
      src.playbackRate.linearRampToValueAtTime(base, now + holdSec);
    } catch {
      /* partial AudioParam mock — degrade silently */
    }
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
