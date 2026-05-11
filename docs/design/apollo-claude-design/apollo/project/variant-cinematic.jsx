// Variant C — "Cinematic". Big imagery, music-poster feel.
// Instrument Serif italic display, DM Sans body, JetBrains Mono for data.
// Warm red-orange accent on near-black. Image-driven layouts.

const CI = {
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

const ciScreen = { width: "100%", height: "100%", background: CI.ink, color: CI.text, fontFamily: CI.sans, display: "flex", flexDirection: "column" };

const CiHeader = ({ crumb, num }) => (
  <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 36px", borderBottom: `1px solid ${CI.line}` }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
      <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 28, letterSpacing: "-0.02em" }}>Apollo</span>
      {crumb && <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{crumb}</span>}
    </div>
    {num && <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{num}</span>}
    <nav style={{ display: "flex", gap: 22, fontSize: 13, color: CI.mute }}>
      <span>Library</span><span>Catalog</span><span style={{ color: CI.text }}>hamletxz</span>
    </nav>
  </header>
);

// ───────────────────────────── DASHBOARD
const CinematicDashboard = () => (
  <div style={ciScreen}>
    <CiHeader crumb="library" />
    <main style={{ flex: 1, padding: "0", display: "flex", flexDirection: "column" }}>
      {/* hero */}
      <section style={{ padding: "60px 60px 48px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 60, alignItems: "end", borderBottom: `1px solid ${CI.line}` }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>tonight ·  curated for you</span>
          <h1 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 92, fontWeight: 400, letterSpacing: "-0.035em", lineHeight: 0.95, margin: "16px 0 0" }}>
            What will you<br />make tonight<span style={{ color: CI.red }}>?</span>
          </h1>
          <p style={{ fontSize: 16, color: CI.mute, marginTop: 24, maxWidth: 380, lineHeight: 1.55 }}>
            Tell Apollo what you want to hear and it will assemble, critique, and either render it for you — or perform it live.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
            <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "14px 24px", fontSize: 14, fontFamily: CI.sans, fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 10 }}>Start a session <ApolloIcon.arrow /></button>
            <button style={{ background: "transparent", color: CI.text, border: `1px solid ${CI.line2}`, padding: "14px 24px", fontSize: 14, fontFamily: CI.sans, cursor: "pointer" }}>Browse catalog</button>
          </div>
        </div>
        <div style={{ aspectRatio: "5/4", background: stripePlaceholder("rgba(232,85,58,0.18)", CI.surf), border: `1px solid ${CI.line2}`, position: "relative", display: "flex", alignItems: "flex-end", padding: 28 }}>
          <span style={{ position: "absolute", top: 18, left: 24, fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>last performed · live</span>
          <div>
            <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 54, lineHeight: 0.95, color: CI.cream }}>warehouse,<br />4am.</div>
            <div style={{ fontFamily: CI.mono, fontSize: 11, color: CI.mute, marginTop: 14, letterSpacing: "0.18em" }}>TECHNO · 120 MIN · 18 TRACKS</div>
          </div>
        </div>
      </section>

      {/* recent */}
      <section style={{ padding: "40px 60px", flex: 1 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 24 }}>
          <h2 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 32, fontWeight: 400, letterSpacing: "-0.02em", margin: 0 }}>Recent sessions</h2>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>6 sessions · 9h 12m</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 }}>
          {APOLLO_SESSIONS.slice(0, 6).map((s, i) => (
            <article key={i} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ aspectRatio: "1/1", background: stripePlaceholder(`rgba(${["232,85,58","232,85,58","240,177,90","155,191,122","240,177,90","232,85,58"][i]},0.14)`, CI.surf), border: `1px solid ${CI.line}`, position: "relative", padding: 16, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                <span style={{ fontFamily: CI.mono, fontSize: 9, color: s.status === "live" ? CI.red : CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>
                  {s.status === "live" ? "● LIVE NOW" : `№ ${String(i + 1).padStart(2, "0")}`}
                </span>
                <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 26, lineHeight: 1.0, color: CI.cream }}>{s.name.split(" · ")[0]}</div>
              </div>
              <div>
                <div style={{ fontSize: 14 }}>{s.name}</div>
                <div style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.16em", marginTop: 4 }}>
                  {s.genre} · {fmtDuration(s.duration)} · {s.date}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  </div>
);

// ───────────────────────────── BRIEF
const CinematicBrief = () => (
  <div style={ciScreen}>
    <CiHeader crumb="new session" num="01 / 03 — brief" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
      <section style={{ padding: "60px 60px", display: "flex", flexDirection: "column", justifyContent: "center", borderRight: `1px solid ${CI.line}` }}>
        <h1 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 80, fontWeight: 400, letterSpacing: "-0.03em", lineHeight: 0.95, margin: 0 }}>
          One sentence.<br />That's all<br />I need<span style={{ color: CI.red }}>.</span>
        </h1>
        <p style={{ fontSize: 16, color: CI.mute, marginTop: 24, maxWidth: 420, lineHeight: 1.55 }}>
          Tell me the genre, the duration, the mood and where you'll listen. I'll fill the rest in and ask only what I really need.
        </p>
        <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 10, fontFamily: CI.mono, fontSize: 11, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>
          <span>"30 minutes of lofi for a rainy garden"</span>
          <span>"Ninety-minute techno set, build slowly, peak at minute 60"</span>
          <span>"Sunday brunch, neo-soul, warm and easy"</span>
        </div>
      </section>

      <section style={{ background: CI.surf, padding: "40px 50px", display: "flex", flexDirection: "column", gap: 28 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>your prompt</span>
          <textarea defaultValue="A 30-minute lofi ambient set for a rainy garden afternoon. Soft, contemplative, no peaks." style={{ background: "transparent", border: "none", color: CI.cream, fontFamily: CI.display, fontStyle: "italic", fontSize: 32, lineHeight: 1.25, letterSpacing: "-0.015em", resize: "none", outline: "none", minHeight: 180, padding: 0 }} />
          <div style={{ height: 1, background: CI.line2 }} />
        </div>

        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>understood as</span>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 14 }}>
            {[
              ["Genre",       "lofi · ambient"],
              ["Duration",    "30 minutes"],
              ["Mood",        "contemplative"],
              ["Venue",       "garden, rainy"],
              ["Energy",      "plateau, no peaks"],
              ["Tempo range", "58–62 BPM"],
            ].map(([k, v]) => (
              <div key={k} style={{ borderTop: `1px solid ${CI.line}`, paddingTop: 8 }}>
                <div style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{k}</div>
                <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 20, marginTop: 2 }}>{v}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint }}>⌘ + ↵</span>
          <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "14px 28px", fontFamily: CI.display, fontStyle: "italic", fontSize: 18, cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}>
            Curate this set <ApolloIcon.arrow />
          </button>
        </div>
      </section>
    </main>
  </div>
);

// ───────────────────────────── CURATE
const CinematicCurate = () => (
  <div style={ciScreen}>
    <CiHeader crumb="lofi · garden chill" num="02 / 03 — curate" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "200px 1fr 380px", gap: 0 }}>
      {/* left rail: cover + meta */}
      <aside style={{ borderRight: `1px solid ${CI.line}`, padding: "28px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ aspectRatio: "1/1", background: stripePlaceholder("rgba(232,85,58,0.18)", CI.surf), border: `1px solid ${CI.line}`, padding: 12, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <span style={{ fontFamily: CI.mono, fontSize: 9, color: CI.red, textTransform: "uppercase", letterSpacing: "0.18em" }}>apollo · 010</span>
          <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 22, lineHeight: 1.0 }}>lofi for<br />a rainy<br />garden</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", color: CI.mute }}><span>Tracks</span><span style={{ color: CI.text, fontFamily: CI.mono }}>5</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", color: CI.mute }}><span>Length</span><span style={{ color: CI.text, fontFamily: CI.mono }}>34:12</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", color: CI.mute }}><span>Avg BPM</span><span style={{ color: CI.text, fontFamily: CI.mono }}>60.2</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", color: CI.mute }}><span>Key flow</span><span style={{ color: CI.text, fontFamily: CI.mono }}>5A→6A</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", color: CI.mute }}><span>Energy</span><span style={{ color: CI.warn, fontFamily: CI.mono }}>plateau</span></div>
        </div>
        <div style={{ marginTop: "auto" }}>
          <div style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>versions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
            {[["v1", true], ["v2 (peakier)", false]].map(([n, a]) => (
              <button key={n} style={{ background: a ? CI.surf2 : "transparent", color: a ? CI.text : CI.mute, border: `1px solid ${a ? CI.line2 : "transparent"}`, padding: "6px 10px", fontFamily: CI.mono, fontSize: 11, textAlign: "left", cursor: "pointer" }}>{n}</button>
            ))}
            <button style={{ background: "transparent", color: CI.faint, border: `1px dashed ${CI.line2}`, padding: "6px 10px", fontFamily: CI.mono, fontSize: 11, textAlign: "left", cursor: "pointer" }}>+ branch</button>
          </div>
        </div>
      </aside>

      {/* center: tracks with arc */}
      <section style={{ padding: "28px 36px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 36, fontWeight: 400, letterSpacing: "-0.02em", margin: 0 }}>The set</h2>
          <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>↑↓ reorder · ⌫ remove · ⌘K swap</span>
        </div>

        {/* arc as a wide watermark behind the list */}
        <div style={{ position: "relative" }}>
          <svg viewBox="0 0 600 80" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: 80, opacity: 0.5 }}>
            <path d="M0 60 C100 50, 200 45, 300 48 S 500 55, 600 60 L600 80 L0 80 Z" fill={CI.red} fillOpacity="0.10" />
            <path d="M0 60 C100 50, 200 45, 300 48 S 500 55, 600 60" stroke={CI.red} strokeWidth="1" fill="none" />
          </svg>
          <span style={{ position: "absolute", top: 6, right: 4, fontFamily: CI.mono, fontSize: 10, color: CI.warn, textTransform: "uppercase", letterSpacing: "0.18em", zIndex: 1 }}>! flat arc detected</span>
        </div>

        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 0 }}>
          {APOLLO_TRACKS.map((t, i) => (
            <li key={t.n} style={{ display: "grid", gridTemplateColumns: "32px 60px 1fr 70px 50px 90px", gap: 16, alignItems: "center", padding: "16px 0", borderBottom: `1px solid ${CI.line}` }}>
              <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 26, color: CI.faint }}>{String(t.n).padStart(2, "0")}</span>
              <div style={{ width: 50, height: 50, background: stripePlaceholder(`rgba(232,85,58,0.${(i + 1) * 2})`, CI.surf), border: `1px solid ${CI.line}` }} />
              <div>
                <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 22, lineHeight: 1.1 }}>{t.title}</div>
                <div style={{ fontSize: 12, color: CI.mute, marginTop: 4 }}>{t.artist} · <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint }}>{t.label}</span></div>
              </div>
              <span style={{ fontFamily: CI.mono, fontSize: 12, color: CI.mute }}>{t.bpm} BPM</span>
              <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, padding: "2px 8px", border: `1px solid ${CI.line2}` }}>{t.key}</span>
              <div style={{ display: "flex", gap: 2 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 14, background: k < t.energy ? CI.red : CI.line2 }} />
                ))}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* right: critic as letter */}
      <aside style={{ borderLeft: `1px solid ${CI.line}`, background: CI.surf, padding: "28px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>note from the critic</span>
          <h3 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 34, fontWeight: 400, letterSpacing: "-0.02em", margin: "8px 0 0", lineHeight: 1.05 }}>"Two fixes,<br />one win."</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1, overflow: "auto" }}>
          {APOLLO_CRITIC_NOTES.map((n, i) => {
            const tone = n.severity === "fix" ? CI.red : n.severity === "tip" ? CI.warn : CI.green;
            return (
              <article key={i} style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 14, borderBottom: i < APOLLO_CRITIC_NOTES.length - 1 ? `1px solid ${CI.line}` : "none" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontFamily: CI.mono, fontSize: 10, color: tone, textTransform: "uppercase", letterSpacing: "0.18em" }}>{n.severity} · pos {n.target}</span>
                  {n.accepted && <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.green }}>✓ kept</span>}
                </div>
                <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 19, lineHeight: 1.2 }}>{n.headline}</div>
                <div style={{ fontSize: 12, color: CI.mute, lineHeight: 1.55 }}>{n.body}</div>
                {n.suggestion && <div style={{ fontFamily: CI.mono, fontSize: 11, color: CI.warn, paddingTop: 6 }}>→ {n.suggestion}</div>}
                {!n.accepted && (
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "7px 12px", fontSize: 11, fontFamily: CI.sans, cursor: "pointer" }}>Apply</button>
                    <button style={{ background: "transparent", color: CI.text, border: `1px solid ${CI.line2}`, padding: "7px 12px", fontSize: 11, fontFamily: CI.sans, cursor: "pointer" }}>Edit</button>
                    <button style={{ background: "transparent", color: CI.faint, border: "none", padding: "7px 4px", fontSize: 11, fontFamily: CI.sans, cursor: "pointer" }}>ignore</button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
        <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "14px", fontSize: 14, fontFamily: CI.sans, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
          Apply all & continue <ApolloIcon.arrow />
        </button>
      </aside>
    </main>
  </div>
);

// ───────────────────────────── EDITOR
const CinematicEditor = () => (
  <div style={ciScreen}>
    <CiHeader crumb="lofi · garden chill" num="02 / 03 — edit by hand" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 0 }}>
      <section style={{ padding: "32px 48px", display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>your move</span>
          <h2 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 44, fontWeight: 400, letterSpacing: "-0.02em", margin: "8px 0 0" }}>Sequence the night.</h2>
        </div>

        {/* horizontal timeline cards */}
        <div style={{ display: "flex", gap: 12, overflow: "auto", paddingBottom: 8 }}>
          {APOLLO_TRACKS.map((t, i) => (
            <div key={t.n} style={{ flex: "0 0 200px", border: `1px solid ${i === 2 ? CI.red : CI.line}`, background: i === 2 ? "rgba(232,85,58,0.06)" : CI.surf, padding: 16, display: "flex", flexDirection: "column", gap: 10, position: "relative" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 22, color: CI.faint }}>{String(t.n).padStart(2, "0")}</span>
                <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.mute }}>{t.bpm}·{t.key}</span>
              </div>
              <div style={{ aspectRatio: "1/1", background: stripePlaceholder("rgba(232,85,58,0.18)", CI.ink), border: `1px solid ${CI.line}` }} />
              <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 18, lineHeight: 1.1 }}>{t.title}</div>
              <div style={{ fontSize: 11, color: CI.mute }}>{t.artist}</div>
              <div style={{ display: "flex", gap: 1, marginTop: "auto" }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 6, background: k < t.energy ? CI.red : CI.line2 }} />
                ))}
              </div>
              {i === 2 && <span style={{ position: "absolute", top: -10, right: -10, background: CI.red, color: CI.cream, fontFamily: CI.mono, fontSize: 9, padding: "3px 8px", textTransform: "uppercase", letterSpacing: "0.14em" }}>editing</span>}
            </div>
          ))}
          <div style={{ flex: "0 0 200px", border: `1px dashed ${CI.line2}`, padding: 16, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, color: CI.faint, cursor: "pointer" }}>
            <ApolloIcon.plus />
            <span style={{ fontSize: 12 }}>Add a track</span>
          </div>
        </div>

        {/* arc + transition map */}
        <div style={{ background: CI.surf, border: `1px solid ${CI.line}`, padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>arc & transitions</span>
            <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.warn, textTransform: "uppercase", letterSpacing: "0.18em" }}>! still flat</span>
          </div>
          <svg viewBox="0 0 500 80" preserveAspectRatio="none" style={{ width: "100%", height: 80 }}>
            <defs>
              <linearGradient id="ci-arc" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CI.red} stopOpacity="0.4" />
                <stop offset="100%" stopColor={CI.red} stopOpacity="0" />
              </linearGradient>
            </defs>
            <line x1="0" y1="60" x2="500" y2="60" stroke={CI.line2} strokeDasharray="3 3" />
            <path d="M0 60 L100 56 L200 50 L300 45 L400 55 L500 58" stroke={CI.red} strokeWidth="1.5" fill="none" />
            <path d="M0 60 L100 56 L200 50 L300 45 L400 55 L500 58 L500 80 L0 80 Z" fill="url(#ci-arc)" />
            {APOLLO_TRACKS.map((t, i) => (
              <g key={i} transform={`translate(${50 + i * 100}, 0)`}>
                <circle cx="0" cy={60 - t.energy * 2} r="3" fill={i === 2 ? CI.red : CI.cream} />
                <text x="0" y="78" textAnchor="middle" fontFamily={CI.mono} fontSize="9" fill={CI.faint}>{t.key}</text>
              </g>
            ))}
          </svg>
        </div>

        {/* command bar */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${CI.line2}`, background: CI.surf, padding: "12px 16px" }}>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red }}>›</span>
          <input placeholder='swap track 3 with brian-cid—errors  ·  build "garden-chill"' style={{ flex: 1, background: "transparent", border: "none", color: CI.text, fontFamily: CI.mono, fontSize: 13, outline: "none" }} />
          <button style={{ background: CI.cream, color: CI.ink, border: "none", padding: "7px 16px", fontSize: 11, fontFamily: CI.sans, fontWeight: 500, cursor: "pointer" }}>Run</button>
        </div>
      </section>

      <aside style={{ borderLeft: `1px solid ${CI.line}`, padding: "32px 28px", display: "flex", flexDirection: "column", gap: 22, background: CI.surf }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>then</span>
          <h3 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 30, fontWeight: 400, letterSpacing: "-0.02em", margin: "6px 0 0" }}>Materialize.</h3>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <button style={{ background: CI.cream, color: CI.ink, border: "none", padding: "20px 18px", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, cursor: "pointer", textAlign: "left" }}>
            <span style={{ fontFamily: CI.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.18em", color: CI.red2 }}>route a · async</span>
            <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 26, lineHeight: 1.0 }}>Render to YouTube</span>
            <span style={{ fontSize: 12, color: "rgba(10,8,7,0.7)", marginTop: 4 }}>Apollo presses the vinyl. Comes back as a 1080p MP4 with chapters.</span>
          </button>
          <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "20px 18px", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, cursor: "pointer", textAlign: "left" }}>
            <span style={{ fontFamily: CI.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.18em", color: "rgba(255,255,255,0.7)" }}>route b · live</span>
            <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 26, lineHeight: 1.0 }}>Apollo, take the booth</span>
            <span style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 4 }}>Real-time mixing with mic awareness and visual stage.</span>
          </button>
        </div>

        <div style={{ marginTop: "auto", fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>
          set health · 78 / 100
          <div style={{ height: 3, background: CI.line, marginTop: 6, position: "relative" }}>
            <div style={{ width: "78%", height: "100%", background: CI.red }} />
          </div>
        </div>
      </aside>
    </main>
  </div>
);

// ───────────────────────────── EXPORT (poster + render)
const CinematicExport = () => (
  <div style={ciScreen}>
    <CiHeader crumb="lofi · garden chill" num="03 / 03 — pressing" />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 0 }}>
      <section style={{ padding: "40px 48px", borderRight: `1px solid ${CI.line}`, display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>release · async</span>
          <h2 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 56, fontWeight: 400, letterSpacing: "-0.025em", margin: "8px 0 0", lineHeight: 0.95 }}>
            Pressing<br />the vinyl.
          </h2>
        </div>

        {/* poster */}
        <div style={{ aspectRatio: "5/7", background: stripePlaceholder("rgba(232,85,58,0.16)", CI.surf), border: `1px solid ${CI.line2}`, position: "relative", padding: 28, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div>
            <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>APOLLO · 010</span>
            <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 56, lineHeight: 0.95, color: CI.cream, marginTop: 16 }}>lofi for<br />a rainy<br />garden,<br />2026</div>
          </div>
          <div>
            <div style={{ fontFamily: CI.mono, fontSize: 10, color: CI.mute, textTransform: "uppercase", letterSpacing: "0.18em", lineHeight: 1.6 }}>
              <div>5 tracks · 34:12</div>
              <div>contemplative · ambient · 60 BPM avg</div>
              <div>curated by Apollo for hamletxz</div>
            </div>
          </div>
          <span style={{ position: "absolute", top: 14, right: 18, fontFamily: CI.mono, fontSize: 9, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>cover · 1:1.4 · 1440px</span>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button style={{ flex: 1, background: CI.cream, color: CI.ink, border: "none", padding: "14px", fontSize: 13, fontFamily: CI.sans, fontWeight: 500, cursor: "pointer" }}>Download MP4</button>
          <button style={{ flex: 1, background: "transparent", color: CI.text, border: `1px solid ${CI.line2}`, padding: "14px", fontSize: 13, fontFamily: CI.sans, cursor: "pointer" }}>Upload to YouTube</button>
        </div>
      </section>

      <section style={{ padding: "40px 48px", display: "flex", flexDirection: "column", gap: 24 }}>
        <div>
          <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>render · 02:14 elapsed</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 6 }}>
            <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 56, color: CI.red }}>62%</span>
            <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.mute, textTransform: "uppercase", letterSpacing: "0.18em" }}>~ 1:38 left</span>
          </div>
          <div style={{ height: 4, background: CI.surf2, marginTop: 14, position: "relative" }}>
            <div style={{ width: "62%", height: "100%", background: CI.red }} />
          </div>
        </div>

        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          {[
            ["Stems aligned",        "complete"],
            ["Crossfades rendered",  "complete"],
            ["Mastering · -14 LUFS", "running"],
            ["Cover composed",       "queued"],
            ["MP4 encoded · 1080p",  "queued"],
          ].map(([k, s], i) => (
            <li key={i} style={{ display: "grid", gridTemplateColumns: "20px 1fr 80px", alignItems: "center", paddingBottom: 12, borderBottom: `1px solid ${CI.line}` }}>
              <span style={{ color: s === "complete" ? CI.green : s === "running" ? CI.red : CI.faint, fontFamily: CI.mono, fontSize: 12 }}>{s === "complete" ? "✓" : s === "running" ? "●" : "○"}</span>
              <span style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 19 }}>{k}</span>
              <span style={{ fontFamily: CI.mono, fontSize: 10, color: s === "complete" ? CI.green : s === "running" ? CI.red : CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{s}</span>
            </li>
          ))}
        </ul>

        <div style={{ marginTop: "auto", padding: 18, background: CI.surf, border: `1px solid ${CI.line}` }}>
          <div style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>chapters</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontFamily: CI.mono, fontSize: 12, color: CI.mute }}>
            {APOLLO_TRACKS.map((t, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr 36px" }}>
                <span style={{ color: CI.red }}>{i === 0 ? "00:00" : i === 1 ? "06:50" : i === 2 ? "13:42" : i === 3 ? "20:24" : "27:08"}</span>
                <span style={{ color: CI.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title} · {t.artist}</span>
                <span>{t.key}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  </div>
);

// ───────────────────────────── LIVE
const CinematicLive = () => {
  const [mode, setMode] = React.useState("audience");
  return (
    <div style={ciScreen}>
      <CiHeader crumb="lofi · garden chill — LIVE" num={mode.toUpperCase()} />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 36px", borderBottom: `1px solid ${CI.line}`, background: CI.surf }}>
          <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
            <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>● broadcasting</span>
            <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>03 / 05 · 12:48 elapsed · target 30:00</span>
          </div>
          <div style={{ display: "flex", gap: 4, padding: 3, border: `1px solid ${CI.line2}` }}>
            {[["audience", "Audience"], ["cabin", "Booth"], ["immersive", "Immersive"]].map(([id, lbl]) => (
              <button key={id} onClick={() => setMode(id)} style={{ background: mode === id ? CI.cream : "transparent", color: mode === id ? CI.ink : CI.mute, border: "none", padding: "6px 16px", fontFamily: CI.sans, fontSize: 12, cursor: "pointer" }}>{lbl}</button>
            ))}
          </div>
        </div>

        {mode === "audience" && (
          <div style={{ flex: 1, position: "relative", background: "#000", display: "grid", placeItems: "center", overflow: "hidden", padding: 40 }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 50%, rgba(232,85,58,0.20), transparent 70%)` }} />
            <div style={{ position: "absolute", inset: 0, background: stripePlaceholder("rgba(232,85,58,0.10)") }} />
            {/* floating data tags */}
            <div style={{ position: "absolute", top: 28, left: 36, fontFamily: CI.mono, fontSize: 10, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>track 03 / 05</div>
            <div style={{ position: "absolute", top: 28, right: 36, fontFamily: CI.mono, fontSize: 10, color: CI.cream, textTransform: "uppercase", letterSpacing: "0.22em" }}>61.1 BPM · 6A · CAMELOT 6</div>
            <div style={{ textAlign: "center", position: "relative" }}>
              <div style={{ fontFamily: CI.mono, fontSize: 12, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.32em" }}>now playing</div>
              <h1 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 200, fontWeight: 400, color: CI.cream, letterSpacing: "-0.05em", margin: "8px 0 0", lineHeight: 0.85 }}>Mesh</h1>
              <div style={{ fontFamily: CI.display, fontSize: 36, color: CI.red, marginTop: 18, letterSpacing: "-0.02em" }}>Brian Cid</div>
              <div style={{ width: 260, height: 1, background: CI.cream, opacity: 0.4, margin: "32px auto" }} />
              <div style={{ fontFamily: CI.mono, fontSize: 12, color: CI.mute, letterSpacing: "0.22em", textTransform: "uppercase" }}>apollo · live · garden chill, 2026</div>
            </div>
            <div style={{ position: "absolute", bottom: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.22em" }}>up next · trikk · vilara</span>
              <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.22em" }}>crossfade in 0:29</span>
            </div>
          </div>
        )}

        {mode === "cabin" && (
          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 0 }}>
            <section style={{ padding: "32px 40px", display: "flex", flexDirection: "column", gap: 22, borderRight: `1px solid ${CI.line}` }}>
              <div>
                <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.22em" }}>now</span>
                <h2 style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 56, fontWeight: 400, letterSpacing: "-0.025em", margin: "4px 0 0", lineHeight: 0.95 }}>Brian Cid<br /><span style={{ color: CI.red }}>Mesh</span></h2>
                <div style={{ fontFamily: CI.mono, fontSize: 11, color: CI.mute, marginTop: 10, letterSpacing: "0.18em", textTransform: "uppercase" }}>61.1 BPM · 6A · crossfade 0:29</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 2, height: 70 }}>
                {Array.from({ length: 80 }).map((_, k) => {
                  const h = 6 + Math.abs(Math.sin(k * 0.4) * 36) + Math.random() * 8;
                  return <span key={k} style={{ flex: 1, height: h, background: k < 50 ? CI.red : CI.line2 }} />;
                })}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {[["Skip", false], ["Stay", false], ["More energy", true], ["Wind down", false]].map(([b, a]) => (
                  <button key={b} style={{ background: a ? CI.red : "transparent", color: a ? CI.cream : CI.text, border: a ? "none" : `1px solid ${CI.line2}`, padding: "10px 16px", fontSize: 13, fontFamily: CI.sans, cursor: "pointer" }}>{b}</button>
                ))}
              </div>
              <div style={{ borderTop: `1px solid ${CI.line}`, paddingTop: 18 }}>
                <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.22em" }}>up next</span>
                <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 26, marginTop: 4 }}>Trikk · Vilara <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.faint, fontStyle: "normal" }}>60 BPM · 6A</span></div>
              </div>
              <div style={{ marginTop: "auto" }}>
                <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.22em" }}>talk to apollo</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${CI.line2}`, padding: "10px 14px", marginTop: 8 }}>
                  <ApolloIcon.mic />
                  <input placeholder='"more groove" · "drop the energy" · "darker"' style={{ flex: 1, background: "transparent", border: "none", color: CI.text, fontFamily: CI.sans, fontSize: 13, outline: "none" }} />
                  <button style={{ background: CI.red, color: CI.cream, border: "none", padding: "6px 16px", fontSize: 11, fontFamily: CI.sans, cursor: "pointer" }}>Send</button>
                </div>
                <div style={{ marginTop: 12, fontFamily: CI.display, fontStyle: "italic", fontSize: 16, color: CI.mute }}>
                  ‹ "Sticking with Mesh — the room feels settled. Lifting at 22:00."
                </div>
              </div>
            </section>
            <section style={{ background: "#000", position: "relative", overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 18px", borderBottom: `1px solid ${CI.line}` }}>
                <div style={{ display: "flex", gap: 6 }}>
                  {[["Particles", true], ["Strobe", false], ["Fractal", false], ["Vinyl", false]].map(([v, a]) => (
                    <button key={v} style={{ background: a ? CI.red : "transparent", color: a ? CI.cream : CI.mute, border: a ? "none" : `1px solid ${CI.line2}`, padding: "5px 12px", fontSize: 10, fontFamily: CI.mono, textTransform: "uppercase", letterSpacing: "0.18em", cursor: "pointer" }}>{v}</button>
                  ))}
                </div>
                <span style={{ fontFamily: CI.mono, fontSize: 10, color: CI.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>fullscreen ↗</span>
              </div>
              <div style={{ flex: 1, position: "relative" }}>
                <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 50%, rgba(232,85,58,0.22), transparent 70%)` }} />
                <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 400 400">
                  {Array.from({ length: 60 }).map((_, k) => (
                    <circle key={k} cx={Math.random() * 400} cy={Math.random() * 400} r={Math.random() * 2.5} fill={CI.cream} opacity={Math.random() * 0.7} />
                  ))}
                </svg>
                <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
                  <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 96, color: CI.cream, opacity: 0.92, letterSpacing: "-0.04em" }}>Mesh</div>
                </div>
              </div>
            </section>
          </div>
        )}

        {mode === "immersive" && (
          <div style={{ flex: 1, position: "relative", background: "#000", overflow: "hidden" }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 60%, rgba(232,85,58,0.30), transparent 70%)` }} />
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
              {Array.from({ length: 120 }).map((_, k) => (
                <circle key={k} cx={Math.random() * 800} cy={Math.random() * 600} r={Math.random() * 2.5} fill={CI.cream} opacity={Math.random() * 0.7} />
              ))}
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
              <div style={{ fontFamily: CI.display, fontStyle: "italic", fontSize: 280, color: CI.red, letterSpacing: "-0.05em", lineHeight: 0.9, textAlign: "center", textShadow: "0 0 60px rgba(232,85,58,0.5)" }}>Mesh</div>
            </div>
            <div style={{ position: "absolute", top: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontFamily: CI.mono, fontSize: 11, color: CI.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>● live</span>
              <button style={{ background: "rgba(0,0,0,0.4)", color: CI.cream, border: `1px solid ${CI.line2}`, padding: "8px 16px", fontFamily: CI.sans, fontSize: 12, cursor: "pointer", backdropFilter: "blur(8px)" }}>Show controls</button>
            </div>
            <div style={{ position: "absolute", bottom: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between", color: CI.cream, fontFamily: CI.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em" }}>
              <span>brian cid · 61 bpm · 6A</span>
              <span>03 / 05</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

Object.assign(window, {
  CinematicDashboard,
  CinematicBrief,
  CinematicCurate,
  CinematicEditor,
  CinematicExport,
  CinematicLive,
});
