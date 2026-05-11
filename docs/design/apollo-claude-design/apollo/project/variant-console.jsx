// Variant B — "Console". Modern dark, structured panels, data-rich.
// Space Grotesk display, JetBrains Mono for data. Electric cyan accent.
//
// Exposes window.Console* for each screen.

const CN = {
  bg:      "#0a0e12",
  surf:    "#10161d",
  surf2:   "#161e27",
  line:    "rgba(180,210,235,0.08)",
  line2:   "rgba(180,210,235,0.16)",
  text:    "#dbe5ee",
  mute:    "rgba(219,229,238,0.55)",
  faint:   "rgba(219,229,238,0.32)",
  cyan:    "#5ee2d8",
  cyan2:   "#34a89e",
  warn:    "#f5a96b",
  red:     "#ef6262",
  green:   "#7bd88f",
  display: '"Space Grotesk", system-ui, sans-serif',
  mono:    '"JetBrains Mono", ui-monospace, monospace',
};

const cnScreen = { width: "100%", height: "100%", background: CN.bg, color: CN.text, fontFamily: CN.display, display: "flex", flexDirection: "column" };
const tag = (color = CN.cyan) => ({ fontFamily: CN.mono, fontSize: 10, color, textTransform: "uppercase", letterSpacing: "0.16em" });

const CnTopbar = ({ session, phase = 0 }) => {
  const phases = ["Brief", "Plan", "Critique", "Edit", "Render", "Live"];
  return (
    <header style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", alignItems: "center", padding: "14px 24px", borderBottom: `1px solid ${CN.line}`, background: CN.surf, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 22, height: 22, background: CN.cyan, position: "relative" }}>
          <div style={{ position: "absolute", inset: 4, background: CN.bg }} />
          <div style={{ position: "absolute", inset: 9, background: CN.cyan }} />
        </div>
        <span style={{ fontFamily: CN.mono, fontSize: 13, fontWeight: 600, letterSpacing: "0.04em" }}>APOLLO</span>
        {session && <span style={{ ...tag(CN.faint) }}>/ {session}</span>}
      </div>
      <div style={{ display: "flex", justifyContent: "center", gap: 0, alignItems: "center" }}>
        {phases.map((p, i) => (
          <React.Fragment key={p}>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 18, height: 18, borderRadius: 2, background: i < phase ? CN.cyan : i === phase ? CN.cyan : "transparent", border: i >= phase ? `1px solid ${CN.line2}` : "none", color: i < phase ? CN.bg : i === phase ? CN.bg : CN.faint, fontFamily: CN.mono, fontSize: 10, display: "grid", placeItems: "center", fontWeight: 600 }}>{i < phase ? "✓" : i + 1}</span>
              <span style={{ ...tag(i === phase ? CN.cyan : i < phase ? CN.text : CN.faint) }}>{p}</span>
            </span>
            {i < phases.length - 1 && <span style={{ width: 24, height: 1, background: i < phase ? CN.cyan2 : CN.line, margin: "0 10px" }} />}
          </React.Fragment>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, ...tag(CN.mute) }}>
        <span>hamletxz</span>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: CN.green }} />
      </div>
    </header>
  );
};

// ───────────────────────────────────── DASHBOARD
const ConsoleDashboard = () => (
  <div style={cnScreen}>
    <CnTopbar />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "240px 1fr", gap: 0 }}>
      <aside style={{ borderRight: `1px solid ${CN.line}`, padding: "20px 16px", background: CN.surf, display: "flex", flexDirection: "column", gap: 4 }}>
        {[["sessions", "Sessions", 6, true], ["catalog", "Catalog", 1842, false], ["renders", "Renders", 23, false], ["live", "Live history", 8, false]].map(([id, l, c, a]) => (
          <button key={id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px", background: a ? CN.surf2 : "transparent", border: "none", color: a ? CN.text : CN.mute, fontFamily: CN.display, fontSize: 13, cursor: "pointer", borderLeft: a ? `2px solid ${CN.cyan}` : "2px solid transparent" }}>
            <span>{l}</span><span style={{ fontFamily: CN.mono, fontSize: 11, color: CN.faint }}>{c}</span>
          </button>
        ))}
        <div style={{ marginTop: 20, ...tag(CN.faint), padding: "0 10px" }}>filters</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "10px" }}>
          {["lofi", "techno", "house", "ambient", "synthwave"].map(g => (
            <span key={g} style={{ ...tag(CN.mute), padding: "4px 8px", border: `1px solid ${CN.line2}`, borderRadius: 2 }}>{g}</span>
          ))}
        </div>
      </aside>
      <section style={{ padding: "24px 32px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 22 }}>
          <div>
            <h1 style={{ fontFamily: CN.display, fontWeight: 500, fontSize: 28, letterSpacing: "-0.02em", margin: 0 }}>Sessions</h1>
            <div style={{ ...tag(CN.faint), marginTop: 6 }}>6 total · 3 ready · 1 live · 2 drafts</div>
          </div>
          <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "10px 16px", fontFamily: CN.mono, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <ApolloIcon.plus /> NEW SESSION
          </button>
        </div>
        <div style={{ border: `1px solid ${CN.line}`, borderRadius: 4, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: "32px 2fr 1.4fr 1fr 100px 60px 80px", padding: "10px 16px", background: CN.surf, ...tag(CN.faint), borderBottom: `1px solid ${CN.line}` }}>
            <span></span><span>name</span><span>genre</span><span>created</span><span>length</span><span>tracks</span><span>status</span>
          </div>
          {APOLLO_SESSIONS.map((s, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "32px 2fr 1.4fr 1fr 100px 60px 80px", padding: "12px 16px", background: i % 2 ? CN.surf : "transparent", alignItems: "center", borderBottom: i < APOLLO_SESSIONS.length - 1 ? `1px solid ${CN.line}` : "none", fontSize: 13 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: s.status === "live" ? CN.cyan : s.status === "ready" ? CN.green : CN.faint, boxShadow: s.status === "live" ? `0 0 8px ${CN.cyan}` : "none" }} />
              <span style={{ fontFamily: CN.display, fontWeight: 500 }}>{s.name}</span>
              <span style={{ fontFamily: CN.mono, fontSize: 12, color: CN.mute }}>{s.genre}</span>
              <span style={{ fontFamily: CN.mono, fontSize: 12, color: CN.mute }}>{s.date}</span>
              <span style={{ fontFamily: CN.mono, fontSize: 12 }}>{fmtDuration(s.duration)}</span>
              <span style={{ fontFamily: CN.mono, fontSize: 12, color: CN.mute }}>{5 + i}</span>
              <span style={{ ...tag(s.status === "live" ? CN.cyan : s.status === "ready" ? CN.green : CN.warn) }}>{s.status}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          {[["sessions this week", "14", CN.cyan], ["hours rendered", "9.2", CN.green], ["live performances", "3", CN.warn]].map(([k, v, c]) => (
            <div key={k} style={{ border: `1px solid ${CN.line}`, padding: "14px 16px", background: CN.surf }}>
              <div style={tag(CN.faint)}>{k}</div>
              <div style={{ fontFamily: CN.mono, fontSize: 28, color: c, marginTop: 6 }}>{v}</div>
            </div>
          ))}
        </div>
      </section>
    </main>
  </div>
);

// ───────────────────────────────────── BRIEF
const ConsoleBrief = () => (
  <div style={cnScreen}>
    <CnTopbar session="new" phase={0} />
    <main style={{ flex: 1, padding: "40px 80px", display: "grid", gridTemplateColumns: "1fr 360px", gap: 40 }}>
      <div>
        <div style={tag(CN.cyan)}>step 01 · brief</div>
        <h1 style={{ fontFamily: CN.display, fontWeight: 400, fontSize: 44, letterSpacing: "-0.025em", margin: "12px 0 8px", lineHeight: 1.05 }}>Describe the session</h1>
        <p style={{ color: CN.mute, fontSize: 15, margin: 0, maxWidth: 520, lineHeight: 1.5 }}>
          Apollo will parse genre, duration, mood, and venue from your prompt. Tweak any field that didn't land right.
        </p>

        <div style={{ marginTop: 32, border: `1px solid ${CN.line2}`, background: CN.surf, padding: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderBottom: `1px solid ${CN.line}`, ...tag(CN.faint) }}>
            <span>prompt</span><span>⌘↵ to parse</span>
          </div>
          <textarea defaultValue="A 30-minute lofi ambient set for a rainy garden afternoon. Soft, contemplative, no peaks." style={{ width: "100%", boxSizing: "border-box", background: "transparent", border: "none", color: CN.text, fontFamily: CN.display, fontSize: 22, padding: "20px 14px", resize: "none", outline: "none", minHeight: 140, lineHeight: 1.4 }} />
        </div>

        <div style={{ marginTop: 24 }}>
          <div style={tag(CN.faint)}>parsed → {`{ … }`}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, marginTop: 12, background: CN.line, border: `1px solid ${CN.line}` }}>
            {[
              ["genre",       "lofi · ambient",          CN.cyan],
              ["duration_min","30",                       CN.cyan],
              ["mood",        "contemplative",            CN.cyan],
              ["energy_target","plateau, no_peaks",       CN.warn],
              ["venue",       "garden · rainy",           CN.cyan],
              ["language",    "instrumental",             CN.faint],
            ].map(([k, v, c]) => (
              <div key={k} style={{ background: CN.surf, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={tag(CN.faint)}>{k}</span>
                <span style={{ fontFamily: CN.mono, fontSize: 14, color: c }}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 28, alignItems: "center" }}>
          <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "12px 20px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            CURATE → <ApolloIcon.arrow />
          </button>
          <button style={{ background: "transparent", color: CN.mute, border: `1px solid ${CN.line2}`, padding: "12px 20px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer" }}>RE-PARSE</button>
        </div>
      </div>

      <aside style={{ background: CN.surf, padding: "20px 22px", border: `1px solid ${CN.line}`, display: "flex", flexDirection: "column", gap: 16, alignSelf: "start" }}>
        <div style={tag(CN.cyan)}>presets</div>
        {[
          ["Late-night focus",   "lofi · 60min · low-energy"],
          ["Friday warehouse",   "techno · 90min · build"],
          ["Sunday brunch",      "neo-soul · 45min · warm"],
          ["Solo run",           "synthwave · 35min · drive"],
        ].map(([n, sub]) => (
          <div key={n} style={{ paddingBottom: 14, borderBottom: `1px solid ${CN.line}`, cursor: "pointer" }}>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{n}</div>
            <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.faint, marginTop: 4 }}>{sub}</div>
          </div>
        ))}
        <div style={{ ...tag(CN.faint), marginTop: 8 }}>tip</div>
        <p style={{ fontSize: 12, color: CN.mute, margin: 0, lineHeight: 1.5 }}>Mention venue ("café", "warehouse", "garden") and Apollo will adjust dynamic range and crowd density assumptions.</p>
      </aside>
    </main>
  </div>
);

// ───────────────────────────────────── CURATE
const ConsoleCurate = () => (
  <div style={cnScreen}>
    <CnTopbar session="lofi · garden chill" phase={2} />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 0 }}>
      <section style={{ padding: "20px 24px", borderRight: `1px solid ${CN.line}`, display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={tag(CN.cyan)}>playlist · v1</div>
            <h2 style={{ fontFamily: CN.display, fontWeight: 500, fontSize: 22, margin: "4px 0 0" }}>5 tracks · 34 min · key flow 5A→6A→6A→6A→5A</h2>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button style={{ ...tag(CN.mute), padding: "6px 10px", border: `1px solid ${CN.line2}`, background: "transparent", cursor: "pointer" }}>v1 · current</button>
            <button style={{ ...tag(CN.faint), padding: "6px 10px", border: `1px solid ${CN.line}`, background: "transparent", cursor: "pointer" }}>+ branch</button>
          </div>
        </div>

        {/* arc visual */}
        <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: "12px 14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={tag(CN.faint)}>energy arc · target plateau</span>
            <span style={tag(CN.warn)}>⚠ flat · consider one peak</span>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 56 }}>
            {APOLLO_TRACKS.map((t, i) => (
              <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <div style={{ width: "100%", height: `${20 + t.energy * 4}%`, background: `linear-gradient(180deg, ${CN.cyan2}, ${CN.cyan})` }} />
                <span style={{ ...tag(CN.faint), fontSize: 9 }}>{t.bpm}</span>
              </div>
            ))}
          </div>
        </div>

        {/* track list */}
        <div style={{ background: CN.surf, border: `1px solid ${CN.line}` }}>
          <div style={{ display: "grid", gridTemplateColumns: "26px 28px 1.6fr 60px 36px 80px 18px", padding: "10px 14px", borderBottom: `1px solid ${CN.line}`, ...tag(CN.faint) }}>
            <span></span><span>#</span><span>track</span><span>bpm</span><span>key</span><span>energy</span><span></span>
          </div>
          {APOLLO_TRACKS.map((t, i) => (
            <div key={t.n} style={{ display: "grid", gridTemplateColumns: "26px 28px 1.6fr 60px 36px 80px 18px", padding: "12px 14px", alignItems: "center", borderBottom: i < APOLLO_TRACKS.length - 1 ? `1px solid ${CN.line}` : "none", fontSize: 13 }}>
              <span style={{ color: CN.faint, cursor: "grab", fontSize: 11 }}><ApolloIcon.drag /></span>
              <span style={{ fontFamily: CN.mono, color: CN.faint }}>{String(t.n).padStart(2, "0")}</span>
              <div>
                <div style={{ fontWeight: 500 }}>{t.title} <span style={{ color: CN.mute, fontWeight: 400 }}>— {t.artist}</span></div>
                <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.faint, marginTop: 2 }}>{t.label}</div>
              </div>
              <span style={{ fontFamily: CN.mono, fontSize: 12 }}>{t.bpm}</span>
              <span style={{ fontFamily: CN.mono, fontSize: 12, color: CN.cyan, padding: "1px 6px", border: `1px solid ${CN.line2}`, borderRadius: 2 }}>{t.key}</span>
              <div style={{ display: "flex", gap: 1.5 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ width: 5, height: 12, background: k < t.energy ? CN.cyan : CN.line2 }} />
                ))}
              </div>
              <ApolloIcon.x />
            </div>
          ))}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0" }}>
          <span style={tag(CN.faint)}>↑↓ reorder · ⌫ remove · ⌘K replace</span>
          <button style={{ background: "transparent", color: CN.cyan, border: `1px solid ${CN.cyan2}`, padding: "8px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <ApolloIcon.plus /> ADD TRACK
          </button>
        </div>
      </section>

      <aside style={{ display: "flex", flexDirection: "column", background: CN.surf }}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${CN.line}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={tag(CN.warn)}>● critic · needs_fixes</span>
            <span style={tag(CN.faint)}>3 notes</span>
          </div>
          <h3 style={{ fontFamily: CN.display, fontSize: 17, fontWeight: 500, margin: "8px 0 0" }}>Two fixes, one win.</h3>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "18px 22px", display: "flex", flexDirection: "column", gap: 16 }}>
          {APOLLO_CRITIC_NOTES.map((n, i) => {
            const tone = n.severity === "fix" ? CN.red : n.severity === "tip" ? CN.warn : CN.green;
            return (
              <article key={i} style={{ background: CN.surf2, border: `1px solid ${CN.line}`, borderLeft: `2px solid ${tone}`, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={tag(tone)}>[{n.severity}] pos {n.target}</span>
                  {n.accepted && <span style={tag(CN.green)}>✓ kept</span>}
                </div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{n.headline}</div>
                <div style={{ fontSize: 12, color: CN.mute, lineHeight: 1.5 }}>{n.body}</div>
                {n.suggestion && <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.cyan, padding: "8px", background: "rgba(94,226,216,0.05)", border: `1px dashed ${CN.cyan2}` }}>→ {n.suggestion}</div>}
                {!n.accepted && (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "6px 12px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.14em", cursor: "pointer", fontWeight: 600 }}>APPLY</button>
                    <button style={{ background: "transparent", color: CN.mute, border: `1px solid ${CN.line2}`, padding: "6px 12px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.14em", cursor: "pointer" }}>EDIT</button>
                    <button style={{ background: "transparent", color: CN.faint, border: "none", padding: "6px 8px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.14em", cursor: "pointer" }}>ignore</button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
        <div style={{ padding: "14px 22px", borderTop: `1px solid ${CN.line}`, display: "flex", gap: 8 }}>
          <button style={{ flex: 1, background: CN.cyan, color: CN.bg, border: "none", padding: "12px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>APPLY ALL → EDITOR</button>
          <button style={{ background: "transparent", color: CN.text, border: `1px solid ${CN.line2}`, padding: "12px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer" }}>SKIP</button>
        </div>
      </aside>
    </main>
  </div>
);

// ───────────────────────────────────── EDITOR
const ConsoleEditor = () => (
  <div style={cnScreen}>
    <CnTopbar session="lofi · garden chill" phase={3} />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 0 }}>
      <section style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={tag(CN.cyan)}>step 04 · edit</div>
            <h2 style={{ fontFamily: CN.display, fontWeight: 500, fontSize: 22, margin: "4px 0 0" }}>Manual control</h2>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button style={{ ...tag(CN.faint), padding: "6px 10px", border: `1px solid ${CN.line2}`, background: "transparent", cursor: "pointer" }}>UNDO ⌘Z</button>
            <button style={{ ...tag(CN.cyan), padding: "6px 10px", border: `1px solid ${CN.cyan2}`, background: "transparent", cursor: "pointer" }}>RUN CRITIC AGAIN</button>
          </div>
        </div>

        {/* timeline grid */}
        <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <span style={tag(CN.faint)}>timeline · 34:12</span>
            <div style={{ display: "flex", gap: 12, ...tag(CN.faint) }}><span>0</span><span>10m</span><span>20m</span><span>30m</span></div>
          </div>
          <div style={{ display: "flex", height: 50, gap: 2 }}>
            {APOLLO_TRACKS.map((t, i) => (
              <div key={i} style={{ flex: t.bpm, background: i === 2 ? CN.cyan : CN.surf2, border: `1px solid ${i === 2 ? CN.cyan : CN.line2}`, padding: "6px 8px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                <span style={{ fontFamily: CN.mono, fontSize: 10, color: i === 2 ? CN.bg : CN.text, fontWeight: 600 }}>{t.title.slice(0, 14)}</span>
                <span style={{ fontFamily: CN.mono, fontSize: 9, color: i === 2 ? CN.bg : CN.faint }}>{t.bpm} · {t.key}</span>
              </div>
            ))}
          </div>
        </div>

        {/* track ops */}
        <div style={{ background: CN.surf, border: `1px solid ${CN.line}` }}>
          {APOLLO_TRACKS.map((t, i) => (
            <div key={t.n} style={{ display: "grid", gridTemplateColumns: "16px 28px 1fr 1fr 70px 80px 50px", padding: "12px 14px", alignItems: "center", borderBottom: i < APOLLO_TRACKS.length - 1 ? `1px solid ${CN.line}` : "none", background: i === 2 ? "rgba(94,226,216,0.05)" : "transparent", fontSize: 13 }}>
              <span style={{ color: CN.faint, cursor: "grab" }}><ApolloIcon.drag /></span>
              <span style={{ fontFamily: CN.mono, color: CN.faint }}>{String(t.n).padStart(2, "0")}</span>
              <div>
                <div style={{ fontWeight: 500 }}>{t.title}</div>
                <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.mute }}>{t.artist}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: CN.mute, fontSize: 11 }}>
                <span>→ next: Δkey {i < APOLLO_TRACKS.length - 1 ? "+1" : "-"} · ΔBPM {i < APOLLO_TRACKS.length - 1 ? "0" : "-"}</span>
              </div>
              <span style={{ fontFamily: CN.mono, fontSize: 12 }}>{t.bpm} BPM</span>
              <div style={{ display: "flex", gap: 1.5 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ width: 5, height: 10, background: k < t.energy ? CN.cyan : CN.line2 }} />
                ))}
              </div>
              <div style={{ display: "flex", gap: 4, justifyContent: "flex-end", color: CN.faint }}>
                <ApolloIcon.spark /><ApolloIcon.x />
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "12px 14px", border: `1px dashed ${CN.line2}`, background: CN.surf }}>
          <span style={tag(CN.cyan)}>cmd</span>
          <input placeholder="swap 3 with brian-cid--errors  ·  build my-set  ·  add deep-house--midnight-groove" style={{ flex: 1, background: "transparent", border: "none", color: CN.text, fontFamily: CN.mono, fontSize: 13, outline: "none" }} />
          <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "6px 14px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>RUN</button>
        </div>
      </section>

      <aside style={{ borderLeft: `1px solid ${CN.line}`, background: CN.surf, padding: "20px 22px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <div style={tag(CN.faint)}>set health</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
            <span style={{ fontFamily: CN.mono, fontSize: 32, color: CN.cyan }}>78</span>
            <span style={{ ...tag(CN.faint) }}>/ 100</span>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[
            ["key flow",      82, CN.cyan],
            ["bpm coherence", 95, CN.green],
            ["energy arc",    42, CN.warn],
            ["mood fit",      88, CN.cyan],
            ["duration",      99, CN.green],
          ].map(([k, v, c]) => (
            <div key={k}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: CN.mute }}>
                <span>{k}</span><span style={{ fontFamily: CN.mono, color: c }}>{v}</span>
              </div>
              <div style={{ height: 4, background: CN.surf2, marginTop: 4 }}>
                <div style={{ width: `${v}%`, height: "100%", background: c }} />
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={tag(CN.faint)}>finalize</div>
          <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "12px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            RENDER → YOUTUBE
          </button>
          <button style={{ background: "transparent", color: CN.cyan, border: `1px solid ${CN.cyan}`, padding: "12px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            <ApolloIcon.play /> GO LIVE
          </button>
        </div>
      </aside>
    </main>
  </div>
);

// ───────────────────────────────────── EXPORT
const ConsoleExport = () => (
  <div style={cnScreen}>
    <CnTopbar session="lofi · garden chill" phase={4} />
    <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
      <section style={{ padding: "32px 40px", borderRight: `1px solid ${CN.line}`, display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <div style={tag(CN.cyan)}>step 05 · render</div>
          <h2 style={{ fontFamily: CN.display, fontWeight: 500, fontSize: 30, margin: "8px 0 0", letterSpacing: "-0.02em" }}>Build async session</h2>
          <p style={{ color: CN.mute, fontSize: 14, marginTop: 8, maxWidth: 420, lineHeight: 1.5 }}>Apollo mixes the set, generates cover art, and packages a YouTube-ready MP4 with chapter markers.</p>
        </div>

        <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
            <span style={tag(CN.cyan)}>job · build_4f21a7d79575</span>
            <span style={tag(CN.warn)}>● running · 02:14 elapsed</span>
          </div>
          <div style={{ height: 8, background: CN.surf2, position: "relative", marginBottom: 16 }}>
            <div style={{ width: "62%", height: "100%", background: `linear-gradient(90deg, ${CN.cyan2}, ${CN.cyan})` }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, fontFamily: CN.mono, fontSize: 12 }}>
            {[
              ["[01/05]", "fetch stems",         "ok",      CN.green],
              ["[02/05]", "align beatgrids",     "ok",      CN.green],
              ["[03/05]", "render crossfades",   "ok",      CN.green],
              ["[04/05]", "master with -14 LUFS","running", CN.warn],
              ["[05/05]", "encode mp4 1080p",    "queued",  CN.faint],
            ].map(([code, lbl, st, c], i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "60px 1fr 80px", color: c }}>
                <span>{code}</span><span style={{ color: c === CN.faint ? CN.faint : CN.text }}>{lbl}</span><span>{st}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 16 }}>
          <div style={tag(CN.faint)}>output</div>
          <div style={{ fontFamily: CN.mono, fontSize: 12, color: CN.mute, marginTop: 8, lineHeight: 1.7 }}>
            <div>format → mp4 · h264 · 1080p · -14 LUFS</div>
            <div>duration → 34:12</div>
            <div>chapters → 5 (one per track)</div>
            <div>cover → static · 1:1 · 1440px</div>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
            <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "10px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>DOWNLOAD .MP4</button>
            <button style={{ background: "transparent", color: CN.text, border: `1px solid ${CN.line2}`, padding: "10px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer" }}>UPLOAD TO YOUTUBE</button>
          </div>
        </div>
      </section>

      <section style={{ padding: "32px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={tag(CN.faint)}>preview</div>
        <div style={{ aspectRatio: "16/9", background: `linear-gradient(135deg, ${CN.surf2}, ${CN.surf})`, border: `1px solid ${CN.line2}`, position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", inset: 0, background: stripePlaceholder("rgba(94,226,216,0.10)") }} />
          <div style={{ position: "absolute", inset: 0, padding: 32, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={tag(CN.cyan)}>APOLLO · 010</div>
            <div>
              <div style={{ fontFamily: CN.display, fontWeight: 500, fontSize: 36, letterSpacing: "-0.02em" }}>lofi for a rainy garden</div>
              <div style={{ fontFamily: CN.mono, fontSize: 12, color: CN.mute, marginTop: 8 }}>5 tracks · 34:12 · contemplative</div>
            </div>
          </div>
        </div>
        <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 14 }}>
          <div style={tag(CN.faint)}>chapters</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontFamily: CN.mono, fontSize: 12 }}>
            {APOLLO_TRACKS.map((t, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "50px 1fr 50px", gap: 12 }}>
                <span style={{ color: CN.cyan }}>{i === 0 ? "00:00" : i === 1 ? "06:50" : i === 2 ? "13:42" : i === 3 ? "20:24" : "27:08"}</span>
                <span>{t.title} — {t.artist}</span>
                <span style={{ color: CN.mute }}>{t.key}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  </div>
);

// ───────────────────────────────────── LIVE
const ConsoleLive = () => {
  const [mode, setMode] = React.useState("cabin");
  return (
    <div style={cnScreen}>
      <CnTopbar session="lofi · garden chill · LIVE" phase={5} />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 24px", borderBottom: `1px solid ${CN.line}`, background: CN.surf }}>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <span style={tag(CN.cyan)}>● live · t+12:48</span>
            <span style={tag(CN.faint)}>track 3 / 5 · target 30:00</span>
          </div>
          <div style={{ display: "flex", gap: 0, padding: 2, border: `1px solid ${CN.line2}` }}>
            {[["cabin", "CABIN"], ["immersive", "IMMERSIVE"], ["audience", "AUDIENCE"]].map(([id, lbl]) => (
              <button key={id} onClick={() => setMode(id)} style={{ background: mode === id ? CN.cyan : "transparent", color: mode === id ? CN.bg : CN.mute, border: "none", padding: "6px 14px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>{lbl}</button>
            ))}
          </div>
        </div>

        {mode === "cabin" && (
          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
            <section style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 18, borderRight: `1px solid ${CN.line}` }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {[
                  ["NOW", "Brian Cid · Mesh",          "61.1 BPM · 6A", CN.cyan],
                  ["NEXT","Trikk · Vilara",            "60.0 BPM · 6A", CN.faint],
                ].map(([k, t, sub, c], i) => (
                  <div key={i} style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: "14px 16px", borderTop: `2px solid ${c}` }}>
                    <div style={tag(c)}>{k}</div>
                    <div style={{ fontSize: 16, fontWeight: 500, marginTop: 8 }}>{t}</div>
                    <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.mute, marginTop: 4 }}>{sub}</div>
                    {i === 0 && <div style={{ fontFamily: CN.mono, fontSize: 11, color: CN.warn, marginTop: 10 }}>crossfade in 29s</div>}
                  </div>
                ))}
              </div>

              {/* waveform */}
              <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 12, height: 80 }}>
                <div style={{ display: "flex", alignItems: "center", height: "100%", gap: 1.5 }}>
                  {Array.from({ length: 100 }).map((_, k) => {
                    const h = 4 + Math.abs(Math.sin(k * 0.5) * 30) + Math.random() * 8;
                    return <span key={k} style={{ flex: 1, height: h, background: k < 62 ? CN.cyan : CN.line2 }} />;
                  })}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 6 }}>
                {[["SKIP", CN.line2], ["STAY", CN.line2], ["+ENERGY", CN.cyan], ["WIND DOWN", CN.line2]].map(([b, c], i) => (
                  <button key={b} style={{ background: c === CN.cyan ? CN.cyan : "transparent", color: c === CN.cyan ? CN.bg : CN.text, border: c === CN.cyan ? "none" : `1px solid ${c}`, padding: "10px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>{b}</button>
                ))}
              </div>

              <div style={{ background: CN.surf, border: `1px solid ${CN.line}`, padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={tag(CN.faint)}>talk to apollo</span>
                  <span style={tag(CN.faint)}>mic perception · OFF</span>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${CN.line2}`, padding: "8px 12px", background: CN.bg }}>
                  <ApolloIcon.mic />
                  <input placeholder='"more groove"  ·  "drop the energy"  ·  "play something darker"' style={{ flex: 1, background: "transparent", border: "none", color: CN.text, fontFamily: CN.mono, fontSize: 12, outline: "none" }} />
                  <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "5px 12px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>SEND</button>
                </div>
                <div style={{ marginTop: 12, fontFamily: CN.mono, fontSize: 11, color: CN.mute, lineHeight: 1.6 }}>
                  <div>{"> "}<span style={{ color: CN.text }}>more groove</span></div>
                  <div style={{ color: CN.cyan }}>{"< "}sticking with mesh — the room feels settled. Lifting at 22:00.</div>
                </div>
              </div>
            </section>

            <section style={{ background: "#000", position: "relative", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", background: CN.surf, borderBottom: `1px solid ${CN.line}` }}>
                <div style={{ display: "flex", gap: 0 }}>
                  {["PARTICLES", "STROBE", "FRACTAL", "VINYL"].map((v, i) => (
                    <button key={v} style={{ background: i === 0 ? CN.cyan : "transparent", color: i === 0 ? CN.bg : CN.mute, border: "none", padding: "5px 10px", fontFamily: CN.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.14em", fontWeight: 600, cursor: "pointer" }}>{v}</button>
                  ))}
                </div>
                <span style={tag(CN.faint)}>fullscreen ↗</span>
              </div>
              <div style={{ flex: 1, position: "relative", overflow: "hidden", background: "#000" }}>
                <div style={{ position: "absolute", inset: 0, background: stripePlaceholder("rgba(94,226,216,0.14)") }} />
                <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
                  <svg width="240" height="240" viewBox="0 0 200 200">
                    {Array.from({ length: 36 }).map((_, k) => {
                      const a = (k / 36) * Math.PI * 2;
                      const r1 = 60 + (k % 3) * 20;
                      return <line key={k} x1={100} y1={100} x2={100 + Math.cos(a) * r1} y2={100 + Math.sin(a) * r1} stroke={CN.cyan} strokeWidth="0.5" opacity={0.4 + (k % 3) * 0.2} />;
                    })}
                    <circle cx="100" cy="100" r="20" fill={CN.cyan} opacity="0.8" />
                  </svg>
                </div>
                <div style={{ position: "absolute", bottom: 14, left: 14, right: 14, display: "flex", justifyContent: "space-between", fontFamily: CN.mono, fontSize: 10, color: CN.mute }}>
                  <span>[heartbeat] gA=0.82 gB=0.18 ready=4</span>
                  <span>61 BPM · 6A</span>
                </div>
              </div>
            </section>
          </div>
        )}

        {mode === "immersive" && (
          <div style={{ flex: 1, position: "relative", background: "#000", overflow: "hidden" }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 60%, rgba(94,226,216,0.20), transparent 70%)` }} />
            <div style={{ position: "absolute", inset: 0, background: stripePlaceholder("rgba(94,226,216,0.10)") }} />
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
              {Array.from({ length: 80 }).map((_, k) => (
                <circle key={k} cx={Math.random() * 800} cy={Math.random() * 600} r={Math.random() * 3} fill={CN.cyan} opacity={Math.random() * 0.8} />
              ))}
            </svg>
            <div style={{ position: "absolute", top: 24, left: 28, right: 28, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={tag(CN.cyan)}>● live</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={{ background: "rgba(0,0,0,0.5)", color: CN.text, border: `1px solid ${CN.line2}`, padding: "8px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", cursor: "pointer", backdropFilter: "blur(8px)" }}>controls</button>
                <button style={{ background: CN.cyan, color: CN.bg, border: "none", padding: "8px 14px", fontFamily: CN.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.16em", fontWeight: 600, cursor: "pointer" }}>QUIT</button>
              </div>
            </div>
            <div style={{ position: "absolute", bottom: 28, left: 28, right: 28 }}>
              <div style={tag(CN.cyan)}>now playing · 61 BPM · 6A</div>
              <div style={{ fontFamily: CN.display, fontSize: 56, fontWeight: 500, letterSpacing: "-0.025em", color: "#fff", marginTop: 8 }}>Brian Cid — Mesh</div>
              <div style={{ width: 320, height: 2, background: CN.line2, marginTop: 18, position: "relative" }}>
                <div style={{ position: "absolute", left: 0, top: 0, width: "62%", height: "100%", background: CN.cyan }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", width: 320, marginTop: 6, fontFamily: CN.mono, fontSize: 10, color: CN.mute }}>
                <span>03:18</span><span>05:24</span>
              </div>
            </div>
          </div>
        )}

        {mode === "audience" && (
          <div style={{ flex: 1, background: "#000", display: "grid", placeItems: "center", padding: 60, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at center, rgba(94,226,216,0.15), transparent 70%)` }} />
            <div style={{ textAlign: "center", position: "relative" }}>
              <div style={{ fontFamily: CN.mono, fontSize: 14, color: CN.cyan, letterSpacing: "0.32em", textTransform: "uppercase", marginBottom: 32 }}>● APOLLO LIVE</div>
              <div style={{ fontFamily: CN.display, fontSize: 130, fontWeight: 500, letterSpacing: "-0.04em", color: "#fff", lineHeight: 0.9 }}>MESH</div>
              <div style={{ fontFamily: CN.display, fontSize: 36, fontWeight: 400, color: CN.cyan, marginTop: 12 }}>BRIAN CID</div>
              <div style={{ width: 200, height: 1, background: CN.cyan, opacity: 0.5, margin: "40px auto" }} />
              <div style={{ fontFamily: CN.mono, fontSize: 13, color: CN.mute, letterSpacing: "0.18em", textTransform: "uppercase" }}>03 OF 05 · GARDEN CHILL · 30 MIN</div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

Object.assign(window, {
  ConsoleDashboard,
  ConsoleBrief,
  ConsoleCurate,
  ConsoleEditor,
  ConsoleExport,
  ConsoleLive,
});
