# Beatmatch Feedback-Learning Loop — Implementation Plan

> Status: **planning → ready to build**. Closes the loop scaffolded via
> loop-maker (`~/.claude/skills/beatmatch-learn/`, state in
> `loops/beatmatch-learn/STATE.md`). Scope decided this session:
> **full bucle — measure + correct + apply.**
>
> Lineage: follows the v3.6/v3.7 beatmatch fixes. Those removed *systematic*
> error (contrabombo, out-of-phrase). This loop learns the *residual per-profile*
> timing offset from real measurements + human pitch-bend corrections, the same
> "verify-by-playback + adjust on local artifacts" pattern from the codex report.

---

## 1. One-paragraph thesis

During a live session, every transition produces a **measured residual offset**
(how far the incoming downbeat actually landed from the outgoing downbeat) and,
optionally, a **human pitch-bend correction** (the DJ nudges the incoming track
to fix it by ear). Both are streamed browser→backend over the existing WS,
appended to `measurements.jsonl`. The `beatmatch-learn` loop consumes each line,
updates a per-profile offset via EMA, and `build_live_transition_plan` pre-applies
the learned offset on the next transition of that profile — so the system gets
tighter the more you use it, and your manual corrections are the reinforcement
signal. Profile = `(camelot_key_pair, bpm_bucket)`.

---

## 2. Data flow (verified against current code)

```
BROWSER (lib/live.ts crossfadeToNext)
  • computes residual offset (computeCrossfadeWhen → secondsUntilDownbeat, clamp)
  • pitch-bend buttons record pitch_bend_ms (NEW UI)
        │  ws.send({type:"beatmatch_measurement", profile, key_pair,
        │           bpm_bucket, offset_ms, pitch_bend_ms})   ← reuses existing WS
        ▼
BACKEND (app.py live read-loop, ~line 1180, alongside playback_pos/track_ended)
  • elif msg_type == "beatmatch_measurement": append one JSON line
        │  to loops/beatmatch-learn/measurements.jsonl
        ▼
LOOP (beatmatch-learn SKILL.md — run-until-done)
  • reads new JSONL lines from cursor → EMA update → verifier (sanity) →
        │  writes learned offset to agent/memory.json[beatmatch_offsets] (gate G3)
        ▼
BACKEND (phase_lock.build_live_transition_plan)
  • reads learned offset for the upcoming profile, pre-applies it to the
        anchor/when (gate G4) → next transition of that profile starts corrected
```

Key facts that make this cheap (already exist):
- The live WS read-loop (`app.py:1166`) already dispatches typed messages
  (`playback_pos`, `track_ended`, `user_msg`). Adding one `elif` branch is the
  whole backend ingest.
- The frontend already does `ws.send(JSON.stringify({type:...}))` in several
  places (`live.ts:824, 1837, ...`). One more message type.
- `computeCrossfadeWhen` already returns `{when, secondsUntilDownbeat, clamped}`
  (the v3.6 offset instrumentation) — the residual is already computed; today it
  only goes to `console.log [xfade-timing]`.
- `agent/memory.json` already exists and is indexed by key_pair/bpm_bucket.

---

## 3. Work breakdown (full scope: measure + correct + apply)

### W1 — Backend ingest (sensor sink)  ~0.5 day
- W1.1 Add `elif msg_type == "beatmatch_measurement"` to the live read-loop in
  `web/backend/app.py` (~line 1180). Validate fields, append one JSON line to
  `loops/beatmatch-learn/measurements.jsonl` (create dir/file if absent).
- W1.2 Path + atomic append helper (open "a", one `json.dumps` + "\n", flush).
- W1.3 **Tests** (mandatory): malformed message rejected; well-formed appends
  exactly one line; concurrent appends don't interleave; missing file created.

### W2 — Frontend measurement emit  ~0.5 day
- W2.1 In `live.ts crossfadeToNext`, after `computeCrossfadeWhen`, build the
  `beatmatch_measurement` payload (profile from the phase_lock payload's
  key_pair + bpm_bucket; `offset_ms` from the residual; `pitch_bend_ms` 0 by
  default) and `ws.send` it. Replaces/augments the `[xfade-timing]` console.log.
- W2.2 **Tests**: the WS send fires once per crossfade with the right shape
  (extend `__tests__/live.test.ts`).

### W3 — Pitch-bend UI (the reinforcement input)  ~1 day
- W3.1 Two buttons (nudge earlier / later) on the live deck UI; each press
  applies a small playbackRate bump to the active incoming deck for a moment
  (audible correction) AND accumulates `pitch_bend_ms` for the current transition.
- W3.2 On the next `beatmatch_measurement` emit, include the accumulated
  `pitch_bend_ms` (sign per the knowledge rubric: forward nudge = positive).
- W3.3 **Tests**: button press accumulates the right ms; sign convention;
  resets per transition.

### W4 — Apply learned offset (the actuator)  ~1 day
- W4.1 `build_live_transition_plan` reads `agent/memory.json[beatmatch_offsets]`
  for the upcoming profile and, if present AND gate G4 is open, shifts the
  outgoing anchor / `when` by the learned offset (same sign frame as the
  knowledge rubric).
- W4.2 Plumb a feature flag / G4 switch so "learning" and "applying" are
  independent (apply OFF by default until you approve).
- W4.3 **Tests**: offset applied when present+flag-on; no-op when absent or
  flag-off; clamped to sane bounds; parity test still holds.

### W5 — Loop wiring + first run  ~0.5 day
- W5.1 Confirm the loop reads the real `measurements.jsonl` and writes
  `beatmatch_offsets` (the loop logic already exists; this is end-to-end wiring).
- W5.2 Clear gate G1 (pre-run sign-off). Run a session, watch STATE.md fill.
- W5.3 Verify the verifier gates anomalies on real data.

**Total: ~3.5 days** of build, then the live A/B run.

---

## 4. Expected results (what success looks like)

- **R1 — Data captured.** After one live session, `measurements.jsonl` has one
  well-formed line per transition with a plausible `offset_ms` (single-digit to
  low-tens of ms, matching the "few ms" you heard).
- **R2 — Corrections recorded.** When you pitch-bend, the next line carries a
  non-zero `pitch_bend_ms` with the correct sign.
- **R3 — Offsets converge.** Over repeated transitions of the same profile, the
  learned `offset_ms` in `memory.json` stabilizes (EMA settles), and
  `mean_abs_offset_lastN` in STATE.md trends down.
- **R4 — Audible improvement (with G4 on).** A profile you corrected early in a
  set enters tighter later in the set / next session without manual correction.
- **R5 — Convergence + stop.** `pitch_bends_lastK → 0` and
  `mean_abs_offset_lastN < threshold` → loop writes `status: done`. Or it hits
  the 100-transition budget and halts cleanly.

---

## 5. Definition of Done

`OFFSET_THRESHOLD_MS = 5` (strict beat-lock). Update the loop default in
`loops/beatmatch-learn/STATE.md` (`OFFSET_THRESHOLD_MS`) and the knowledge
rubric to match.

### Build DoD (gates the live run)
- [ ] **D1** W1–W5 implemented; tests green — backend pytest + frontend vitest
      + `tsc --noEmit` clean.
- [ ] **D2** Backend appends exactly one valid JSONL line per
      `beatmatch_measurement` WS message (W1 tests prove it).
- [ ] **D3** Frontend emits one `beatmatch_measurement` per crossfade with the
      correct shape (W2 tests); pitch-bend buttons accumulate `pitch_bend_ms`
      with the rubric sign (W3 tests).
- [ ] **D4** Verifier gates anomalies on real data (exit 1 on out-of-range /
      malformed; exit 0 otherwise).

### Sensor-accuracy DoD (validates A1 — do this on the FIRST session)
- [ ] **D5** Cross-check: for ≥3 transitions, the logged `offset_ms` agrees in
      direction and rough magnitude with what you hear. If the code's residual
      and your ear disagree, STOP — fix the measurement before trusting the
      loop. This also reveals the physical floor (madmom noise + output
      latency), i.e. whether <5 ms is even reachable on this setup.

### Learning DoD (the actual proof — EITHER outcome is success)
- [ ] **D6** Offsets persist to `memory.json[beatmatch_offsets]` (G3 cleared)
      and `STATE.md` counters update each transition.
- [ ] **D7** A profile **improves**, shown by ONE of:
      - (a) `mean_abs_offset_lastN` for that profile converges **< 5 ms**, OR
      - (b) the profile's offset error is **cut by ≥50%** from its first
        measurement before the 100-transition budget halts.
      > Rationale: if the physical floor (D5) sits above 5 ms, the loop can
      > still prove it *learns and improves* via (b). Don't hold the loop
      > hostage to a threshold the hardware can't reach.
- [ ] **D8** With **G4 on**, at least one previously-corrected profile enters
      with no manual pitch-bend needed (the reinforcement actually closed the
      loop), OR the loop halts cleanly at budget with `status: budget-exceeded`
      and a readable audit trail in `STATE.md`.

### Exit
- [ ] **D9** Exit predicate (`mean_abs_offset_lastN < 5 ms` AND
      `pitch_bends_lastK == 0`) is reached on a real run, OR the budget halt is
      clean and the trend in `STATE.md` is downward (improving but not yet at
      the strict bar).

---

## 6. Assumptions / risks (eyes open)

- **A1.** The browser-side residual (`secondsUntilDownbeat` / clamp) is an
  accurate proxy for what you actually hear. If the residual the code computes
  diverges from the audible offset, the loop learns the wrong thing. → Validate
  early: cross-check a few `offset_ms` values against your ear (the "few ms"
  feedback) before trusting the loop.
- **A2.** A profile recurs enough within practical use for EMA to converge
  (alpha=0.3 needs ~5-10 samples/profile). Sparse profiles stay near 0 — fine,
  they just don't learn. Cohesive genres (deep house, tight key/bpm clusters)
  will have recurring profiles.
- **A3.** Pitch-bend sign matches the residual sign (knowledge rubric). If
  applying makes it WORSE, the sign is inverted — flip in BOTH the rubric and
  `build_live_transition_plan` together (never one side only).
- **R-risk.** Applying learned offsets live (W4) changes audio. Gated behind G4
  precisely so learning is safe to run before applying is trusted.

---

## 7. References
- Loop scaffold: `~/.claude/skills/beatmatch-learn/` (SKILL, verifier, gates,
  trigger) + `~/.claude/skills/beatmatch-learn-knowledge/` (rubric) + repo state
  `loops/beatmatch-learn/STATE.md`.
- v3.6/v3.7 fixes: `agent/phase_lock.py`, `web/frontend/lib/crossfade_timing.ts`;
  diagnosis in memory `project_v36_beatmatch_endbar_bug`.
- Existing WS plumbing: `web/backend/app.py` live read-loop (~1166),
  `web/frontend/lib/live.ts` (`crossfadeToNext`, `ws.send`).
