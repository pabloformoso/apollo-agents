/**
 * scene_picker — which shader scene "auto" shows for a track, and the
 * two colours it is painted with.
 *
 * The rule is the one a VJ would use: beatless / meditative material gets
 * slow light (aurora), mid-tempo grooves get geometry (prism), and anything
 * driving gets motion towards the viewer (tunnel). The genre comes from the
 * track id's prefix (``healing--…``) because ``LiveTrackSummary`` carries no
 * genre field; BPM decides when the prefix says nothing.
 */

import { camelotToColor, type HSLColor } from "./palette";

export type ShaderScene = "aurora" | "prism" | "tunnel" | "pulse";

/** Genres whose music has no kick to follow — never a tunnel or a pulse. */
const CALM_GENRES = new Set([
  "healing",
  "aural",
  "lofi-ambient",
  "lofi - ambient",
  "chillout",
  "ambient",
]);

const DRIVING_GENRES = new Set(["techno", "cyberpunk", "synthware"]);

export interface SceneTrackInfo {
  id?: string | null;
  bpm?: number | null;
}

export function genreOf(track: SceneTrackInfo | null | undefined): string | null {
  const id = track?.id ?? "";
  const cut = id.indexOf("--");
  return cut > 0 ? id.slice(0, cut).toLowerCase() : null;
}

export function autoScene(track: SceneTrackInfo | null | undefined): ShaderScene {
  const genre = genreOf(track);
  if (genre && CALM_GENRES.has(genre)) return "aurora";
  if (genre && DRIVING_GENRES.has(genre)) return "tunnel";
  const bpm = track?.bpm ?? 0;
  if (!(bpm > 0) || bpm < 95) return "aurora";
  if (bpm < 118) return "prism";
  return "tunnel";
}

/** Kaleidoscope symmetry from the Camelot number: 1..12 → 6..12 folds. */
export function symmetryFor(camelotKey: string | null | undefined): number {
  const n = parseInt(String(camelotKey ?? ""), 10);
  if (!Number.isFinite(n) || n < 1 || n > 12) return 8;
  return 6 + Math.round(((n - 1) / 11) * 6);
}

export type RGB = [number, number, number];

export function hslToRgb({ h, s, l }: HSLColor): RGB {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = (((h % 360) + 360) % 360) / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  const [r, g, b] =
    hp < 1 ? [c, x, 0] : hp < 2 ? [x, c, 0] : hp < 3 ? [0, c, x]
    : hp < 4 ? [0, x, c] : hp < 5 ? [x, 0, c] : [c, 0, x];
  const m = l - c / 2;
  return [r + m, g + m, b + m];
}

/**
 * The key's hue plus an analogous partner 45° away — two related colours
 * read as a designed palette; the complementary pair reads as a warning.
 */
export function paletteFor(camelotKey: string | null | undefined): { a: RGB; b: RGB } {
  const base = camelotToColor(camelotKey);
  return {
    a: hslToRgb({ h: base.h, s: 0.8, l: 0.5 }),
    b: hslToRgb({ h: base.h + 45, s: 0.75, l: 0.62 }),
  };
}

/** Frame-rate independent ease of ``cur`` towards ``target`` (in place). */
export function easeRgb(cur: RGB, target: RGB, dtSec: number, tauSec = 2.5): RGB {
  const k = 1 - Math.exp(-Math.max(0, dtSec) / tauSec);
  cur[0] += (target[0] - cur[0]) * k;
  cur[1] += (target[1] - cur[1]) * k;
  cur[2] += (target[2] - cur[2]) * k;
  return cur;
}
