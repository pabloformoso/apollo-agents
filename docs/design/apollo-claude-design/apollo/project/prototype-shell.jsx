// Apollo prototype — interactive flow, single variant (Cinematic / Ember red).
// Reuses the design language from variant-cinematic.jsx but wires up real navigation.

const PT = {
  ink:    "#0a0807",
  surf:   "#13100e",
  surf2:  "#1c1814",
  line:   "rgba(255,238,220,0.10)",
  line2:  "rgba(255,238,220,0.20)",
  text:   "#fbf3e6",
  mute:   "rgba(251,243,230,0.62)",
  faint:  "rgba(251,243,230,0.36)",
  red:    "#e8553a",
  red2:   "#b53d24",
  cream:  "#f0e3c8",
  warn:   "#f0b15a",
  green:  "#9bbf7a",
  display:'"Instrument Serif", "GT Sectra", Georgia, serif',
  sans:   '"DM Sans", "Geist", system-ui, sans-serif',
  mono:   '"JetBrains Mono", ui-monospace, monospace',
};

// ────────────── Logo ──────────────
const ApolloMark = ({ size = 28, dot = true, color = PT.text, dotColor = PT.red }) => (
  <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: size, letterSpacing: "-0.022em", color, lineHeight: 1, display: "inline-flex", alignItems: "baseline" }}>
    Apollo{dot && <span style={{ color: dotColor }}>.</span>}
  </span>
);

// ────────────── Router ──────────────
const ROUTES = [
  { id: "dashboard", label: "Library" },
  { id: "brief",     label: "Brief"   },
  { id: "curate",    label: "Curate"  },
  { id: "editor",    label: "Editor"  },
  { id: "export",    label: "Render"  },
  { id: "live",      label: "Live"    },
];

const Router = React.createContext({ go: () => {}, route: "dashboard" });

// ────────────── App shell ──────────────
const Shell = ({ children, route, go, hideNav }) => (
  <div style={{ width: "100%", minHeight: "100vh", background: PT.ink, color: PT.text, fontFamily: PT.sans, display: "flex", flexDirection: "column" }}>
    {!hideNav && (
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 36px", borderBottom: `1px solid ${PT.line}`, position: "sticky", top: 0, background: PT.ink, zIndex: 10 }}>
        <button onClick={() => go("dashboard")} style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer", display: "flex", alignItems: "baseline", gap: 18 }}>
          <ApolloMark size={28} />
          {route !== "dashboard" && <span style={{ fontFamily: PT.mono, fontSize: 10, color: PT.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>lofi · garden chill</span>}
        </button>
        <nav style={{ display: "flex", gap: 4, padding: 3, border: `1px solid ${PT.line}` }}>
          {ROUTES.map(r => (
            <button key={r.id} onClick={() => go(r.id)} style={{ background: route === r.id ? PT.cream : "transparent", color: route === r.id ? PT.ink : PT.mute, border: "none", padding: "6px 14px", fontFamily: PT.sans, fontSize: 12, cursor: "pointer", letterSpacing: "0.02em" }}>{r.label}</button>
          ))}
        </nav>
        <span style={{ fontSize: 13, color: PT.mute }}>hamletxz</span>
      </header>
    )}
    <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</main>
  </div>
);

// Tiny stripe placeholder — keep it inline so children can reuse
const stripe = (alpha = 0.16, bg = PT.surf) => {
  const svg = encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-1,1 l2,-2 M0,8 l8,-8 M7,9 l2,-2' stroke='rgba(232,85,58,${alpha})' stroke-width='1'/></svg>`);
  return `${bg} url("data:image/svg+xml;utf8,${svg}")`;
};

const SESSIONS = [
  { id: "lofi-garden",       name: "lofi · garden chill",        genre: "lofi · ambient",  duration: 30,  date: "10/05/2026", status: "live"   },
  { id: "deep-house",        name: "deep house · midnight",      genre: "deep house",      duration: 90,  date: "08/05/2026", status: "draft"  },
  { id: "cyberpunk-drive",   name: "cyberpunk drive",            genre: "synthwave",       duration: 45,  date: "06/05/2026", status: "ready"  },
  { id: "sunday-brew",       name: "sunday morning brew",        genre: "neo-soul",        duration: 60,  date: "03/05/2026", status: "ready"  },
  { id: "warehouse-4am",     name: "warehouse 4am",              genre: "techno",          duration: 120, date: "01/05/2026", status: "ready"  },
  { id: "rainy-focus",       name: "rainy office focus",         genre: "lofi · ambient",  duration: 120, date: "28/04/2026", status: "ready"  },
];

const TRACKS = [
  { n: 1, artist: "Clarian",              title: "Television Days", remix: "Tim Engelhardt Dub", label: "Balance Music",  bpm: 58.6, key: "6A", energy: 3.2 },
  { n: 2, artist: "Premiere Three Hands", title: "Lunare",          remix: null,                  label: "Chapter 24",     bpm: 61.1, key: "5A", energy: 4.0 },
  { n: 3, artist: "Brian Cid",            title: "Mesh",            remix: null,                  label: "Original Mix",   bpm: 61.1, key: "6A", energy: 4.4 },
  { n: 4, artist: "Trikk",                title: "Vilara",          remix: null,                  label: "Original Mix",   bpm: 60.0, key: "6A", energy: 3.8 },
  { n: 5, artist: "Trikk",                title: "Devila",          remix: null,                  label: "Original Mix",   bpm: 60.0, key: "5A", energy: 3.5 },
];

const CRITIC_NOTES = [
  { id: "n1", severity: "fix", target: "1–5", headline: "Energy plateau across the whole set", body: "All five tracks sit at energy 3–4. For a 30-min garden chill set this is OK, but a single peak around minute 18 would create a memorable arc.", suggestion: "Add one track ≥ energy 7 around position 3." },
  { id: "n2", severity: "tip", target: "2 → 3", headline: "Key jump 5A → 6A is fine but flat", body: "Both transitions are Camelot-adjacent so they'll mix cleanly. Consider a swap for tonal contrast.", suggestion: "Try Brian Cid · Errors (6A) or Ivory · Refuge (11A)." },
  { id: "n3", severity: "ok",  target: "4 → 5", headline: "Closing pair lands well", body: "Trikk · Vilara into Trikk · Devila is a same-artist outro. Reads intentional.", suggestion: null },
];

const fmtDur = (m) => (m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60 ? (m % 60) + "m" : ""}`.trim());

window.PT = PT;
window.ApolloMark = ApolloMark;
window.Shell = Shell;
window.Router = Router;
window.ROUTES = ROUTES;
window.stripe = stripe;
window.PROTO_SESSIONS = SESSIONS;
window.PROTO_TRACKS = TRACKS;
window.PROTO_CRITIC = CRITIC_NOTES;
window.fmtDur = fmtDur;
