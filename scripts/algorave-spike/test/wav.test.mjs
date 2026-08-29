/*
 * Recording smoke — spec §5.2.
 *
 * Machine-local, like scripts/render_surge_live.py: it asserts the artefact that
 * `node record.mjs` produces. When that WAV does not exist yet the whole suite
 * skips instead of failing, so `npm test` stays green on a fresh clone and in a
 * CI runner that has no browser.
 */
import { existsSync, readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { isTrueStereo, levels, parseWav, sliceRms, windowRms } from '../wav.mjs';
import { description } from '../patterns/deephouse.js';

const WAV = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..', 'output', 'algorave', 'deephouse-30s.wav');
const present = existsSync(WAV);

if (!present) {
  console.log(`[wav.test] skipping — ${WAV} does not exist yet. Run: node record.mjs`);
}

describe.skipIf(!present)('output/algorave/deephouse-30s.wav', () => {
  const wav = present ? parseWav(readFileSync(WAV)) : null;
  const { peak, rms } = present ? levels(wav) : {};

  it('exists and is not a stub', () => {
    expect(statSync(WAV).size).toBeGreaterThan(1_000_000);
  });

  it('is at least 30 seconds long', () => {
    expect(wav.duration).toBeGreaterThanOrEqual(30);
    // ...and is the 16-bar loop it claims to be, not an accidental short capture
    // padded out or a long tail of silence.
    const loopSeconds = description.bars / description.cps;
    expect(wav.duration).toBeGreaterThanOrEqual(loopSeconds - 0.05);
    expect(wav.duration).toBeLessThan(loopSeconds + 5);
  });

  it('is 48 kHz stereo', () => {
    expect(wav.sampleRate).toBe(48_000);
    expect(wav.channels).toBe(2);
    expect(isTrueStereo(wav)).toBe(true); // the pan()s in the pattern have to survive
  });

  it('is audible but does not clip', () => {
    expect(rms).toBeGreaterThan(0.02);
    expect(peak).toBeLessThan(0.99);
    // A pattern this dense should also not be a whisper.
    expect(peak).toBeGreaterThan(0.2);
  });

  it('is non-silent in every 5 second window', () => {
    const windows = windowRms(wav, 5);
    expect(windows.length).toBeGreaterThanOrEqual(6);
    for (const w of windows) {
      expect(w.rms, `window at ${w.start}s`).toBeGreaterThan(0.01);
    }
  });

  it('carries the arrangement, not a static loop', () => {
    // Measured above 1.5 kHz. Broadband RMS is useless here: the kick is loud
    // enough that adding a clap and a chord stab moves it by ~3 %, which is not
    // a margin any test should stand on. Above 1.5 kHz the kick and the bass are
    // gone and what remains is exactly what the section map adds.
    const barSeconds = 1 / description.cps;
    const top = (fromBar, toBar) =>
      sliceRms(wav, fromBar * barSeconds, toBar * barSeconds, 1500);
    const sections = Object.fromEntries(
      description.sections.map((s) => [s.name, top(s.fromBar, s.toBar)]),
    );

    for (const [name, value] of Object.entries(sections)) {
      expect(value, `${name} is silent above 1.5 kHz`).toBeGreaterThan(0.005);
    }
    // The clap and the stabs arriving at bar 4 are the biggest single step.
    expect(sections.groove).toBeGreaterThan(sections.intro * 1.05);
    // ...and the hat energy keeps climbing into the peak.
    expect(sections.peak).toBeGreaterThan(sections.groove);
    expect(sections.peak).toBeGreaterThan(sections.intro * 1.1);

    // The full-band picture: nothing collapses, and the loudest transients
    // arrive once every layer is in.
    const peakBetween = (fromBar, toBar) => {
      const from = Math.floor(fromBar * barSeconds * wav.sampleRate);
      const to = Math.min(Math.floor(toBar * barSeconds * wav.sampleRate), wav.frames);
      let max = 0;
      for (const ch of wav.channelData) {
        for (let i = from; i < to; i++) if (Math.abs(ch[i]) > max) max = Math.abs(ch[i]);
      }
      return max;
    };
    expect(peakBetween(4, 8)).toBeGreaterThan(peakBetween(0, 4) * 1.05);
  });

  it('holds a steady four-on-the-floor pulse', () => {
    // The kick is the one thing that must never drop out. Slice each beat's
    // attack window and check the low end is there in all 64 of them — this is
    // what caught @strudel's offline maxPolyphony cull silently killing voices
    // from bar 5 onward (see README "API surprises").
    const beatSeconds = 1 / description.cps / 4;
    const misses = [];
    for (let beat = 0; beat < description.bars * 4; beat++) {
      const at = beat * beatSeconds;
      if (at + 0.05 > wav.duration) break;
      if (sliceRms(wav, at, at + 0.05) < 0.05) misses.push(beat);
    }
    expect(misses, `beats with no kick: ${misses.join(',')}`).toHaveLength(0);
  });
});
