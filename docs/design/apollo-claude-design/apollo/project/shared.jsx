// Shared data and tiny helpers for all three Apollo redesign variants.
// Loaded as a global Babel script — assigns helpers to window.

const APOLLO_TRACKS = [
  { n: 1, artist: "Clarian",                  title: "Television Days",        remix: "Tim Engelhardt Dub",  label: "Balance Music",      bpm: 58.6, key: "6A", energy: 3.2 },
  { n: 2, artist: "Premiere Three Hands",     title: "Lunare",                 remix: null,                   label: "Chapter 24",         bpm: 61.1, key: "5A", energy: 4.0 },
  { n: 3, artist: "Brian Cid",                title: "Mesh",                   remix: null,                   label: "Original Mix",       bpm: 61.1, key: "6A", energy: 4.4 },
  { n: 4, artist: "Trikk",                    title: "Vilara",                 remix: null,                   label: "Original Mix",       bpm: 60.0, key: "6A", energy: 3.8 },
  { n: 5, artist: "Trikk",                    title: "Devila",                 remix: null,                   label: "Original Mix",       bpm: 60.0, key: "5A", energy: 3.5 },
];

const APOLLO_SESSIONS = [
  { name: "lofi · garden chill",        genre: "lofi · ambient",   duration: 30,  date: "10/05/2026", status: "live"   },
  { name: "deep house · midnight",      genre: "deep house",       duration: 90,  date: "08/05/2026", status: "draft"  },
  { name: "cyberpunk drive",            genre: "synthwave",        duration: 45,  date: "06/05/2026", status: "ready"  },
  { name: "sunday morning brew",        genre: "neo-soul",         duration: 60,  date: "03/05/2026", status: "ready"  },
  { name: "warehouse 4am",              genre: "techno",           duration: 120, date: "01/05/2026", status: "ready"  },
  { name: "rainy office focus",         genre: "lofi · ambient",   duration: 120, date: "28/04/2026", status: "ready"  },
];

// Six phases collapsed into three user-facing stages.
const APOLLO_PHASES = [
  { id: "brief",   label: "Brief",   sub: "you tell Apollo what you want" },
  { id: "curate",  label: "Curate",  sub: "Apollo plans, critiques, edits" },
  { id: "play",    label: "Play",    sub: "render or go live"             },
];

// Critic notes that map onto specific tracks — the cards are the action surface.
const APOLLO_CRITIC_NOTES = [
  {
    severity: "fix",
    target: "1–5",
    headline: "Energy plateau across the whole set",
    body: "All five tracks sit at energy 0.0–0.2. For a 30-minute garden chill set this is acceptable, but a single peak around minute 18 would create a memorable arc without breaking the mood.",
    suggestion: "Add one track ≥ energy 7 around position 3.",
    accepted: false,
  },
  {
    severity: "tip",
    target: "2 → 3",
    headline: "Key jump 5A → 6A is fine but flat",
    body: "Both transitions are Camelot-adjacent so they'll mix cleanly. Consider an in-key swap for track 3 to add tonal contrast.",
    suggestion: "Try Brian Cid · Errors (6A) or Ivory · Refuge (11A).",
    accepted: false,
  },
  {
    severity: "ok",
    target: "4 → 5",
    headline: "Closing pair lands well",
    body: "Trikk · Vilara into Trikk · Devila is a same-artist outro. Reads intentional.",
    suggestion: null,
    accepted: true,
  },
];

// Helpers
const fmtDuration = (m) => (m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60 ? (m % 60) + "m" : ""}`.trim());
const energyBar = (e, max = 10) => {
  const pct = Math.max(0, Math.min(1, e / max));
  return pct;
};

// Inline placeholder image: subtle diagonal stripe SVG, used where an album-art
// or cover would normally sit. Returns a CSS background string.
const stripePlaceholder = (color = "rgba(255,255,255,0.06)", bg = "transparent") => {
  const svg = encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-1,1 l2,-2 M0,8 l8,-8 M7,9 l2,-2' stroke='${color}' stroke-width='1'/></svg>`);
  return `${bg} url("data:image/svg+xml;utf8,${svg}")`;
};

// Tiny SVG icons — kept primitive (no fancy hand-drawn art).
const Icon = {
  play:    (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" {...p}><path d="M4 3l9 5-9 5z"/></svg>,
  pause:   (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" {...p}><rect x="4" y="3" width="3" height="10"/><rect x="9" y="3" width="3" height="10"/></svg>,
  plus:    (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.5" fill="none" {...p}><path d="M8 3v10M3 8h10"/></svg>,
  arrow:   (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.5" fill="none" {...p}><path d="M3 8h10M9 4l4 4-4 4"/></svg>,
  check:   (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.8" fill="none" {...p}><path d="M3 8.5l3 3 7-7"/></svg>,
  x:       (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.5" fill="none" {...p}><path d="M4 4l8 8M12 4l-8 8"/></svg>,
  mic:     (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.4" fill="none" {...p}><rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.5 8.5a4.5 4.5 0 009 0M8 13v2"/></svg>,
  drag:    (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" {...p}><circle cx="6" cy="4" r="1"/><circle cx="10" cy="4" r="1"/><circle cx="6" cy="8" r="1"/><circle cx="10" cy="8" r="1"/><circle cx="6" cy="12" r="1"/><circle cx="10" cy="12" r="1"/></svg>,
  spark:   (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" {...p}><path d="M8 1l1.5 4.5L14 7l-4.5 1.5L8 13l-1.5-4.5L2 7l4.5-1.5z"/></svg>,
  wave:    (p={}) => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.4" fill="none" {...p}><path d="M1 8h2l1-4 2 8 2-12 2 12 2-8 1 4h2"/></svg>,
};

Object.assign(window, {
  APOLLO_TRACKS,
  APOLLO_SESSIONS,
  APOLLO_PHASES,
  APOLLO_CRITIC_NOTES,
  fmtDuration,
  energyBar,
  stripePlaceholder,
  ApolloIcon: Icon,
});
