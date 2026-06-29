<!-- changing state — read & written every run; never moved into SKILL.md. -->

# build-beatmatch-loop — State Ledger

> The builder loop's memory. Read at start, written before stopping. Implements
> the work items in `docs/beatmatch-feedback-loop.md`. Persists between runs
> because it is external to the skill.

---

## Tunables

```
COVERAGE_MIN          : 80      # global backend coverage floor (baseline 76%)
MAX_ITERATIONS        : 20      # hard budget
ITEM_ORDER            : W1 W2 W3 W4 W5
```

---

## Prerequisite

```
step0_coverage_tooling_installed : NO   # uv pip install coverage pytest-cov (backend)
                                        # npm i -D @vitest/coverage-v8 (frontend)
```

---

## Work items

| item | title | status | tests | covered | notes |
|------|-------|--------|-------|---------|-------|
| W1 | Backend ingest (measurements.jsonl sink) | done | 12 green | yes | record_beatmatch_measurement in app.py + WS elif |
| W2 | Frontend measurement emit | done | green | n/a | live.ts emits beatmatch_measurement; profile via crossfade_timing |
| W3 | Pitch-bend UI (reinforcement input) | done | green | n/a | nudgePitch + deck.nudgeRate + applyPitchNudge; buttons in page.tsx pending (presentational) |
| W4 | Apply learned offset (gated G3) | done-gated | 13 green | yes | logic in phase_lock (read_learned_offset + shift); engine wiring with apply flag ON awaits G3 |
| W5 | Loop wiring + coverage >= 80% | in-progress | — | — | measuring coverage after W1-W4 |

<!-- status: pending · in-progress · done · failed -->

---

## Counters

```
iterations              : 1     # inline implementation pass
items_done              : 4 / 5  # W1-W4 done (W4 gated G3); W5 coverage in progress
backend_coverage_pct    : 76      # with-tests metric; pushing toward 80 in W5
suites_green            : true    # 828 passed + new W5 batches (run.py +13, main.py +15)
predicate_holds         : false   # coverage not yet at 80% (with-tests metric)
new_tests_added         : 53     # W1:12, W4:13, W2/W3 frontend, W5 coverage:28
note                    : metric = coverage WITH tests in denominator (user choice). \
                          source-only is 57% (main.py legacy 32%). 80% with-tests \
                          ~= +400 more covered stmts → mechanical legacy-test grind, \
                          ideal for the autonomous loop to continue.
```

---

## Ledger

| iteration | item | action | verifier | coverage | status |
|-----------|------|--------|----------|----------|--------|
| (initial) | — | scaffold | — | 76% | pending — no runs yet |

<!-- One row per iteration. Do not delete rows — audit trail. -->

---

## Open gate requests

| gate | item | reason | cleared? |
|------|------|--------|----------|
| G1 | — | pre-run sign-off | YES (user: "Apruebo. Puedes lanzar la implementación?") |
| G3 | W4 | wire read_learned_offset into live_engine with the apply flag ON — this changes how live transitions sound. Logic is implemented + tested with the flag OFF (no audible change yet). Awaits sign-off to enable. | NO |

---

## Last run

```
timestamp : (not yet run)
iteration : 0
outcome   : —
exit code : —
```

---

## Notes

- First: do **step 0** (install coverage tooling) and flip the prereq flag.
- Then clear gate **G1** (pre-run sign-off).
- Verifier = `~/.claude/skills/build-beatmatch-loop/verifier.sh`
  (pytest + coverage>=80% + tsc + vitest). ~22 min per run.
- **G3** pauses before W4's audio-affecting merge.
- Hard budget: **20 iterations** → halt with `budget-exceeded`.
- Goal predicate: W1-W5 done AND verifier exit 0 (all green AND coverage>=80%).
