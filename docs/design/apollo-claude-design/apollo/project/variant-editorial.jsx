// Variant A — "Editorial". Dark mode editorial.
// Newsreader serif headlines, Geist sans body, JetBrains Mono for data.
// Warm amber accent on near-black ink.
//
// Exposes: window.EditorialDashboard, EditorialBrief, EditorialCurate,
// EditorialEditor, EditorialExport, EditorialLive

const ED = {
  ink:    "#0d0c0b",
  ink2:   "#15140f",
  ink3:   "#1d1b16",
  line:   "rgba(232,224,206,0.10)",
  line2:  "rgba(232,224,206,0.18)",
  paper:  "#f4ecd8",
  text:   "#e8e0ce",
  mute:   "rgba(232,224,206,0.55)",
  faint:  "rgba(232,224,206,0.32)",
  amber:  "#e8a755",
  amber2: "#c98432",
  red:    "#d56a4a",
  green:  "#9bb37a",
  serif:  '"Newsreader", "Source Serif 4", Georgia, serif',
  sans:   '"Geist", "Inter Tight", system-ui, sans-serif',
  mono:   '"JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace',
};

const edScreen = {
  width: "100%", height: "100%", background: ED.ink, color: ED.text,
  fontFamily: ED.sans, display: "flex", flexDirection: "column",
  letterSpacing: "-0.005em",
};

const EdNav = ({ active = "Sessions", crumb }) => (
  <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "20px 36px", borderBottom: `1px solid ${ED.line}` }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
      <span style={{ fontFamily: ED.serif, fontStyle: "italic", fontSize: 22, letterSpacing: "-0.02em" }}>
        Apollo<span style={{ color: ED.amber }}>.</span>
      </span>
      {crumb && <span style={{ color: ED.faint, fontSize: 12, fontFamily: ED.mono, textTransform: "uppercase", letterSpacing: "0.12em" }}>{crumb}</span>}
    </div>
    <nav style={{ display: "flex", gap: 28, fontSize: 13, color: ED.mute }}>
      {["Sessions", "Catalog", "Live"].map(n => (
        <span key={n} style={{ color: n === active ? ED.text : ED.mute, borderBottom: n === active ? `1px solid ${ED.amber}` : "none", paddingBottom: 2 }}>{n}</span>
      ))}
      <span style={{ color: ED.mute }}>hamletxz</span>
    </nav>
  </header>
);

// ───────────────────────────────────────────────────────── DASHBOARD
const EditorialDashboard = () => (
  <div style={edScreen}>
    <EdNav active="Sessions" />
    <main style={{ padding: "40px 36px", flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 56 }}>
      <section>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 8 }}>Your library · 6 sessions</div>
            <h1 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 44, letterSpacing: "-0.025em", margin: 0, lineHeight: 1.05 }}>
              Pick up where you <em style={{ color: ED.amber, fontStyle: "italic" }}>left off</em>.
            </h1>
          </div>
          <button style={{ background: ED.paper, color: ED.ink, border: "none", padding: "12px 18px", fontFamily: ED.sans, fontSize: 13, fontWeight: 500, display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <ApolloIcon.plus /> New session
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, background: ED.line, border: `1px solid ${ED.line}` }}>
          {APOLLO_SESSIONS.map((s, i) => (
            <article key={i} style={{ background: ED.ink, padding: "22px 22px 18px", display: "flex", flexDirection: "column", gap: 12, position: "relative" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>{s.date}</span>
                <span style={{ fontFamily: ED.mono, fontSize: 10, color: s.status === "live" ? ED.amber : ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>
                  {s.status === "live" ? "● live now" : s.status}
                </span>
              </div>
              <h3 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 22, letterSpacing: "-0.02em", margin: 0, lineHeight: 1.15 }}>{s.name}</h3>
              <div style={{ display: "flex", gap: 14, fontSize: 12, color: ED.mute }}>
                <span>{s.genre}</span>
                <span style={{ color: ED.faint }}>·</span>
                <span>{fmtDuration(s.duration)}</span>
              </div>
              <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                {Array.from({ length: 24 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 14 + Math.sin(i + k * 0.6) * 6 + Math.random() * 4, background: k < 18 ? ED.amber2 : ED.line2, opacity: 0.7 }} />
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <aside style={{ borderLeft: `1px solid ${ED.line}`, paddingLeft: 36, display: "flex", flexDirection: "column", gap: 32 }}>
        <div>
          <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 14 }}>Quick brief</div>
          <p style={{ fontFamily: ED.serif, fontSize: 17, lineHeight: 1.45, color: ED.text, margin: 0 }}>
            <em style={{ color: ED.amber }}>"</em>30 minutes of lofi for a rainy garden afternoon, soft and contemplative.<em style={{ color: ED.amber }}>"</em>
          </p>
          <button style={{ marginTop: 16, background: "transparent", color: ED.text, border: `1px solid ${ED.line2}`, padding: "10px 14px", fontSize: 12, fontFamily: ED.sans, display: "flex", alignItems: "center", gap: 8, cursor: "pointer", width: "100%", justifyContent: "space-between" }}>
            <span>Build it</span>
            <ApolloIcon.arrow />
          </button>
        </div>
        <div>
          <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 14 }}>This week</div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10, fontSize: 13 }}>
            <li style={{ display: "flex", justifyContent: "space-between", color: ED.mute }}><span>Sessions built</span><span style={{ color: ED.text, fontFamily: ED.mono }}>14</span></li>
            <li style={{ display: "flex", justifyContent: "space-between", color: ED.mute }}><span>Hours rendered</span><span style={{ color: ED.text, fontFamily: ED.mono }}>9h 12m</span></li>
            <li style={{ display: "flex", justifyContent: "space-between", color: ED.mute }}><span>Live performances</span><span style={{ color: ED.text, fontFamily: ED.mono }}>3</span></li>
          </ul>
        </div>
      </aside>
    </main>
  </div>
);

// ───────────────────────────────────────────────────────── BRIEF
const EditorialBrief = () => (
  <div style={edScreen}>
    <EdNav crumb="Sessions / New" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1.1fr 1fr", padding: "60px 80px", gap: 80, alignItems: "start" }}>
      <div>
        <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 20 }}>01 — brief</div>
        <h1 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 56, letterSpacing: "-0.03em", margin: 0, lineHeight: 1.0 }}>
          Tell Apollo<br />what you<br /><em style={{ color: ED.amber, fontStyle: "italic" }}>want to hear</em>.
        </h1>
        <p style={{ fontFamily: ED.serif, fontSize: 18, lineHeight: 1.5, color: ED.mute, marginTop: 28, maxWidth: 380 }}>
          One sentence is enough. Apollo will infer genre, mood, energy and venue — and ask only if something is missing.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
        <div style={{ borderTop: `1px solid ${ED.line2}`, borderBottom: `1px solid ${ED.line2}`, padding: "20px 0" }}>
          <textarea
            defaultValue="A 30-minute lofi ambient set for a rainy garden afternoon. Soft, contemplative, no peaks."
            style={{ width: "100%", background: "transparent", border: "none", color: ED.text, fontFamily: ED.serif, fontSize: 26, lineHeight: 1.35, letterSpacing: "-0.015em", resize: "none", outline: "none", minHeight: 120 }}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 14, columnGap: 24, fontSize: 13 }}>
          {[
            ["Genre",       "lofi · ambient",           true],
            ["Duration",    "30 minutes",               true],
            ["Mood",        "contemplative",            true],
            ["Venue",       "garden · rainy afternoon", true],
            ["Energy arc",  "flat plateau, no peaks",   true],
          ].map(([k, v, ok]) => (
            <React.Fragment key={k}>
              <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", paddingTop: 3 }}>{k}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 10, color: ED.text }}>
                <span>{v}</span>
                {ok && <span style={{ color: ED.green, fontSize: 11 }}>✓ inferred</span>}
              </span>
            </React.Fragment>
          ))}
        </div>

        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          {["loud crowded bar", "intimate listening room", "outdoor café morning"].map(c => (
            <button key={c} style={{ background: "transparent", color: ED.mute, border: `1px solid ${ED.line2}`, padding: "8px 14px", borderRadius: 999, fontSize: 12, fontFamily: ED.sans, cursor: "pointer" }}>{c}</button>
          ))}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
          <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint }}>⌘↵ to send</span>
          <button style={{ background: ED.paper, color: ED.ink, border: "none", padding: "14px 22px", fontFamily: ED.sans, fontSize: 14, fontWeight: 500, display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
            Curate this set <ApolloIcon.arrow />
          </button>
        </div>
      </div>
    </main>
  </div>
);

// ───────────────────────────────────────────────────────── CURATE (Review + Critic + Editor merged)
const EditorialCurate = () => {
  const phases = [
    { id: "plan",    label: "Planned",  done: true,  active: false },
    { id: "review",  label: "Reviewed", done: true,  active: false },
    { id: "critic",  label: "Critique", done: false, active: true  },
    { id: "edit",    label: "Edited",   done: false, active: false },
    { id: "render",  label: "Render",   done: false, active: false },
  ];
  return (
    <div style={edScreen}>
      <EdNav crumb="lofi · garden chill / curate" />
      <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 0 }}>
        {/* Left: playlist */}
        <section style={{ padding: "32px 40px", borderRight: `1px solid ${ED.line}`, display: "flex", flexDirection: "column", gap: 24 }}>
          <div>
            <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>02 — curate</div>
            <h2 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 32, letterSpacing: "-0.02em", margin: "8px 0 0" }}>
              5 tracks · 34 min · <em style={{ color: ED.amber }}>flat arc</em>
            </h2>
          </div>

          {/* phase rail */}
          <div style={{ display: "flex", alignItems: "center", gap: 0, fontFamily: ED.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.14em" }}>
            {phases.map((p, i) => (
              <React.Fragment key={p.id}>
                <span style={{ color: p.active ? ED.amber : p.done ? ED.text : ED.faint, display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 999, background: p.active ? ED.amber : p.done ? ED.text : ED.faint, opacity: p.done || p.active ? 1 : 0.4 }} />
                  {p.label}
                </span>
                {i < phases.length - 1 && <span style={{ flex: 1, height: 1, background: p.done ? ED.line2 : ED.line, margin: "0 12px" }} />}
              </React.Fragment>
            ))}
          </div>

          {/* energy graph */}
          <div style={{ height: 80, position: "relative", border: `1px solid ${ED.line}`, padding: 12 }}>
            <span style={{ position: "absolute", top: 8, left: 12, fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>Energy arc</span>
            <span style={{ position: "absolute", top: 8, right: 12, fontFamily: ED.mono, fontSize: 10, color: ED.red, textTransform: "uppercase", letterSpacing: "0.14em" }}>plateau detected</span>
            <svg viewBox="0 0 300 50" preserveAspectRatio="none" style={{ width: "100%", height: "100%", marginTop: 14 }}>
              <line x1="0" y1="35" x2="300" y2="35" stroke={ED.line} strokeDasharray="2 3" />
              <path d="M0 38 L60 35 L120 32 L180 33 L240 36 L300 38" stroke={ED.amber} strokeWidth="1.5" fill="none" />
              <path d="M0 38 L60 35 L120 32 L180 33 L240 36 L300 38 L300 50 L0 50 Z" fill={ED.amber} opacity="0.08" />
            </svg>
          </div>

          {/* tracks */}
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column" }}>
            {APOLLO_TRACKS.map(t => (
              <li key={t.n} style={{ display: "grid", gridTemplateColumns: "20px 1fr auto auto auto", gap: 14, alignItems: "center", padding: "14px 0", borderBottom: `1px solid ${ED.line}` }}>
                <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint }}>{String(t.n).padStart(2, "0")}</span>
                <div>
                  <div style={{ fontFamily: ED.serif, fontSize: 17, letterSpacing: "-0.015em" }}>{t.title} <span style={{ color: ED.faint, fontStyle: "italic" }}>· {t.artist}</span></div>
                  <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.12em", marginTop: 3 }}>
                    {t.remix ? `${t.remix} remix · ` : ""}{t.label}
                  </div>
                </div>
                <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.mute }}>{t.bpm} BPM</span>
                <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber, padding: "2px 8px", border: `1px solid ${ED.line2}` }}>{t.key}</span>
                <div style={{ display: "flex", gap: 2, width: 60 }}>
                  {Array.from({ length: 10 }).map((_, k) => (
                    <span key={k} style={{ flex: 1, height: 12, background: k < t.energy ? ED.amber2 : ED.line2 }} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Right: critic + actions */}
        <aside style={{ padding: "32px 40px", display: "flex", flexDirection: "column", gap: 22, background: ED.ink2 }}>
          <div>
            <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>The critic says</div>
            <h2 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 24, letterSpacing: "-0.02em", margin: "6px 0 0", fontStyle: "italic" }}>
              "Two fixes, one win."
            </h2>
          </div>

          {APOLLO_CRITIC_NOTES.map((n, i) => {
            const tone = n.severity === "fix" ? ED.red : n.severity === "tip" ? ED.amber : ED.green;
            return (
              <article key={i} style={{ borderLeft: `2px solid ${tone}`, paddingLeft: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontFamily: ED.mono, fontSize: 10, color: tone, textTransform: "uppercase", letterSpacing: "0.16em" }}>
                    {n.severity} · pos {n.target}
                  </span>
                  {n.accepted && <span style={{ fontFamily: ED.mono, fontSize: 10, color: ED.green }}>✓ accepted</span>}
                </div>
                <div style={{ fontFamily: ED.serif, fontSize: 16, lineHeight: 1.3, color: ED.text }}>{n.headline}</div>
                <div style={{ fontSize: 12, color: ED.mute, lineHeight: 1.45 }}>{n.body}</div>
                {n.suggestion && (
                  <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber, padding: "8px 10px", background: "rgba(232,167,85,0.06)", border: `1px solid rgba(232,167,85,0.2)` }}>
                    → {n.suggestion}
                  </div>
                )}
                {!n.accepted && (
                  <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                    <button style={{ background: ED.paper, color: ED.ink, border: "none", padding: "6px 12px", fontSize: 11, fontFamily: ED.sans, cursor: "pointer" }}>Apply fix</button>
                    <button style={{ background: "transparent", color: ED.mute, border: `1px solid ${ED.line2}`, padding: "6px 12px", fontSize: 11, fontFamily: ED.sans, cursor: "pointer" }}>Ignore</button>
                    <button style={{ background: "transparent", color: ED.mute, border: `1px solid ${ED.line2}`, padding: "6px 12px", fontSize: 11, fontFamily: ED.sans, cursor: "pointer" }}>Edit manually</button>
                  </div>
                )}
              </article>
            );
          })}

          <div style={{ marginTop: "auto", display: "flex", gap: 10, paddingTop: 16, borderTop: `1px solid ${ED.line2}` }}>
            <button style={{ flex: 1, background: ED.paper, color: ED.ink, border: "none", padding: "12px 14px", fontSize: 13, fontFamily: ED.sans, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              Apply all & continue <ApolloIcon.arrow />
            </button>
            <button style={{ background: "transparent", color: ED.text, border: `1px solid ${ED.line2}`, padding: "12px 14px", fontSize: 13, fontFamily: ED.sans, cursor: "pointer" }}>
              Edit manually
            </button>
          </div>
        </aside>
      </main>
    </div>
  );
};

// ───────────────────────────────────────────────────────── EDITOR (manual control)
const EditorialEditor = () => (
  <div style={edScreen}>
    <EdNav crumb="lofi · garden chill / edit" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "260px 1fr 320px", gap: 0 }}>
      <aside style={{ borderRight: `1px solid ${ED.line}`, padding: "28px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>Suggested swaps</div>
        {[
          { who: "Brian Cid · Errors",          why: "+1.8 energy, same key", bpm: "61", key: "6A" },
          { who: "Ivory · Refuge",              why: "tonal contrast",        bpm: "60", key: "11A" },
          { who: "Justin Marchacos · Optics",   why: "warmer pad",            bpm: "61", key: "8A" },
          { who: "Innellea · Erlkönig",         why: "introduces a peak",     bpm: "61", key: "9A" },
        ].map((s, i) => (
          <div key={i} style={{ paddingBottom: 16, borderBottom: `1px solid ${ED.line}`, cursor: "pointer" }}>
            <div style={{ fontFamily: ED.serif, fontSize: 15 }}>{s.who}</div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
              <span style={{ fontSize: 11, color: ED.amber, fontStyle: "italic" }}>{s.why}</span>
              <span style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint }}>{s.bpm} · {s.key}</span>
            </div>
          </div>
        ))}
      </aside>

      <section style={{ padding: "28px 36px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 24 }}>
          <h2 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 28, margin: 0 }}>Set timeline</h2>
          <div style={{ display: "flex", gap: 12, fontFamily: ED.mono, fontSize: 11, color: ED.mute }}>
            <span>↑↓ reorder</span><span>⌫ remove</span><span>⌘K swap</span>
          </div>
        </div>

        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 1, background: ED.line }}>
          {APOLLO_TRACKS.map((t, i) => (
            <li key={t.n} style={{ background: i === 2 ? ED.ink3 : ED.ink, padding: "14px 16px", display: "grid", gridTemplateColumns: "16px 28px 1fr 60px 38px 80px 16px", gap: 14, alignItems: "center", borderLeft: i === 2 ? `2px solid ${ED.amber}` : "2px solid transparent" }}>
              <span style={{ color: ED.faint, cursor: "grab" }}><ApolloIcon.drag /></span>
              <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint }}>{String(t.n).padStart(2, "0")}</span>
              <div>
                <div style={{ fontFamily: ED.serif, fontSize: 16 }}>{t.title} <span style={{ color: ED.faint, fontStyle: "italic" }}>· {t.artist}</span></div>
                <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, marginTop: 2 }}>{t.label}</div>
              </div>
              <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.mute }}>{t.bpm} BPM</span>
              <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber }}>{t.key}</span>
              <div style={{ display: "flex", gap: 2 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 10, background: k < t.energy ? ED.amber2 : ED.line2 }} />
                ))}
              </div>
              <ApolloIcon.x />
            </li>
          ))}
        </ul>

        <div style={{ marginTop: 18, padding: "12px 16px", border: `1px dashed ${ED.line2}`, color: ED.mute, fontSize: 13, display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
          <ApolloIcon.plus /> Add track or describe what you want here…
        </div>
      </section>

      <aside style={{ borderLeft: `1px solid ${ED.line}`, padding: "28px 24px", background: ED.ink2, display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em", marginBottom: 10 }}>Set health</div>
          <div style={{ fontFamily: ED.serif, fontSize: 22, lineHeight: 1.2 }}>
            <span style={{ color: ED.green }}>4 of 5</span> checks passed
          </div>
        </div>
        {[
          ["Key flow",       "all Camelot-adjacent",      "ok"],
          ["BPM range",      "58–61, ±2.5",                "ok"],
          ["Energy arc",     "plateau, no peaks",          "warn"],
          ["Duration",       "34m vs target 30m",          "ok"],
          ["Mood coherence", "garden chill, contemplative","ok"],
        ].map(([k, v, s], i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", borderBottom: `1px solid ${ED.line}`, paddingBottom: 10 }}>
            <div>
              <div style={{ fontSize: 13 }}>{k}</div>
              <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, marginTop: 2 }}>{v}</div>
            </div>
            <span style={{ fontFamily: ED.mono, fontSize: 10, color: s === "ok" ? ED.green : ED.amber, alignSelf: "flex-start" }}>{s === "ok" ? "✓" : "!"}</span>
          </div>
        ))}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
          <button style={{ background: ED.paper, color: ED.ink, border: "none", padding: "14px", fontSize: 14, fontFamily: ED.sans, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            Render to YouTube <ApolloIcon.arrow />
          </button>
          <button style={{ background: "transparent", color: ED.amber, border: `1px solid ${ED.amber}`, padding: "14px", fontSize: 14, fontFamily: ED.sans, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            <ApolloIcon.play /> Go live with Apollo
          </button>
        </div>
      </aside>
    </main>
  </div>
);

// ───────────────────────────────────────────────────────── EXPORT
const EditorialExport = () => (
  <div style={edScreen}>
    <EdNav crumb="lofi · garden chill / render" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", padding: "60px 80px", gap: 60 }}>
      <div>
        <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.14em" }}>03 — render</div>
        <h1 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 52, letterSpacing: "-0.03em", margin: "12px 0 0", lineHeight: 1.0 }}>
          Pressing the<br /><em style={{ color: ED.amber }}>vinyl</em>.
        </h1>
        <p style={{ fontFamily: ED.serif, fontSize: 17, color: ED.mute, marginTop: 24, maxWidth: 380, lineHeight: 1.5 }}>
          Apollo is mixing your set into a single audio file. You'll get a YouTube-ready MP4 with cover art and chapter markers.
        </p>

        <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 14 }}>
          {[
            ["Stems aligned",      "complete"],
            ["Crossfades rendered","complete"],
            ["Mastering pass",     "running"],
            ["Cover art",          "queued"],
            ["MP4 encode",         "queued"],
          ].map(([k, s], i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 12, borderBottom: `1px solid ${ED.line}` }}>
              <span style={{ fontSize: 14 }}>{k}</span>
              <span style={{ fontFamily: ED.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.16em", color: s === "complete" ? ED.green : s === "running" ? ED.amber : ED.faint }}>
                {s === "complete" ? "✓ done" : s === "running" ? "● running" : "○ queued"}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div style={{ aspectRatio: "1/1", background: stripePlaceholder("rgba(232,167,85,0.18)", ED.ink2), border: `1px solid ${ED.line2}`, position: "relative", display: "flex", alignItems: "flex-end", padding: 24 }}>
          <div>
            <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber, textTransform: "uppercase", letterSpacing: "0.16em" }}>Apollo · 010</div>
            <div style={{ fontFamily: ED.serif, fontStyle: "italic", fontSize: 36, lineHeight: 1.0, marginTop: 8 }}>lofi for a<br />rainy garden</div>
            <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.mute, marginTop: 14 }}>34:12 · 5 tracks</div>
          </div>
          <span style={{ position: "absolute", top: 16, right: 16, fontFamily: ED.mono, fontSize: 10, color: ED.faint }}>cover preview</span>
        </div>

        <div style={{ marginTop: 24, fontFamily: ED.mono, fontSize: 12, color: ED.mute, display: "flex", flexDirection: "column", gap: 6 }}>
          {APOLLO_TRACKS.map((t, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr 44px", gap: 10 }}>
              <span style={{ color: ED.amber }}>{i === 0 ? "00:00" : i === 1 ? "06:50" : i === 2 ? "13:42" : i === 3 ? "20:24" : "27:08"}</span>
              <span style={{ color: ED.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title} · {t.artist}</span>
              <span>{t.key}</span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 28 }}>
          <button style={{ flex: 1, background: ED.paper, color: ED.ink, border: "none", padding: "14px", fontSize: 13, fontFamily: ED.sans, cursor: "pointer" }}>Download MP4</button>
          <button style={{ background: "transparent", color: ED.text, border: `1px solid ${ED.line2}`, padding: "14px 18px", fontSize: 13, fontFamily: ED.sans, cursor: "pointer" }}>Upload to YouTube</button>
        </div>
      </div>
    </main>
  </div>
);

// ───────────────────────────────────────────────────────── LIVE DJ
const EditorialLive = () => {
  const [mode, setMode] = React.useState("cabin");
  return (
    <div style={edScreen}>
      <EdNav crumb="lofi · garden chill / live" active="Live" />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 36px", borderBottom: `1px solid ${ED.line}` }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
            <span style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber, textTransform: "uppercase", letterSpacing: "0.16em" }}>● live · track 3 / 5</span>
            <span style={{ fontFamily: ED.serif, fontStyle: "italic", fontSize: 22 }}>Apollo is performing</span>
          </div>
          <div style={{ display: "flex", gap: 4, padding: 3, border: `1px solid ${ED.line2}`, borderRadius: 999 }}>
            {[["cabin", "Cabin"], ["immersive", "Immersive"], ["audience", "Audience"]].map(([id, lbl]) => (
              <button key={id} onClick={() => setMode(id)} style={{ background: mode === id ? ED.paper : "transparent", color: mode === id ? ED.ink : ED.mute, border: "none", padding: "6px 14px", fontSize: 12, fontFamily: ED.sans, borderRadius: 999, cursor: "pointer" }}>{lbl}</button>
            ))}
          </div>
        </div>

        {mode === "cabin" && (
          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 0 }}>
            <section style={{ padding: "32px 40px", display: "flex", flexDirection: "column", gap: 22, borderRight: `1px solid ${ED.line}` }}>
              <div>
                <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.16em" }}>Now playing</div>
                <h2 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 34, letterSpacing: "-0.02em", margin: "8px 0 0" }}>Brian Cid · <em style={{ fontStyle: "italic" }}>Mesh</em></h2>
                <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.mute, marginTop: 6 }}>61.1 BPM · 6A · crossfade in 29s</div>
              </div>
              <div style={{ height: 56, display: "flex", alignItems: "center", gap: 2 }}>
                {Array.from({ length: 80 }).map((_, k) => {
                  const h = 6 + Math.abs(Math.sin(k * 0.4) * 30) + Math.random() * 8;
                  return <span key={k} style={{ flex: 1, height: h, background: k < 50 ? ED.amber : ED.line2 }} />;
                })}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {["Skip", "Stay", "More energy", "Wind down"].map((b, i) => (
                  <button key={b} style={{ background: i === 2 ? ED.paper : "transparent", color: i === 2 ? ED.ink : ED.text, border: i === 2 ? "none" : `1px solid ${ED.line2}`, padding: "10px 14px", fontSize: 12, fontFamily: ED.sans, cursor: "pointer" }}>{b}</button>
                ))}
              </div>
              <div style={{ borderTop: `1px solid ${ED.line}`, paddingTop: 18 }}>
                <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.16em" }}>Up next</div>
                <div style={{ fontFamily: ED.serif, fontSize: 18, marginTop: 6 }}>Trikk · <em>Vilara</em> <span style={{ color: ED.faint, fontFamily: ED.mono, fontSize: 11, fontStyle: "normal" }}> 60.0 BPM · 6A</span></div>
              </div>
              <div style={{ marginTop: "auto" }}>
                <div style={{ fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.16em", marginBottom: 8 }}>Talk to Apollo</div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${ED.line2}`, padding: "10px 14px" }}>
                  <ApolloIcon.mic />
                  <input placeholder='"more groove" · "drop the energy" · "play something darker"' style={{ flex: 1, background: "transparent", border: "none", color: ED.text, fontFamily: ED.sans, fontSize: 13, outline: "none" }} />
                  <button style={{ background: ED.amber, color: ED.ink, border: "none", padding: "6px 14px", fontSize: 11, fontFamily: ED.sans, cursor: "pointer" }}>Send</button>
                </div>
                <div style={{ marginTop: 10, fontFamily: ED.serif, fontSize: 13, color: ED.mute, fontStyle: "italic" }}>
                  ‹ "Sticking with Mesh — the room feels settled. I'll lift gently around minute 22."
                </div>
              </div>
            </section>
            <section style={{ background: ED.ink2, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", inset: 0, background: stripePlaceholder("rgba(232,167,85,0.10)") }} />
              <div style={{ position: "absolute", top: 16, left: 20, right: 20, display: "flex", justifyContent: "space-between", fontFamily: ED.mono, fontSize: 10, color: ED.faint, textTransform: "uppercase", letterSpacing: "0.16em" }}>
                <span>Visuals · particles</span>
                <span>fullscreen ↗</span>
              </div>
              <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
                <svg width="220" height="220" viewBox="0 0 200 200">
                  <circle cx="100" cy="100" r="80" stroke={ED.amber} strokeWidth="0.5" fill="none" opacity="0.4" />
                  <circle cx="100" cy="100" r="60" stroke={ED.amber} strokeWidth="0.5" fill="none" opacity="0.6" />
                  <circle cx="100" cy="100" r="40" stroke={ED.amber} strokeWidth="0.8" fill="none" />
                  <circle cx="100" cy="100" r="20" fill={ED.amber} opacity="0.4" />
                </svg>
              </div>
              <div style={{ position: "absolute", bottom: 16, left: 20, right: 20, display: "flex", gap: 6 }}>
                {["Particles", "Strobe", "Fractal", "Vinyl"].map((v, i) => (
                  <button key={v} style={{ background: i === 0 ? ED.amber : "transparent", color: i === 0 ? ED.ink : ED.mute, border: i === 0 ? "none" : `1px solid ${ED.line2}`, padding: "5px 11px", fontSize: 10, fontFamily: ED.mono, textTransform: "uppercase", letterSpacing: "0.12em", cursor: "pointer" }}>{v}</button>
                ))}
                <span style={{ marginLeft: "auto", fontFamily: ED.mono, fontSize: 10, color: ED.faint, display: "flex", alignItems: "center", gap: 6 }}>
                  <ApolloIcon.mic /> mic perception · off
                </span>
              </div>
            </section>
          </div>
        )}

        {mode === "immersive" && (
          <div style={{ flex: 1, position: "relative", background: "#000" }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 50%, rgba(232,167,85,0.18), transparent 60%), ${stripePlaceholder("rgba(232,167,85,0.12)")}` }} />
            <div style={{ position: "absolute", top: 24, left: 32, right: 32, display: "flex", justifyContent: "space-between", color: ED.amber, fontFamily: ED.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em" }}>
              <span>● live</span>
              <span>track 3 / 5 — 12:48 elapsed</span>
            </div>
            <div style={{ position: "absolute", bottom: 32, left: 32, right: 32, display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
              <div>
                <div style={{ fontFamily: ED.mono, fontSize: 11, color: ED.amber, textTransform: "uppercase", letterSpacing: "0.16em" }}>now playing</div>
                <div style={{ fontFamily: ED.serif, fontSize: 56, fontStyle: "italic", color: "#fff", marginTop: 8, lineHeight: 1.0 }}>Mesh</div>
                <div style={{ fontFamily: ED.serif, fontSize: 22, color: ED.text, marginTop: 4 }}>Brian Cid <span style={{ color: ED.faint }}>· 61 BPM · 6A</span></div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={{ background: "rgba(255,255,255,0.08)", color: "#fff", border: `1px solid ${ED.line2}`, padding: "10px 16px", fontSize: 12, fontFamily: ED.sans, cursor: "pointer", backdropFilter: "blur(8px)" }}>Talk to Apollo</button>
                <button style={{ background: ED.paper, color: ED.ink, border: "none", padding: "10px 16px", fontSize: 12, fontFamily: ED.sans, cursor: "pointer" }}>Show controls</button>
              </div>
            </div>
          </div>
        )}

        {mode === "audience" && (
          <div style={{ flex: 1, background: "#000", position: "relative", display: "grid", placeItems: "center", padding: 60 }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at center, rgba(232,167,85,0.12), transparent 70%)` }} />
            <div style={{ textAlign: "center", position: "relative" }}>
              <div style={{ fontFamily: ED.mono, fontSize: 12, color: ED.amber, textTransform: "uppercase", letterSpacing: "0.32em", marginBottom: 24 }}>Apollo · live</div>
              <h1 style={{ fontFamily: ED.serif, fontStyle: "italic", fontSize: 96, fontWeight: 400, color: "#fff", letterSpacing: "-0.04em", margin: 0, lineHeight: 0.95 }}>Brian Cid</h1>
              <h2 style={{ fontFamily: ED.serif, fontWeight: 400, fontSize: 56, color: ED.amber, letterSpacing: "-0.03em", margin: "8px 0 32px" }}>Mesh</h2>
              <div style={{ fontFamily: ED.mono, fontSize: 13, color: ED.mute, letterSpacing: "0.18em", textTransform: "uppercase" }}>lofi · garden chill — track 3 of 5</div>
              <div style={{ width: 240, height: 1, background: ED.amber, margin: "32px auto 0", opacity: 0.5 }} />
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

Object.assign(window, {
  EditorialDashboard,
  EditorialBrief,
  EditorialCurate,
  EditorialEditor,
  EditorialExport,
  EditorialLive,
});
