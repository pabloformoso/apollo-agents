// Apollo prototype — six screens, fully interactive.
// All screens read state from a single useReducer in the App; navigation is route-only.

const { useState, useReducer, useEffect, useRef, useContext, useMemo } = React;

// ─────────────────────────────────────────── SHARED ───
const Crumb = ({ children }) => (
  <span style={{ fontFamily: PT.mono, fontSize: 10, color: PT.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{children}</span>
);
const Btn = ({ children, kind = "primary", onClick, style = {}, disabled }) => {
  const variants = {
    primary:   { background: PT.red, color: PT.cream, border: "none" },
    cream:     { background: PT.cream, color: PT.ink, border: "none" },
    ghost:     { background: "transparent", color: PT.text, border: `1px solid ${PT.line2}` },
    quiet:     { background: "transparent", color: PT.faint, border: "none" },
  };
  return (
    <button onClick={onClick} disabled={disabled} style={{ ...variants[kind], padding: "12px 22px", fontFamily: PT.sans, fontSize: 14, fontWeight: 500, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1, display: "inline-flex", alignItems: "center", gap: 10, transition: "transform 80ms ease", ...style }}>{children}</button>
  );
};
const Arrow = () => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.5" fill="none"><path d="M3 8h10M9 4l4 4-4 4"/></svg>;
const Plus = () => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.5" fill="none"><path d="M8 3v10M3 8h10"/></svg>;
const Mic = () => <svg viewBox="0 0 16 16" width="14" height="14" stroke="currentColor" strokeWidth="1.4" fill="none"><rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.5 8.5a4.5 4.5 0 009 0M8 13v2"/></svg>;

// ─────────────────────────────────────────── DASHBOARD ───
const Dashboard = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  return (
    <div style={{ flex: 1 }}>
      {/* hero */}
      <section style={{ padding: "60px 60px 48px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 60, alignItems: "end", borderBottom: `1px solid ${PT.line}` }}>
        <div>
          <Crumb>tonight · curated for you</Crumb>
          <h1 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 88, fontWeight: 400, letterSpacing: "-0.035em", lineHeight: 0.95, margin: "16px 0 0" }}>
            What will you<br />make tonight<span style={{ color: PT.red }}>?</span>
          </h1>
          <p style={{ fontSize: 16, color: PT.mute, marginTop: 24, maxWidth: 380, lineHeight: 1.55 }}>
            Tell Apollo what you want to hear and it will assemble, critique, and either render it for you — or perform it live.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
            <Btn onClick={() => { dispatch({ type: "new" }); go("brief"); }}>Start a session <Arrow /></Btn>
            <Btn kind="ghost">Browse catalog</Btn>
          </div>
        </div>
        <div style={{ aspectRatio: "5/4", background: stripe(0.18), border: `1px solid ${PT.line2}`, position: "relative", display: "flex", alignItems: "flex-end", padding: 28 }}>
          <span style={{ position: "absolute", top: 18, left: 24 }}><Crumb>last performed · live</Crumb></span>
          <div>
            <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 54, lineHeight: 0.95, color: PT.cream }}>warehouse,<br />4am.</div>
            <div style={{ fontFamily: PT.mono, fontSize: 11, color: PT.mute, marginTop: 14, letterSpacing: "0.18em" }}>TECHNO · 120 MIN · 18 TRACKS</div>
          </div>
        </div>
      </section>

      <section style={{ padding: "40px 60px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 24 }}>
          <h2 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 32, fontWeight: 400, letterSpacing: "-0.02em", margin: 0 }}>Recent sessions</h2>
          <Crumb>{PROTO_SESSIONS.length} sessions · 7h 45m</Crumb>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 }}>
          {PROTO_SESSIONS.map((s, i) => {
            const colors = ["232,85,58", "232,85,58", "240,177,90", "155,191,122", "240,177,90", "232,85,58"];
            return (
              <article key={s.id} onClick={() => { if (s.status === "live") go("live"); else go("curate"); }} style={{ display: "flex", flexDirection: "column", gap: 14, cursor: "pointer" }}>
                <div style={{ aspectRatio: "1/1", background: `${PT.surf} url("data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-1,1 l2,-2 M0,8 l8,-8 M7,9 l2,-2' stroke='rgba(${colors[i]},0.18)' stroke-width='1'/></svg>`)}")`, border: `1px solid ${PT.line}`, position: "relative", padding: 18, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                  <span style={{ fontFamily: PT.mono, fontSize: 9, color: s.status === "live" ? PT.red : PT.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>
                    {s.status === "live" ? "● LIVE NOW" : `№ ${String(i + 1).padStart(2, "0")}`}
                  </span>
                  <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 28, lineHeight: 1.0, color: PT.cream }}>{s.name.split(" · ")[0]}</div>
                </div>
                <div>
                  <div style={{ fontSize: 14 }}>{s.name}</div>
                  <div style={{ fontFamily: PT.mono, fontSize: 10, color: PT.faint, textTransform: "uppercase", letterSpacing: "0.16em", marginTop: 4 }}>
                    {s.genre} · {fmtDur(s.duration)} · {s.date}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
};

// ─────────────────────────────────────────── BRIEF ───
const Brief = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  const [text, setText] = useState(state.brief.text);
  const [busy, setBusy] = useState(false);

  // naive parse
  const parsed = useMemo(() => {
    const t = text.toLowerCase();
    const dur = (t.match(/(\d+)\s*(min|minute|m)\b/) || t.match(/(\d+)\s*hour|h\b/));
    const venueMatch = t.match(/(garden|cafe|bar|club|warehouse|office|home|car|gym)/);
    const moodMatch  = t.match(/(chill|contemplative|warm|dark|intense|easy|peaky|peak|melancholic|euphoric|focus)/);
    const genreMatch = t.match(/(lofi|ambient|techno|house|deep house|neo[-\s]?soul|synthwave|jazz|trance|garage|drum and bass|dnb)/);
    return {
      genre:    genreMatch ? genreMatch[1] : "—",
      duration: dur ? `${dur[1]} ${dur[2] || "min"}` : "—",
      mood:     moodMatch ? moodMatch[1] : "—",
      venue:    venueMatch ? venueMatch[1] : "—",
      energy:   /peak|build|intens/.test(t) ? "with peak" : "plateau, no peaks",
      tempo:    /lofi|ambient/.test(t) ? "58–66 BPM" : /techno/.test(t) ? "126–134 BPM" : "auto",
    };
  }, [text]);

  const submit = () => {
    setBusy(true);
    dispatch({ type: "setBrief", payload: { text, parsed } });
    // simulate plan + critique
    setTimeout(() => { dispatch({ type: "planComplete" }); setBusy(false); go("curate"); }, 1400);
  };

  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
      <section style={{ padding: "60px 60px", display: "flex", flexDirection: "column", justifyContent: "center", borderRight: `1px solid ${PT.line}` }}>
        <Crumb>01 · brief</Crumb>
        <h1 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 80, fontWeight: 400, letterSpacing: "-0.03em", lineHeight: 0.95, margin: "8px 0 0" }}>
          One sentence.<br />That's all<br />I need<span style={{ color: PT.red }}>.</span>
        </h1>
        <p style={{ fontSize: 16, color: PT.mute, marginTop: 24, maxWidth: 420, lineHeight: 1.55 }}>
          Tell me the genre, the duration, the mood and where you'll listen. I'll fill the rest in and only ask if I really need to.
        </p>
        <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 8, fontFamily: PT.mono, fontSize: 11, color: PT.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>
          {[
            "30 minutes of lofi for a rainy garden",
            "Ninety-minute techno set, build slowly, peak at minute 60",
            "Sunday brunch, neo-soul, warm and easy",
          ].map(p => (
            <button key={p} onClick={() => setText(p)} style={{ background: "transparent", border: "none", color: "inherit", padding: 0, textAlign: "left", cursor: "pointer", textTransform: "none", letterSpacing: 0, fontFamily: PT.display, fontStyle: "italic", fontSize: 16 }}>
              <span style={{ color: PT.red, marginRight: 8 }}>›</span> "{p}"
            </button>
          ))}
        </div>
      </section>

      <section style={{ background: PT.surf, padding: "40px 50px", display: "flex", flexDirection: "column", gap: 28 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
          <Crumb><span style={{ color: PT.red }}>your prompt</span></Crumb>
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="A 30-minute lofi ambient set for a rainy garden afternoon…"
            style={{ background: "transparent", border: "none", color: PT.cream, fontFamily: PT.display, fontStyle: "italic", fontSize: 32, lineHeight: 1.25, letterSpacing: "-0.015em", resize: "none", outline: "none", minHeight: 180, padding: 0 }} />
          <div style={{ height: 1, background: PT.line2 }} />
        </div>
        <div>
          <Crumb>understood as</Crumb>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 14 }}>
            {[
              ["Genre", parsed.genre],
              ["Duration", parsed.duration],
              ["Mood", parsed.mood],
              ["Venue", parsed.venue],
              ["Energy", parsed.energy],
              ["Tempo", parsed.tempo],
            ].map(([k, v]) => (
              <div key={k} style={{ borderTop: `1px solid ${PT.line}`, paddingTop: 8 }}>
                <Crumb>{k}</Crumb>
                <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 20, marginTop: 2, color: v === "—" ? PT.faint : PT.text }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.faint }}>{busy ? "Apollo is curating…" : "⌘ + ↵"}</span>
          <Btn onClick={submit} disabled={busy || !text.trim()} style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 18 }}>
            {busy ? "Curating…" : <>Curate this set <Arrow /></>}
          </Btn>
        </div>
      </section>
    </div>
  );
};

// ─────────────────────────────────────────── CURATE ───
const Curate = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  const tracks = state.tracks;
  const arc = useMemo(() => {
    const max = Math.max(...tracks.map(t => t.energy));
    return max < 5 ? "flat" : "shaped";
  }, [tracks]);

  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "220px 1fr 380px" }}>
      {/* left rail */}
      <aside style={{ borderRight: `1px solid ${PT.line}`, padding: "28px 22px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ aspectRatio: "1/1", background: stripe(0.18), border: `1px solid ${PT.line}`, padding: 14, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <Crumb><span style={{ color: PT.red }}>apollo · 010</span></Crumb>
          <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 24, lineHeight: 0.95 }}>{state.brief.parsed.genre === "—" ? "lofi for\na rainy\ngarden" : state.brief.parsed.genre}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12 }}>
          {[
            ["Tracks",  tracks.length],
            ["Length",  `${Math.floor(tracks.length * 6.8)}m`],
            ["Avg BPM", (tracks.reduce((a, t) => a + t.bpm, 0) / tracks.length).toFixed(1)],
            ["Key flow", `${tracks[0]?.key}→${tracks[tracks.length - 1]?.key}`],
            ["Energy",  arc],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", color: PT.mute }}>
              <span>{k}</span>
              <span style={{ color: arc === "flat" && k === "Energy" ? PT.warn : PT.text, fontFamily: PT.mono }}>{v}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: "auto" }}>
          <Crumb>versions</Crumb>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
            {[["v1", true], ["v2 (peakier)", false]].map(([n, a]) => (
              <button key={n} style={{ background: a ? PT.surf2 : "transparent", color: a ? PT.text : PT.mute, border: `1px solid ${a ? PT.line2 : "transparent"}`, padding: "6px 10px", fontFamily: PT.mono, fontSize: 11, textAlign: "left", cursor: "pointer" }}>{n}</button>
            ))}
            <button style={{ background: "transparent", color: PT.faint, border: `1px dashed ${PT.line2}`, padding: "6px 10px", fontFamily: PT.mono, fontSize: 11, textAlign: "left", cursor: "pointer" }}>+ branch</button>
          </div>
        </div>
      </aside>

      {/* center */}
      <section style={{ padding: "28px 36px", display: "flex", flexDirection: "column", gap: 18, overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <Crumb>02 · curate</Crumb>
            <h2 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 36, fontWeight: 400, letterSpacing: "-0.02em", margin: "4px 0 0" }}>The set</h2>
          </div>
          <Btn kind="ghost" onClick={() => go("editor")}>Edit by hand</Btn>
        </div>

        {/* arc strip */}
        <div style={{ position: "relative", padding: "12px 0", borderTop: `1px solid ${PT.line}`, borderBottom: `1px solid ${PT.line}` }}>
          <Crumb>arc · {arc === "flat" ? "! flat" : "shaped"}</Crumb>
          <svg viewBox="0 0 600 60" preserveAspectRatio="none" style={{ width: "100%", height: 50, marginTop: 6 }}>
            <line x1="0" y1="40" x2="600" y2="40" stroke={PT.line2} strokeDasharray="2 4" />
            {tracks.map((t, i) => {
              const x = (i + 0.5) * (600 / tracks.length);
              const y = 50 - t.energy * 5;
              return (
                <g key={i}>
                  <line x1={x} y1="50" x2={x} y2={y} stroke={PT.red} strokeWidth="1.5" opacity="0.5"/>
                  <circle cx={x} cy={y} r="4" fill={PT.red}/>
                </g>
              );
            })}
            <path d={tracks.map((t, i) => {
              const x = (i + 0.5) * (600 / tracks.length);
              const y = 50 - t.energy * 5;
              return `${i === 0 ? "M" : "L"}${x} ${y}`;
            }).join(" ")} stroke={PT.red} strokeWidth="1" fill="none" opacity="0.6"/>
          </svg>
        </div>

        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 0, overflow: "auto" }}>
          {tracks.map((t, i) => (
            <li key={t.n} style={{ display: "grid", gridTemplateColumns: "32px 60px 1fr 70px 50px 90px 28px", gap: 16, alignItems: "center", padding: "14px 0", borderBottom: `1px solid ${PT.line}` }}>
              <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 26, color: PT.faint }}>{String(i + 1).padStart(2, "0")}</span>
              <div style={{ width: 50, height: 50, background: stripe(0.16 + i * 0.04), border: `1px solid ${PT.line}` }} />
              <div>
                <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 22, lineHeight: 1.1 }}>{t.title}</div>
                <div style={{ fontSize: 12, color: PT.mute, marginTop: 4 }}>{t.artist} · <span style={{ fontFamily: PT.mono, fontSize: 10, color: PT.faint }}>{t.label}</span></div>
              </div>
              <span style={{ fontFamily: PT.mono, fontSize: 12, color: PT.mute }}>{t.bpm} BPM</span>
              <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.red, padding: "2px 8px", border: `1px solid ${PT.line2}`, textAlign: "center" }}>{t.key}</span>
              <div style={{ display: "flex", gap: 2 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 12, background: k < t.energy ? PT.red : PT.line2 }} />
                ))}
              </div>
              <button onClick={() => dispatch({ type: "removeTrack", n: t.n })} style={{ background: "transparent", border: "none", color: PT.faint, cursor: "pointer", fontSize: 14 }}>×</button>
            </li>
          ))}
        </ul>
      </section>

      {/* right: critic */}
      <aside style={{ borderLeft: `1px solid ${PT.line}`, background: PT.surf, padding: "28px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <Crumb><span style={{ color: PT.red }}>note from the critic</span></Crumb>
          <h3 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 32, fontWeight: 400, letterSpacing: "-0.02em", margin: "6px 0 0", lineHeight: 1.05 }}>"{state.notes.filter(n => n.severity === "fix").length} fixes,<br />{state.notes.filter(n => n.severity === "ok").length} win."</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1, overflow: "auto" }}>
          {state.notes.map((n, i) => {
            const tone = n.severity === "fix" ? PT.red : n.severity === "tip" ? PT.warn : PT.green;
            const handled = state.handled.includes(n.id);
            return (
              <article key={n.id} style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 14, borderBottom: i < state.notes.length - 1 ? `1px solid ${PT.line}` : "none", opacity: handled ? 0.5 : 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontFamily: PT.mono, fontSize: 10, color: tone, textTransform: "uppercase", letterSpacing: "0.18em" }}>{n.severity} · pos {n.target}</span>
                  {(n.severity === "ok" || handled) && <span style={{ fontFamily: PT.mono, fontSize: 10, color: PT.green }}>✓ {handled ? "applied" : "kept"}</span>}
                </div>
                <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 19, lineHeight: 1.2 }}>{n.headline}</div>
                <div style={{ fontSize: 12, color: PT.mute, lineHeight: 1.55 }}>{n.body}</div>
                {n.suggestion && <div style={{ fontFamily: PT.mono, fontSize: 11, color: PT.warn, paddingTop: 6 }}>→ {n.suggestion}</div>}
                {n.severity !== "ok" && !handled && (
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <Btn style={{ padding: "7px 12px", fontSize: 11 }} onClick={() => dispatch({ type: "applyNote", id: n.id })}>Apply</Btn>
                    <Btn kind="ghost" style={{ padding: "7px 12px", fontSize: 11 }} onClick={() => go("editor")}>Edit</Btn>
                    <Btn kind="quiet" style={{ padding: "7px 4px", fontSize: 11 }} onClick={() => dispatch({ type: "ignoreNote", id: n.id })}>ignore</Btn>
                  </div>
                )}
              </article>
            );
          })}
        </div>
        <Btn onClick={() => go("export")} style={{ justifyContent: "center", padding: "14px" }}>Looks good — Materialize <Arrow /></Btn>
      </aside>
    </div>
  );
};

// ─────────────────────────────────────────── EDITOR ───
const Editor = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  const [sel, setSel] = useState(2); // index
  const [cmd, setCmd] = useState("");
  const tracks = state.tracks;

  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px" }}>
      <section style={{ padding: "32px 48px", display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <Crumb><span style={{ color: PT.red }}>your move</span></Crumb>
          <h2 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 44, fontWeight: 400, letterSpacing: "-0.02em", margin: "4px 0 0" }}>Sequence the night.</h2>
        </div>
        <div style={{ display: "flex", gap: 12, overflow: "auto", paddingBottom: 8 }}>
          {tracks.map((t, i) => (
            <button key={t.n} onClick={() => setSel(i)} style={{ flex: "0 0 200px", border: `1px solid ${i === sel ? PT.red : PT.line}`, background: i === sel ? "rgba(232,85,58,0.08)" : PT.surf, padding: 16, display: "flex", flexDirection: "column", gap: 10, position: "relative", cursor: "pointer", color: PT.text, textAlign: "left" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 22, color: PT.faint }}>{String(i + 1).padStart(2, "0")}</span>
                <span style={{ fontFamily: PT.mono, fontSize: 10, color: PT.mute }}>{t.bpm}·{t.key}</span>
              </div>
              <div style={{ aspectRatio: "1/1", background: stripe(0.18, PT.ink), border: `1px solid ${PT.line}` }} />
              <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 18, lineHeight: 1.1 }}>{t.title}</div>
              <div style={{ fontSize: 11, color: PT.mute }}>{t.artist}</div>
              <div style={{ display: "flex", gap: 1 }}>
                {Array.from({ length: 10 }).map((_, k) => (
                  <span key={k} style={{ flex: 1, height: 6, background: k < t.energy ? PT.red : PT.line2 }} />
                ))}
              </div>
              {i === sel && <span style={{ position: "absolute", top: -10, right: -10, background: PT.red, color: PT.cream, fontFamily: PT.mono, fontSize: 9, padding: "3px 8px", textTransform: "uppercase", letterSpacing: "0.14em" }}>editing</span>}
            </button>
          ))}
          <button onClick={() => dispatch({ type: "addTrack" })} style={{ flex: "0 0 200px", border: `1px dashed ${PT.line2}`, background: "transparent", padding: 16, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, color: PT.faint, cursor: "pointer" }}>
            <Plus />
            <span style={{ fontSize: 12 }}>Add a track</span>
          </button>
        </div>

        <div style={{ background: PT.surf, border: `1px solid ${PT.line}`, padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <Crumb>arc &amp; transitions</Crumb>
          </div>
          <svg viewBox="0 0 500 80" preserveAspectRatio="none" style={{ width: "100%", height: 80 }}>
            <defs><linearGradient id="ed-arc" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={PT.red} stopOpacity="0.4"/><stop offset="100%" stopColor={PT.red} stopOpacity="0"/></linearGradient></defs>
            <line x1="0" y1="60" x2="500" y2="60" stroke={PT.line2} strokeDasharray="3 3"/>
            <path d={tracks.map((t, i) => `${i === 0 ? "M" : "L"}${(i + 0.5) * (500 / tracks.length)} ${60 - t.energy * 4}`).join(" ")} stroke={PT.red} strokeWidth="1.5" fill="none"/>
            {tracks.map((t, i) => (
              <g key={i} transform={`translate(${(i + 0.5) * (500 / tracks.length)}, 0)`}>
                <circle cx="0" cy={60 - t.energy * 4} r="3" fill={i === sel ? PT.red : PT.cream}/>
                <text x="0" y="78" textAnchor="middle" fontFamily={PT.mono} fontSize="9" fill={PT.faint}>{t.key}</text>
              </g>
            ))}
          </svg>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); if (cmd.trim()) { dispatch({ type: "command", cmd }); setCmd(""); }}} style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${PT.line2}`, background: PT.surf, padding: "12px 16px" }}>
          <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.red }}>›</span>
          <input value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder='swap track 3 · build "garden-chill" · add brian-cid—errors' style={{ flex: 1, background: "transparent", border: "none", color: PT.text, fontFamily: PT.mono, fontSize: 13, outline: "none" }}/>
          <Btn kind="cream" style={{ padding: "7px 16px", fontSize: 11 }}>Run</Btn>
        </form>
      </section>

      <aside style={{ borderLeft: `1px solid ${PT.line}`, padding: "32px 28px", display: "flex", flexDirection: "column", gap: 22, background: PT.surf }}>
        <div>
          <Crumb>then</Crumb>
          <h3 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 30, fontWeight: 400, letterSpacing: "-0.02em", margin: "6px 0 0" }}>Materialize.</h3>
        </div>
        <button onClick={() => go("export")} style={{ background: PT.cream, color: PT.ink, border: "none", padding: "20px 18px", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, cursor: "pointer", textAlign: "left", fontFamily: PT.sans }}>
          <span style={{ fontFamily: PT.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.18em", color: PT.red2 }}>route a · async</span>
          <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 26, lineHeight: 1.0 }}>Render to YouTube</span>
          <span style={{ fontSize: 12, color: "rgba(10,8,7,0.7)", marginTop: 4 }}>Apollo presses the vinyl. 1080p MP4 with chapters.</span>
        </button>
        <button onClick={() => go("live")} style={{ background: PT.red, color: PT.cream, border: "none", padding: "20px 18px", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, cursor: "pointer", textAlign: "left", fontFamily: PT.sans }}>
          <span style={{ fontFamily: PT.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.18em", color: "rgba(255,255,255,0.7)" }}>route b · live</span>
          <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 26, lineHeight: 1.0 }}>Apollo, take the booth</span>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 4 }}>Real-time mixing with mic awareness and visuals.</span>
        </button>
        <div style={{ marginTop: "auto" }}>
          <Crumb>set health · 78 / 100</Crumb>
          <div style={{ height: 3, background: PT.line, marginTop: 6, position: "relative" }}>
            <div style={{ width: "78%", height: "100%", background: PT.red }}/>
          </div>
        </div>
      </aside>
    </div>
  );
};

// ─────────────────────────────────────────── EXPORT ───
const Export = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  const [pct, setPct] = useState(state.export.pct);
  useEffect(() => {
    if (pct >= 100) return;
    const id = setInterval(() => setPct(p => Math.min(100, p + 1.6)), 120);
    return () => clearInterval(id);
  }, [pct]);
  useEffect(() => { dispatch({ type: "setExportPct", pct }); }, [pct]);
  const stages = [
    ["Stems aligned",        pct >  4],
    ["Crossfades rendered",  pct > 22],
    ["Mastering · -14 LUFS", pct > 50],
    ["Cover composed",       pct > 74],
    ["MP4 encoded · 1080p",  pct >= 100],
  ];

  return (
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.1fr 1fr" }}>
      <section style={{ padding: "40px 48px", borderRight: `1px solid ${PT.line}`, display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <Crumb><span style={{ color: PT.red }}>release · async</span></Crumb>
          <h2 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 56, fontWeight: 400, letterSpacing: "-0.025em", margin: "4px 0 0", lineHeight: 0.95 }}>
            {pct < 100 ? <>Pressing<br />the vinyl.</> : <>Vinyl's<br />ready.</>}
          </h2>
        </div>
        <div style={{ aspectRatio: "5/7", background: stripe(0.16), border: `1px solid ${PT.line2}`, position: "relative", padding: 28, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div>
            <Crumb><span style={{ color: PT.red }}>APOLLO · 010</span></Crumb>
            <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 56, lineHeight: 0.95, color: PT.cream, marginTop: 16 }}>lofi for<br />a rainy<br />garden,<br />2026</div>
          </div>
          <div style={{ fontFamily: PT.mono, fontSize: 10, color: PT.mute, textTransform: "uppercase", letterSpacing: "0.18em", lineHeight: 1.6 }}>
            <div>{state.tracks.length} tracks · 34:12</div>
            <div>contemplative · ambient · 60 BPM avg</div>
            <div>curated by Apollo for hamletxz</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Btn kind="cream" style={{ flex: 1, justifyContent: "center" }} disabled={pct < 100}>Download MP4</Btn>
          <Btn kind="ghost" style={{ flex: 1, justifyContent: "center" }} disabled={pct < 100}>Upload to YouTube</Btn>
        </div>
      </section>

      <section style={{ padding: "40px 48px", display: "flex", flexDirection: "column", gap: 24 }}>
        <div>
          <Crumb>render · {Math.floor(pct * 0.036)} min elapsed</Crumb>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 6 }}>
            <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 56, color: PT.red }}>{Math.round(pct)}%</span>
            <Crumb>~ {Math.max(0, Math.ceil((100 - pct) * 1.4))}s left</Crumb>
          </div>
          <div style={{ height: 4, background: PT.surf2, marginTop: 14, position: "relative" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: PT.red, transition: "width 200ms" }}/>
          </div>
        </div>
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          {stages.map(([label, done], i) => {
            const running = !done && (i === 0 || stages[i - 1][1]);
            return (
              <li key={i} style={{ display: "grid", gridTemplateColumns: "20px 1fr 80px", alignItems: "center", paddingBottom: 12, borderBottom: `1px solid ${PT.line}` }}>
                <span style={{ color: done ? PT.green : running ? PT.red : PT.faint, fontFamily: PT.mono, fontSize: 12 }}>{done ? "✓" : running ? "●" : "○"}</span>
                <span style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 19 }}>{label}</span>
                <span style={{ fontFamily: PT.mono, fontSize: 10, color: done ? PT.green : running ? PT.red : PT.faint, textTransform: "uppercase", letterSpacing: "0.18em" }}>{done ? "complete" : running ? "running" : "queued"}</span>
              </li>
            );
          })}
        </ul>
        <div style={{ marginTop: "auto", padding: 18, background: PT.surf, border: `1px solid ${PT.line}` }}>
          <Crumb>chapters</Crumb>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontFamily: PT.mono, fontSize: 12, color: PT.mute }}>
            {state.tracks.map((t, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr 36px" }}>
                <span style={{ color: PT.red }}>{["00:00","06:50","13:42","20:24","27:08","33:45","40:10"][i] || "—"}</span>
                <span style={{ color: PT.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title} · {t.artist}</span>
                <span>{t.key}</span>
              </div>
            ))}
          </div>
        </div>
        {pct >= 100 && (
          <Btn onClick={() => go("dashboard")} style={{ alignSelf: "flex-start" }}>Back to library <Arrow /></Btn>
        )}
      </section>
    </div>
  );
};

// ─────────────────────────────────────────── LIVE ───
const Live = ({ state, dispatch }) => {
  const { go } = useContext(Router);
  const [mode, setMode] = useState("audience");
  const [trackIx, setTrackIx] = useState(2);
  const [cmd, setCmd] = useState("");
  const [chat, setChat] = useState([
    { who: "apollo", text: "Sticking with Mesh — the room feels settled. Lifting at 22:00." },
  ]);
  const [intent, setIntent] = useState("more energy");

  const t = state.tracks[trackIx];
  const next = state.tracks[(trackIx + 1) % state.tracks.length];
  const send = (e) => {
    e?.preventDefault();
    if (!cmd.trim()) return;
    setChat(c => [...c, { who: "you", text: cmd }, { who: "apollo", text: `Heard. Adjusting toward "${cmd.toLowerCase()}".` }]);
    setCmd("");
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 36px", borderBottom: `1px solid ${PT.line}`, background: PT.surf }}>
        <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
          <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>● broadcasting</span>
          <Crumb>{String(trackIx + 1).padStart(2, "0")} / {String(state.tracks.length).padStart(2, "0")} · 12:48 elapsed · target 30:00</Crumb>
        </div>
        <div style={{ display: "flex", gap: 4, padding: 3, border: `1px solid ${PT.line2}` }}>
          {[["audience", "Audience"], ["cabin", "Booth"], ["immersive", "Immersive"]].map(([id, lbl]) => (
            <button key={id} onClick={() => setMode(id)} style={{ background: mode === id ? PT.cream : "transparent", color: mode === id ? PT.ink : PT.mute, border: "none", padding: "6px 16px", fontFamily: PT.sans, fontSize: 12, cursor: "pointer" }}>{lbl}</button>
          ))}
        </div>
        <Btn kind="ghost" style={{ padding: "8px 14px", fontSize: 12 }} onClick={() => { if (confirm("End the live session?")) go("dashboard"); }}>Quit</Btn>
      </div>

      {mode === "audience" && (
        <div style={{ flex: 1, position: "relative", background: "#000", display: "grid", placeItems: "center", overflow: "hidden", padding: 40 }}>
          <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 50%, rgba(232,85,58,0.20), transparent 70%)` }} />
          <div style={{ position: "absolute", inset: 0, background: stripe(0.10, "transparent") }} />
          <div style={{ position: "absolute", top: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between" }}>
            <Crumb><span style={{ color: PT.red }}>track {String(trackIx + 1).padStart(2, "0")} / {String(state.tracks.length).padStart(2, "0")}</span></Crumb>
            <Crumb><span style={{ color: PT.cream }}>{t.bpm} BPM · {t.key} · CAMELOT</span></Crumb>
          </div>
          <div style={{ textAlign: "center", position: "relative" }}>
            <Crumb>now playing</Crumb>
            <h1 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 200, fontWeight: 400, color: PT.cream, letterSpacing: "-0.05em", margin: "8px 0 0", lineHeight: 0.85 }}>{t.title}</h1>
            <div style={{ fontFamily: PT.display, fontSize: 36, color: PT.red, marginTop: 18, letterSpacing: "-0.02em" }}>{t.artist}</div>
            <div style={{ width: 260, height: 1, background: PT.cream, opacity: 0.4, margin: "32px auto" }}/>
            <div style={{ fontFamily: PT.mono, fontSize: 12, color: PT.mute, letterSpacing: "0.22em", textTransform: "uppercase" }}>apollo · live · garden chill, 2026</div>
          </div>
          <div style={{ position: "absolute", bottom: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between" }}>
            <Crumb>up next · {next.artist} · {next.title}</Crumb>
            <Crumb>crossfade in 0:29</Crumb>
          </div>
        </div>
      )}

      {mode === "cabin" && (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.2fr 1fr" }}>
          <section style={{ padding: "32px 40px", display: "flex", flexDirection: "column", gap: 22, borderRight: `1px solid ${PT.line}` }}>
            <div>
              <Crumb>now</Crumb>
              <h2 style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 56, fontWeight: 400, letterSpacing: "-0.025em", margin: "4px 0 0", lineHeight: 0.95 }}>{t.artist}<br /><span style={{ color: PT.red }}>{t.title}</span></h2>
              <Crumb>{t.bpm} BPM · {t.key} · crossfade 0:29</Crumb>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 70 }}>
              {Array.from({ length: 80 }).map((_, k) => {
                const h = 6 + Math.abs(Math.sin(k * 0.4) * 36) + Math.random() * 8;
                return <span key={k} style={{ flex: 1, height: h, background: k < 50 ? PT.red : PT.line2 }}/>;
              })}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {["skip", "stay", "more energy", "wind down"].map(b => (
                <button key={b} onClick={() => { setIntent(b); if (b === "skip") setTrackIx((trackIx + 1) % state.tracks.length); }} style={{ background: intent === b ? PT.red : "transparent", color: intent === b ? PT.cream : PT.text, border: intent === b ? "none" : `1px solid ${PT.line2}`, padding: "10px 16px", fontSize: 13, fontFamily: PT.sans, cursor: "pointer", textTransform: "capitalize" }}>{b}</button>
              ))}
            </div>
            <div style={{ borderTop: `1px solid ${PT.line}`, paddingTop: 18 }}>
              <Crumb>up next</Crumb>
              <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 26, marginTop: 4 }}>{next.artist} · {next.title} <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.faint, fontStyle: "normal" }}>{next.bpm} BPM · {next.key}</span></div>
            </div>
            <div style={{ marginTop: "auto" }}>
              <Crumb>talk to apollo</Crumb>
              <form onSubmit={send} style={{ display: "flex", gap: 8, alignItems: "center", border: `1px solid ${PT.line2}`, padding: "10px 14px", marginTop: 8 }}>
                <Mic />
                <input value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder='"more groove" · "darker" · "drop the energy"' style={{ flex: 1, background: "transparent", border: "none", color: PT.text, fontFamily: PT.sans, fontSize: 13, outline: "none" }}/>
                <Btn style={{ padding: "6px 16px", fontSize: 11 }}>Send</Btn>
              </form>
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6, maxHeight: 110, overflow: "auto" }}>
                {chat.slice(-4).map((m, i) => (
                  <div key={i} style={{ fontFamily: m.who === "apollo" ? PT.display : PT.sans, fontStyle: m.who === "apollo" ? "italic" : "normal", fontSize: m.who === "apollo" ? 16 : 14, color: m.who === "apollo" ? PT.mute : PT.text }}>
                    <span style={{ color: PT.red, marginRight: 6 }}>{m.who === "apollo" ? "‹" : "›"}</span>{m.text}
                  </div>
                ))}
              </div>
            </div>
          </section>
          <section style={{ background: "#000", position: "relative", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 18px", borderBottom: `1px solid ${PT.line}` }}>
              <div style={{ display: "flex", gap: 6 }}>
                {["Particles", "Strobe", "Fractal", "Vinyl"].map((v, i) => (
                  <button key={v} style={{ background: i === 0 ? PT.red : "transparent", color: i === 0 ? PT.cream : PT.mute, border: i === 0 ? "none" : `1px solid ${PT.line2}`, padding: "5px 12px", fontSize: 10, fontFamily: PT.mono, textTransform: "uppercase", letterSpacing: "0.18em", cursor: "pointer" }}>{v}</button>
                ))}
              </div>
              <Crumb>fullscreen ↗</Crumb>
            </div>
            <div style={{ flex: 1, position: "relative" }}>
              <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 50%, rgba(232,85,58,0.22), transparent 70%)` }}/>
              <Particles />
              <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
                <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 96, color: PT.cream, opacity: 0.92, letterSpacing: "-0.04em" }}>{t.title}</div>
              </div>
            </div>
          </section>
        </div>
      )}

      {mode === "immersive" && (
        <div style={{ flex: 1, position: "relative", background: "#000", overflow: "hidden" }}>
          <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 60%, rgba(232,85,58,0.30), transparent 70%)` }}/>
          <Particles count={120}/>
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
            <div style={{ fontFamily: PT.display, fontStyle: "italic", fontSize: 280, color: PT.red, letterSpacing: "-0.05em", lineHeight: 0.9, textAlign: "center", textShadow: "0 0 60px rgba(232,85,58,0.5)" }}>{t.title}</div>
          </div>
          <div style={{ position: "absolute", top: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between" }}>
            <span style={{ fontFamily: PT.mono, fontSize: 11, color: PT.red, textTransform: "uppercase", letterSpacing: "0.22em" }}>● live</span>
            <Btn kind="ghost" style={{ background: "rgba(0,0,0,0.4)", backdropFilter: "blur(8px)", padding: "8px 16px", fontSize: 12 }} onClick={() => setMode("cabin")}>Show controls</Btn>
          </div>
          <div style={{ position: "absolute", bottom: 28, left: 36, right: 36, display: "flex", justifyContent: "space-between", color: PT.cream, fontFamily: PT.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em" }}>
            <span>{t.artist} · {t.bpm} BPM · {t.key}</span>
            <span>{String(trackIx + 1).padStart(2, "0")} / {String(state.tracks.length).padStart(2, "0")}</span>
          </div>
        </div>
      )}
    </div>
  );
};

// ─────────────────────────────────────────── Particles canvas (decoration) ───
const Particles = ({ count = 60 }) => {
  const dots = useMemo(() => Array.from({ length: count }).map(() => ({
    x: Math.random() * 100, y: Math.random() * 100, r: Math.random() * 2.5, o: Math.random() * 0.7
  })), [count]);
  return (
    <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
      {dots.map((d, k) => <circle key={k} cx={d.x} cy={d.y} r={d.r * 0.4} fill={PT.cream} opacity={d.o}/>)}
    </svg>
  );
};

window.PROTO_SCREENS = { Dashboard, Brief, Curate, Editor, Export, Live };
