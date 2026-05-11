# Apollo — handoff for Claude Code

This package is the design source-of-truth for the Apollo redesign. Build the production app from these files.

## What's here

| File | Purpose |
|---|---|
| `Apollo prototype.html` | **Primary handoff.** Interactive prototype of the full flow — Dashboard → Brief → Curate → Editor → Render → Live. Wire real services behind this UI. |
| `prototype-shell.jsx` | Design tokens (PT.*), `<ApolloMark>` logo, `<Shell>` (top nav), `<Router>` context, route list, sample data, `stripe()` placeholder helper. |
| `prototype-screens.jsx` | All six screens as React components. Self-contained — read each one to learn the layout and state shape. |
| `Apollo logo.html` | Six logo directions. Recommendation: **01 wordmark with ember dot** for in-app, **03 sun & strings** for video covers. |
| `Apollo redesign.html` | Original three-direction exploration (Editorial · Console · Cinematic) + accent options. **Reference only — not in scope to ship.** |

## The system

**Three user-facing stages**, not six. The legacy phases (`genre · plan · ckpt1 · critique · ckpt2 · editing · validating · rating · complete`) collapse into:

1. **Brief** — one sentence in, parsed into structured fields the user can confirm.
2. **Curate** — the playlist with the critic's notes integrated as actionable cards (Apply / Edit / Ignore). No standalone "Critique" page.
3. **Play** — Render to YouTube (async) **or** Live DJ (real-time, three modes: Audience / Booth / Immersive).

A separate **Editor** route is reachable from Curate for power users.

## Visual language

- **Type**: Instrument Serif (display, italic, headings) · DM Sans (body) · JetBrains Mono (data, labels, code)
- **Colors** (see `prototype-shell.jsx`):
  - `ink #0a0807` background
  - `surf #13100e` / `surf2 #1c1814` raised surfaces
  - `text #fbf3e6` foreground · `mute` 62% · `faint` 36%
  - `red #e8553a` / `red2 #b53d24` accent (Ember)
  - `cream #f0e3c8` highlight + dark-on-light
  - `warn #f0b15a`, `green #9bbf7a` semantic
- **Headings** are always Instrument Serif italic with negative letter-spacing (`-0.02em` to `-0.035em`).
- **Labels & data** are JetBrains Mono uppercase with `0.18em` letter-spacing.
- **Buttons**: solid `red` for primary, `cream` for affirm-positive, `ghost` (1px line) for secondary.
- Stripe SVG placeholders stand in for real cover art / video stills — the app should render real imagery when available; keep the stripe as the empty state.

## Critical UX moves the prototype enforces

- **Single brief box** with live structured-field parsing on the right. Users never fill a multi-step form.
- **Critic notes are tracks-aware**: each card targets a position range and offers a one-click **Apply** that mutates the playlist (see `applyNote` in the reducer — it inserts a peak track at position 3 for the "energy plateau" note).
- **Live mode toggles between three layouts in-place** without leaving the route — Audience (poster), Booth (controls + visuals), Immersive (full-bleed).
- **No visible agent log**. The terminal output is gone. State the agent is busy with `"Curating…"` button labels and stage indicators in Render.

## Backend contracts (shape the API to match these)

```ts
// Brief → Plan
POST /api/sessions  { brief: string }
  → { id, parsed: { genre, duration, mood, venue, energy, tempo }, status: "planning" }

// Curate
GET  /api/sessions/:id  → { tracks: Track[], notes: CriticNote[], handled: string[], arc: { flat, max, peak } }
POST /api/sessions/:id/notes/:noteId/apply  → { tracks, handled }
POST /api/sessions/:id/notes/:noteId/ignore → { handled }
POST /api/sessions/:id/tracks/reorder       { order: number[] }
DELETE /api/sessions/:id/tracks/:n

// Render
POST /api/sessions/:id/render               → SSE stream { stage, pct, etaSeconds }
                                              stages: stems · crossfades · master · cover · encode

// Live
POST /api/sessions/:id/live/start
POST /api/sessions/:id/live/intent          { intent: "skip" | "stay" | "more-energy" | "wind-down" }
POST /api/sessions/:id/live/talk            { text }      → reply, optional new intent
WS   /api/sessions/:id/live/stream          → { trackIx, crossfadeIn, waveform, bpm, key, chat[] }

// Catalog (existing)
GET  /api/catalog?genre=                    → Track[]
```

`Track` shape (already in the prototype): `{ n, artist, title, remix, label, bpm, key, energy }` where `key` is Camelot (e.g. `6A`) and `energy` is 0–10.

## Out of scope for v1, but design-ready

- Mobile companion (controller for Live)
- Empty-states (no sessions, no critic notes)
- First-run onboarding
- Shared / public sessions
- Library filters & search

## Logo

Use the **Wordmark** (option 01 in `Apollo logo.html`) as the primary mark — it's already wired in `<ApolloMark>` in `prototype-shell.jsx`. For YouTube cover art, lift the **Sun & strings** SVG from option 03 directly.

## Open the prototype

Just open `Apollo prototype.html` in any modern browser — no build step. Routes are in the URL hash (`#brief`, `#live`, …).
