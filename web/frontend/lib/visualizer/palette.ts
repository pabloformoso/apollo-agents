/**
 * palette — Camelot key → HSL hue mapping for the visualizer effects.
 *
 * The Camelot wheel is a circular ordering of musical keys; mapping it to
 * a hue circle gives every track a consistent color identity without us
 * needing the raw note name.  ``A`` (minor) keys lean cool, ``B`` (major)
 * keys lean warm.  Tracks without a key fall back to a neutral cyan that
 * matches the Apollo neon brand.
 *
 * Centralising this avoids duplicating literals in every effect module
 * and keeps the v2.5.3 visual layer in line with the GENRE_THEMES palette
 * that ``main.py`` uses for the rendered MP4 — same project, same colors.
 */

export interface HSLColor {
  /** 0..360 — hue circle. */
  h: number;
  /** 0..1 — saturation. */
  s: number;
  /** 0..1 — lightness. */
  l: number;
}

const FALLBACK: HSLColor = { h: 190, s: 0.85, l: 0.55 }; // Apollo neon cyan

const CAMELOT_HUES: Record<string, number> = {
  // A (minor) — left half of the wheel, cooler tones.
  "1A": 210, "2A": 240, "3A": 270, "4A": 300,
  "5A": 330, "6A": 0, "7A": 30, "8A": 60,
  "9A": 90, "10A": 120, "11A": 150, "12A": 180,
  // B (major) — right half, warmer / lighter.
  "1B": 200, "2B": 230, "3B": 260, "4B": 290,
  "5B": 320, "6B": 350, "7B": 20, "8B": 50,
  "9B": 80, "10B": 110, "11B": 140, "12B": 170,
};

/**
 * Resolve a Camelot key (e.g. ``"8A"``) to an HSL color.
 *
 * Unknown / null keys fall back to Apollo's neon cyan so the visualizer
 * never goes dark — a track without metadata still renders coherently.
 */
export function camelotToColor(camelot_key: string | null | undefined): HSLColor {
  if (!camelot_key) return FALLBACK;
  const key = String(camelot_key).trim().toUpperCase();
  const hue = CAMELOT_HUES[key];
  if (hue === undefined) return FALLBACK;
  // Major keys (B) get a slightly higher lightness to feel "lifted".
  const isMajor = key.endsWith("B");
  return {
    h: hue,
    s: 0.85,
    l: isMajor ? 0.62 : 0.55,
  };
}

/**
 * Encode HSL → 0xRRGGBB integer for ``THREE.Color.setHex`` and friends.
 */
export function hslToHex({ h, s, l }: HSLColor): number {
  const sat = Math.max(0, Math.min(1, s));
  const lig = Math.max(0, Math.min(1, l));
  const c = (1 - Math.abs(2 * lig - 1)) * sat;
  const hp = ((h % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let r = 0, g = 0, b = 0;
  if (hp < 1) { r = c; g = x; b = 0; }
  else if (hp < 2) { r = x; g = c; b = 0; }
  else if (hp < 3) { r = 0; g = c; b = x; }
  else if (hp < 4) { r = 0; g = x; b = c; }
  else if (hp < 5) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }
  const m = lig - c / 2;
  const R = Math.round((r + m) * 255);
  const G = Math.round((g + m) * 255);
  const B = Math.round((b + m) * 255);
  return (R << 16) | (G << 8) | B;
}
