import type { Config } from "tailwindcss";

// Apollo v2.6.0 — Cinematic / Ember design system.
//
// Tokens copied verbatim from the Claude Design handoff at
// docs/design/apollo-claude-design/apollo/project/prototype-shell.jsx.
// Keep in sync: when the handoff updates, mirror the changes here.
//
// The legacy neon-cyberpunk palette below (`neon`, `surface`, `border`,
// `muted`, `font-pixel`) is preserved temporarily so unmigrated screens keep
// rendering during the v2.6.0 transition. Remove once the redesign covers
// every route — see plan Sección 3.6.

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── v2.6.0 Ember palette ───────────────────────────────────────
        ink: "#0a0807",
        surf: "#13100e",
        surf2: "#1c1814",
        line: "rgba(255,238,220,0.10)",
        line2: "rgba(255,238,220,0.20)",
        // `text` is a Tailwind reserved utility; expose the ember foreground
        // as `cream-text` (vs `cream` which is the brighter cream tone used
        // for affirm-positive surfaces).
        "ember-text": "#fbf3e6",
        mute: "rgba(251,243,230,0.62)",
        faint: "rgba(251,243,230,0.36)",
        ember: "#e8553a",
        "ember-dark": "#b53d24",
        cream: "#f0e3c8",
        warn: "#f0b15a",
        ok: "#9bbf7a",

        // ── Legacy v2.5.x neon palette (transitional) ──────────────────
        neon: "#00FF88",
        "neon-dim": "#00cc6a",
        purple: "#6A5AFF",
        danger: "#FF1744",
        surface: "#111118",
        border: "#1e1e2e",
        muted: "#4a4a6a",
      },
      fontFamily: {
        // ── v2.6.0 ──
        // ``font-display`` for serif italic headings.
        // ``font-sans`` overrides Tailwind's default sans to DM Sans.
        // ``font-mono`` overrides Tailwind's default mono to JetBrains Mono.
        // Wired up to next/font CSS variables in app/layout.tsx.
        display: ["var(--font-instrument-serif)", "Georgia", "serif"],
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
        // ── Legacy v2.5.x ──
        pixel: ["'Press Start 2P'", "monospace"],
      },
      letterSpacing: {
        // Ember design system uses tight tracking on display + wide on mono.
        "display-tight": "-0.035em",
        "display-snug": "-0.02em",
        mono: "0.18em",
      },
      animation: {
        blink: "blink 1s step-end infinite",
        "fade-in": "fadeIn 0.3s ease-in",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0" } },
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: { from: { transform: "translateY(8px)", opacity: "0" }, to: { transform: "translateY(0)", opacity: "1" } },
      },
    },
  },
  plugins: [],
};
export default config;
