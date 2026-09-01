# Plan — bringing the algorave into Apollo

Working plan for §11 of `docs/algorave-livecoding-plan.md`. That section is
the spec (what and why); this file is the execution contract (tasks,
requirements, acceptance criteria, definition of done) that subagent briefs
are written from.

**Status: EXECUTED, 2026-09-01.** All nine slices landed. Kept as the record of
the contract the work was actually held to — the acceptance criteria below are
what each PR was checked against, and two of them (S7's "the buffer parses",
S3's "one Pattern class") turned out to be criteria a broken implementation
could satisfy. That lesson is worth more than the plan.

Read §11 first. In particular §11.1 (the fusion is coming, just not yet) and
§11.3 (the seams to leave open) — a slice that ships working code but closes
a seam has failed, even if its own acceptance criteria pass.

---

## 1. Ground rules

These apply to **every** slice. They are not repeated per slice.

### 1.1 Conventions

- One slice = one branch off `origin/main` = one PR = one squash-merge.
- Branch: `feat/algorave-<slug>`, `fix/<slug>` or `chore/<slug>`.
- PR title: conventional commit with the section marker, in the house style —
  `feat(algorave): the turn-taking strip — pen, phrase, B2B (§11)`.
- Work happens in a worktree. Worktrees have no `tracks/`, `.env` or venv;
  anything runtime-ish runs from the main checkout (or, for the algorave
  lane, from jarvis).
- The main checkout stays a pure mirror of `origin/main` — no local commits.

### 1.2 Definition of Done (shared)

A slice is done when **all** of these hold:

1. **All four CI checks green** — Backend (Python 3.12), Backend (Python
   3.13), Frontend (Node 20), E2E (Playwright). Read the FULL failure list;
   `tests/web/test_youtube_chat.py` fails local-only and passes in CI.
2. **New behaviour is covered by tests** at the level it lives at: vitest for
   frontend units, Playwright for a user-visible flow, pytest for backend,
   spike vitest for pattern/validator logic.
3. **No new lint errors.** Baseline on `main` is 17 errors + 6 warnings across
   11 files. A slice may not raise either number in the files it touches.
4. **`npx next build` succeeds.** From S1 onward CI enforces this.
5. **The nearest `CLAUDE.md` is updated** when the slice makes a decision or
   discovers a gotcha — `web/CLAUDE.md`, `scripts/CLAUDE.md`, `tests/CLAUDE.md`.
6. **The PR body states what was verified and what was NOT.** "Not verified in
   a real browser" is an acceptable and expected line; a silent omission is not.
7. Squash-merged to `main`, branch deleted, board updated (§2).

### 1.3 What a subagent brief must always carry

- The seam obligations from §11.3 that touch its slice, quoted.
- The bank rule: drum sounds REQUIRE a bank; sampled instruments must NOT
  have one (a `.bank()` on them is silence).
- "Do not close a seam to make your slice simpler. Raise it instead."

---

## 2. Coordination

**GitHub Issues are the source of truth. The HTML board is a generated view.**

- One issue per slice, labelled `algorave-apollo`, titled `S<n> — <name>`,
  body = that slice's section from this file.
- A GitHub Project (board) groups them: `Todo · In progress · In review · Done`.
- PRs close their issue with `Closes #<n>`.
- `docs/algorave-board.html` is a self-contained snapshot of the board,
  committed to `main` and regenerated from `gh` data. It is a view for
  glancing at, never the record — if the HTML and the issues disagree, the
  issues win.

Rationale: issues survive sessions, link to PRs and CI, and both Pablo and
any agent can write to them. A hand-maintained HTML file would go stale the
first time a slice moves while nobody is regenerating it.

---

## 3. The slices

Ordering: **S1 → S3 is the only hard chain** (build must work before a route
is added; the bundle question must be answered before UI is built on it).
S2 is independent and can go any time. S4–S9 resequence freely.

§11.4 listed eight; this plan splits its S1 into S1 + S2, because the CI gap
and the build break are separate problems with separate fixes.

---

### S1 — Unbreak `next build`, and guard it in CI

**Why now.** `/algorave` will use `useAuthQueryBootstrap` for its read-only
view, so it inherits the break the moment it exists. And CI does not build,
which is why nobody noticed.

**Requirements**

- R1. `npx next build` completes successfully on `main`.
- R2. The five affected pages still behave identically at runtime:
  `/curate`, `/render`, `/editor`, `/live`, `/session/[id]/live/visual-only`.
- R3. CI fails if the production build breaks again.
- R4. The fix does not change any page's URL, query handling or auth flow.

**Tasks**

- Wrap the `useSearchParams()` consumers in Suspense boundaries. Prefer
  fixing it once inside `lib/auto-session.ts` and `lib/auth-bootstrap.ts` if
  that is possible without changing their call signatures; otherwise wrap at
  each of the five pages.
- Add a `Build` step (`npm run build`) to the Frontend job in
  `.github/workflows/ci.yml`.
- Update `web/CLAUDE.md`: the "2 pre-existing eslint errors" note is stale —
  record the real baseline (17 errors + 6 warnings, 11 files) and that CI now
  builds.

**Acceptance criteria**

- AC1. `cd web/frontend && npx next build` exits 0 from a clean `npm ci`.
- AC2. `npm test` still passes with no spec edits (437 tests on main at the time).
- AC3. Reverting the Suspense change makes the new CI step fail — i.e. the
  guard actually guards. Demonstrate this in the PR body.
- AC4. Playwright E2E passes; `?viewer=1` on `/live` still strips operator
  chrome and `?token=` bootstrap still works.

**Out of scope.** Fixing the 17 lint errors. Any visual change.

---

### S2 — The algorave spike's tests run in CI

**Why now.** The spike carries the validator, the pen, B2B and the palette
rules — the exact code S5–S7 move into the app — and **none of it runs in
CI**. #147 had to rescue 28 validator tests that a fresh install silently
stopped running. Moving untested-in-CI code into the app propagates that.

**Requirements**

- R1. `scripts/algorave-spike`'s vitest suite runs on every PR.
- R2. A failing spike test fails the build.
- R3. The suite runs from a clean checkout with no manual steps.
- R4. Node 22 (the spike needs `registerHooks`; Node 18 does not work).

**Tasks**

- Add a job (or a step in an existing one) installing `scripts/algorave-spike`
  and running `npx vitest run`.
- Verify all six spec files execute and report a non-zero test count:
  `validate`, `pen`, `b2b`, `serve`, `pattern`, `wav`.
- Record the count in `scripts/CLAUDE.md` so a silent drop to zero is visible.

**Acceptance criteria**

- AC1. CI output shows the spike suite with a test count > 0 for all six files.
- AC2. A deliberately broken assertion fails the PR. Demonstrate in the body.
- AC3. Total CI wall-clock grows by less than ~2 minutes.

**Out of scope.** Adding new tests. Refactoring existing ones.

---

### S3 — The Strudel bundle spike in Next

**Why now.** This is the decision the rest of the route rests on. §11.5 risk 1:
under a bundler, `@strudel/core` and `@strudel/web` can resolve to separate
copies, giving two `Pattern` classes, and the failure is **silent** — no
error, no audio.

**This slice has a stop condition.** If one `Pattern` class cannot be
guaranteed by a mechanism we are willing to maintain, **stop and reopen the
route decision** before any design work. Reporting "it cannot be done safely"
is a successful outcome for this slice.

**Requirements**

- R1. A Next route evaluates a Strudel pattern and produces audible audio.
- R2. Exactly one `Pattern` class exists at runtime, provably.
- R3. The mechanism survives a production build, not just `next dev`.
- R4. The chosen mechanism is written down with its trade-offs.

**Tasks**

- Try, in order of preference: (a) the prebuilt bundle as a static asset under
  `public/vendor/strudel/`, loaded outside bundler resolution; (b) a webpack
  `resolve.alias` mapping every `@strudel/*` specifier to the single file.
- Add a runtime assertion that fails loudly on duplicate classes, so a future
  regression is not silent.
- Throwaway UI: a hardcoded pattern and a play/stop button. No design work.

**Acceptance criteria**

- AC1. Audio is heard from a Next route in `next dev` **and** from
  `next build && next start`. State plainly that this was verified by a human
  in a real browser, or that it was not.
- AC2. The duplicate-class assertion passes, and deliberately importing a
  second copy makes it fail.
- AC3. A short written recommendation: mechanism, cost, what breaks it.

**Out of scope.** Ember styling. The mind. The pen. Anything from §11.2.

---

### S4 — `/algorave` skeleton and the `/dashboard` entry

**Depends on S1 and S3.**

**Requirements**

- R1. `/algorave` exists in the Next app, inside the Ember `Shell`.
- R2. A button on `/dashboard` navigates to it.
- R3. An editable buffer, hot-swapped into running audio on evaluate.
- R4. The canvas follows §11.2: three modes (Audience/Booth/Immersive)
  switched in place, synced to the URL hash — **using the same mode component
  `/live` uses** (§11.3 seam 3), extracted in this slice if it is not already
  shared.
- R5. Ember tokens only. No new colours; the spike's teal/pink does not travel.

**Tasks**

- Extract `/live`'s mode switcher into a shared Ember component; make `/live`
  consume the extracted version in the same PR so the duplication never exists.
- Build the route: shell, mode switcher, buffer, play/stop, evaluate.
- Add the dashboard entry point.
- Decide and record the session identity (§11.3 seam 5) — even if the answer
  is "a rave run gets an id from day one and here is its shape".

**Acceptance criteria**

- AC1. From `/dashboard`, one click reaches `/algorave`; the URL hash tracks
  the mode; a reload restores the mode.
- AC2. Editing the buffer and evaluating changes what is heard, without a
  gap in the audio.
- AC3. `/live` renders identically to before the extraction — verified by the
  existing E2E suite passing unchanged.
- AC4. No hardcoded colour outside the Ember tokens in the new files.

**Out of scope.** The mind, the pen, the palette browser, the OBS view.

---

### S5 — Wire the mind

**Depends on S4.**

**Requirements**

- R1. The route requests a mutation from the mind and shows it as a diff with
  Apply / discard.
- R2. **All access to the mind goes through one client module** (§11.3 seam 1).
  No inline `fetch` anywhere else. This is the slice's real deliverable.
- R3. The mind's address is configurable, not hardcoded.
- R4. The ~20 s wait is a designed state, not a spinner (§11.5 risk 4).
- R5. The tie rule holds: auto-apply only if the buffer is byte-identical to
  what the mind saw; otherwise the human's edit stands and the proposal falls
  back to a manual diff.

**Tasks**

- Write the client module; route every call through it.
- Relaunch the mind with an `--allow-origin` covering the new frontend origin
  and record the new command line in `scripts/CLAUDE.md` (§11.5 risk 2).
- Implement the diff view and the tie check.

**Acceptance criteria**

- AC1. A mutation round-trips end to end against the real mind on jarvis.
- AC2. Grepping the frontend for a direct call to the mind's path returns
  exactly one file.
- AC3. Editing the buffer while the mind is thinking results in the human's
  text surviving and the proposal offered manually — covered by a unit test.
- AC4. A CORS rejection produces a legible error in the UI, not a silent no-op.

**Out of scope.** Phrase-boundary scheduling and B2B (that is S6).

---

### S6 — The turn-taking strip

**Depends on S5.** This is the most reusable thing in the rave (§11.3 seam 4)
— a crossfade *is* a phrase boundary, so this component is what the DJ lane
borrows later.

**Requirements**

- R1. Shows who holds the pen, bars to the next phrase boundary, bars to the
  next B2B flip, and what the mind is currently working on.
- R2. Built as a standalone component with no algorave-specific imports, so a
  deck-driven caller can mount it unchanged.
- R3. The pen logic is imported from the portable module, not reimplemented
  (§11.3 seam 2) — `togglePen`, `decide`, the `WHY` enum, the tie rule.
- R4. The `WHY` reason for firing or not firing is visible, not just logged.

**Tasks**

- Move/port `pen.js` to a location both the spike and the app can import,
  keeping its existing tests running (S2 makes this safe).
- Build the strip; wire it to the scheduler.
- Settle the latency question (§11.5 risk 4): 16-bar phrases, boundary+1, or
  a faster model. Record the decision and why.

**Acceptance criteria**

- AC1. The pen module has exactly one copy in the repo. Demonstrate by grep.
- AC2. The existing pen and b2b tests pass unmodified after the move.
- AC3. Counters stay correct across a mode switch and a page-visibility change.
- AC4. The strip renders with a deck-shaped prop set in a unit test — proving
  R2 without the DJ lane existing yet.

**Out of scope.** Wiring it into `/live`. That is the fusion, and it is later.

---

### S7 — The palette browser

**Depends on S4.**

**Requirements**

- R1. Browse the three categories from `palette.json`: drums, synths,
  instruments.
- R2. The bank rule is visible in the UI, not just enforced: drum sounds
  require a bank; sampled instruments must not have one.
- R3. Audition a sound on click.
- R4. Insert into the buffer without producing invalid Strudel.
- R5. Reads the live `palette.json` — no second copy of the sound list.

**Acceptance criteria**

- AC1. Every entry in `palette.json` is reachable in the UI; the count matches
  the file (15 percussion / 6 machines, 6 synths, 9 instruments at time of
  writing).
- AC2. Inserting any sound yields a buffer that parses — covered by a test
  that inserts every catalogued sound and parses the result.
- AC3. A sampled instrument can never be inserted with `.bank()`.
- AC4. Adding a sound to `palette.json` surfaces it with no frontend change.

**Out of scope.** Editing the palette from the UI.

---

### S8 — The read-only view for OBS

**Depends on S4.**

**Requirements**

- R1. A read-only URL strips all operator chrome: mode switcher, pen control,
  diff review, palette, counters-as-controls.
- R2. It uses the same viewer gate `/live` uses (§11.3 seam 3), not a copy.
- R3. Operator tab and OBS tab work simultaneously, as on `/live`.
- R4. No YouTube chat (§11.2 — later, not never).

**Acceptance criteria**

- AC1. The read-only URL renders no interactive operator control — asserted
  by a test enumerating them, not by eyeball.
- AC2. Two tabs open at once, both showing the same running pattern.
- AC3. Verified in a real OBS Browser Source, or explicitly recorded as not
  verified.

**Out of scope.** Streaming infrastructure, scenes, overlays.

---

### S9 — The fate of the `:4031` playground

**Depends on S4–S8 being usable.**

**Requirements**

- R1. A decision, recorded in `scripts/CLAUDE.md`: keep it as the rehearsal
  room, or redirect it to `/algorave`.
- R2. If kept: what it is for, and what may drift between the two.
- R3. If retired: `serve.mjs`, the vendor bundle and `patterns/playground.html`
  are dealt with explicitly, not left rotting.

**Acceptance criteria**

- AC1. Neither surface silently rots. There is one sentence in the repo saying
  which is which, and it is true.

**Out of scope.** Deleting anything before the replacement is proven in use.

---

## 4. Parallel track (not this plan)

The algorave's own musical work continues independently: roles with voice and
register, gain lanes, section templates, seed-per-pack, the Camelot bridge
(`camelot_to_strudel`) — §6 and §10. Those slices do not block and are not
blocked by anything here.

Known open item, unrelated but live: `parallel=1` must be set as the e4b's
default in LM Studio's GUI on jarvis, or the model reverts to 4 slots
(2048 ctx) after the TTL and the mind starts returning 400s.
