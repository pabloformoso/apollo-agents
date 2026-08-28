/*
 * ApolloAgents — algorave lane, iteration 0.
 *
 * A 16-bar deep house pattern in Strudel (TidalCycles-in-the-browser).
 * 122 BPM, A minor (8A) — the catalog's own vocabulary.
 *
 * This module is PURE: it imports only the pattern engine (@strudel/core,
 * @strudel/mini, @strudel/tonal), never the audio output, so Node can import it
 * and `queryArc` it without a browser, an AudioContext or a sample download.
 * The page (index.html) imports this exact file for playback AND prints its
 * source on screen — in an algorave the code is the visual, so there is only
 * ever one copy of it.
 */

import { gain, n, note, s, stack, saw } from '@strudel/core';
import { mini, miniAllStrings } from '@strudel/mini';
import '@strudel/tonal'; // registers .scale()

// Makes bare strings parse as mini-notation, exactly like the strudel.cc REPL
// (initStrudel does this too). Idempotent, and touches nothing but the parser hook.
// Note it does NOT patch String.prototype — the REPL's transpiler does that — so
// a string we want to call pattern methods on has to go through mini() by hand.
miniAllStrings();

// ---------------------------------------------------------------------------
// Tempo. One cycle == one bar of 4/4.
// ---------------------------------------------------------------------------
export const BPM = 122;
export const CPS = BPM / 60 / 4; // 0.50833… cycles per second
export const BARS = 16; // 16 bars ≈ 31.5 s
export const KEY = 'A minor';
export const CAMELOT = '8A';

// ---------------------------------------------------------------------------
// Arrangement. One value per bar, 16 bars long, so every entry is a plain
// queryable fact rather than something hidden in a callback.
//                bar   0 1 2 3   4 5 6 7   8 9 A B   C D E F
// ---------------------------------------------------------------------------
const FROM_BAR_4 = '<0 0 0 0   1 1 1 1   1 1 1 1   1 1 1 1>';
const LAST_BAR = '<0 0 0 0   0 0 0 0   0 0 0 0   0 0 0 1>';

// Bass filter opens at bar 8 and again at bar 12 (spec: 400–800 Hz).
const BASS_CUTOFF = '<400 400 400 400   400 400 400 400   620 620 620 620   800 800 800 800>';
// Hats get louder over the same arc. The span is wide on purpose: the kick is
// so dominant that a subtle curve here is inaudible in the mixed render.
const HAT_ENERGY = '<0.55 0.55 0.55 0.55   0.85 0.85 0.85 0.85   1.05 1.05 1.05 1.05   1.2 1.2 1.2 1.2>';

// Harmony: one bar of Am7, one bar of Fmaj7. Both chords sit inside A natural
// minor, so the whole track stays in key by construction.
const AM7 = '[a3,c4,e4,g4]';
const FMAJ7 = '[f3,a3,c4,e4]';

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------

// Four-on-the-floor, 909 family.
export const kick = s('bd*4').bank('RolandTR909').gain(0.92);

// The deep house signature: open hat on every offbeat 8th (.125 .375 .625 .875).
export const openHat = s('[~ oh]*4').bank('RolandTR909').gain(0.42).pan(0.52);

// Quiet closed 16ths, accented on the beat, with a touch of swing.
// swingBy(1/8, 8) pushes every off-16th late by 1/128 of a bar ≈ 15 ms at 122 BPM.
export const closedHat = s('hh*16')
  .bank('RolandTR909')
  .gain(mini('[0.30 0.14 0.20 0.16]*4').mul(mini(HAT_ENERGY)))
  .swingBy(1 / 8, 8)
  .pan(0.46);

// Clap on 2 & 4, low in the mix, entering at bar 4.
export const clap = s('~ cp ~ cp')
  .bank('RolandTR909')
  .gain(0.62)
  .room(0.25)
  .roomsize(1.6)
  .orbit(3)
  .mask(FROM_BAR_4);

// Rolling syncopated bass on a 16th grid: 9 onsets a bar, most of them off the
// 8th-note grid, with an octave push (degree 7) into beat 3.
// Written as scale degrees so every pitch is inside A natural minor by
// construction; `<0 5>` walks the root A -> F with the chords.
export const bass = n('[0 ~] [~ 0] [0 ~] [~ 7] [0 ~] [~ 0] [0 0] [~ 0]')
  .add(n('<0 5>'))
  .scale('A1:minor')
  .s('sawtooth')
  .lpf(BASS_CUTOFF)
  .lpq(6)
  .attack(0.005)
  .decay(0.12)
  .sustain(0.35)
  .release(0.08)
  .gain(0.72)
  .orbit(1);

// Am7 / Fmaj7 stabs on the "and" of 2 and the "and" of 4, entering at bar 4.
// A triangle with a pluck envelope stands in for the e-piano: @strudel/web 1.3.0
// has its @strudel/soundfonts import commented out, so there is no GM keyboard
// to reach for. Delay + room do the rest of the character work.
export const stabs = note(`<${AM7} ${FMAJ7}>`)
  .struct('~ ~ ~ x ~ ~ ~ x')
  .s('triangle')
  .attack(0.008)
  .decay(0.22)
  .sustain(0.12)
  .release(0.3)
  .lpf(2400)
  .gain(0.46)
  .delay(0.4)
  .delaytime(0.1875) // a dotted 16th at 122 BPM
  .delayfeedback(0.32)
  .room(0.55)
  .roomsize(3)
  .orbit(2)
  .mask(FROM_BAR_4);

// The 16th bar (index 15): a rising snare roll into the loop point.
export const fill = s('sd*8')
  .bank('RolandTR909')
  .gain(saw.range(0.18, 0.5))
  .pan(0.5)
  .mask(LAST_BAR);

// ---------------------------------------------------------------------------
// The pattern
// ---------------------------------------------------------------------------
export const roles = { kick, openHat, closedHat, clap, bass, stabs, fill };

// Master trim. Seven layers summing into one bus clipped the render at unity.
// `.mul(gain(x))` scales the gain field of every event without flattening the
// per-event variation a plain `.gain(x)` would overwrite. The value is measured,
// not guessed — see README "Levels".
export const MASTER_TRIM = 0.62;

export const pattern = stack(kick, openHat, closedHat, clap, bass, stabs, fill).mul(gain(MASTER_TRIM));

// ---------------------------------------------------------------------------
// Plain-object description — tests and future tooling read this instead of
// parsing the code above.
// ---------------------------------------------------------------------------
export const description = {
  name: 'deephouse',
  bpm: BPM,
  cps: CPS,
  bars: BARS,
  key: KEY,
  camelot: CAMELOT,
  scale: 'A:minor',
  // A natural minor, as pitch classes.
  pitchClasses: ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
  chords: ['Am7', 'Fmaj7'],
  roles: [
    { name: 'kick', sound: 'bd', bank: 'RolandTR909', role: 'drums', onsetsPerBar: 4, fromBar: 0, toBar: 16 },
    { name: 'openHat', sound: 'oh', bank: 'RolandTR909', role: 'drums', onsetsPerBar: 4, fromBar: 0, toBar: 16 },
    { name: 'closedHat', sound: 'hh', bank: 'RolandTR909', role: 'drums', onsetsPerBar: 16, fromBar: 0, toBar: 16 },
    { name: 'clap', sound: 'cp', bank: 'RolandTR909', role: 'drums', onsetsPerBar: 2, fromBar: 4, toBar: 16 },
    { name: 'bass', sound: 'sawtooth', role: 'bass', onsetsPerBar: 9, fromBar: 0, toBar: 16 },
    { name: 'stabs', sound: 'triangle', role: 'chords', onsetsPerBar: 8, fromBar: 4, toBar: 16 },
    { name: 'fill', sound: 'sd', bank: 'RolandTR909', role: 'drums', onsetsPerBar: 8, fromBar: 15, toBar: 16 },
  ],
  sections: [
    { name: 'intro', fromBar: 0, toBar: 4, roles: ['kick', 'openHat', 'closedHat', 'bass'] },
    { name: 'groove', fromBar: 4, toBar: 8, roles: ['kick', 'openHat', 'closedHat', 'bass', 'clap', 'stabs'] },
    { name: 'lift', fromBar: 8, toBar: 12, roles: ['kick', 'openHat', 'closedHat', 'bass', 'clap', 'stabs'] },
    { name: 'peak', fromBar: 12, toBar: 16, roles: ['kick', 'openHat', 'closedHat', 'bass', 'clap', 'stabs', 'fill'] },
  ],
};

export default pattern;
