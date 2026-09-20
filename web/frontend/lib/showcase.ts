/**
 * The showcase: one click from the home page to a set Apollo briefs,
 * curates and performs — with its reasoning on screen.
 *
 * Nothing here is a new mechanism. A showcase IS an ordinary session: the
 * brief goes through `POST /api/sessions` like any typed sentence, planning
 * streams on `/curate`, "Apollo, take the booth" opens `/live`. What this
 * adds is a curated sentence and a single entry point, because in a room
 * full of people every field you type is a moment you lose them.
 *
 * The briefs name genres the catalog actually holds in depth (deep house,
 * lofi ambient, synthware, soul jazz — see `tracks/tracks.json`), because a
 * showcase that widens out of its genre on the second track is not a
 * showcase. Twenty minutes: long enough for two transitions and the
 * safety net to show themselves, short enough to record.
 */

export interface ShowcaseBrief {
  id: string;
  genre: string;
  /** The sentence the parser reads. Genre and duration are inside it on purpose. */
  brief: string;
  /** What the button says while it builds. */
  label: string;
}

export const SHOWCASE_BRIEFS: readonly ShowcaseBrief[] = [
  {
    id: "rooftop-deep-house",
    genre: "deep house",
    brief: "A 20-minute deep house set for a rooftop at golden hour — warm, patient, building to one peak.",
    label: "deep house · rooftop at golden hour",
  },
  {
    id: "rainy-lofi",
    genre: "lofi - ambient",
    brief: "Twenty minutes of lofi ambient for a rainy garden afternoon — no peaks, just drift.",
    label: "lofi ambient · a rainy garden",
  },
  {
    id: "neon-synthware",
    genre: "synthware",
    brief: "A 20-minute synthware set for a late-night drive through a neon city — steady energy, no drops.",
    label: "synthware · a neon night drive",
  },
  {
    id: "brunch-soul-jazz",
    genre: "soul jazz",
    brief: "Twenty minutes of soul jazz for a slow Sunday brunch — warm and easy.",
    label: "soul jazz · Sunday brunch",
  },
] as const;

/**
 * Which brief to run next. Rotates so a second click in the same room
 * shows a different genre; `seed` makes it deterministic for tests and for
 * a presenter who wants a known set (`?showcase=<id>` is not built yet — a
 * seed is enough).
 */
export function pickShowcaseBrief(seed: number = Date.now()): ShowcaseBrief {
  const i = Math.abs(Math.floor(seed)) % SHOWCASE_BRIEFS.length;
  return SHOWCASE_BRIEFS[i];
}

export function showcaseById(id: string): ShowcaseBrief | null {
  return SHOWCASE_BRIEFS.find((b) => b.id === id) ?? null;
}
