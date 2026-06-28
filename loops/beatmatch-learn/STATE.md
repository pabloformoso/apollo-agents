<!-- changing state — read & written every run; never moved into SKILL.md. -->

# beatmatch-learn — State Ledger

> This file is the loop's memory (cursor + counters). Every run reads it at
> start and writes it before stopping. Learned offsets live separately in
> `agent/memory.json` → `beatmatch_offsets`. This file persists between runs
> precisely because it is external to the skill.

---

## Tunables (override defaults here)

```
N (offset window)        : 10
K (pitch-bend window)    : 10
OFFSET_THRESHOLD_MS      : 10
alpha (EMA)              : 0.3
MAX_TRANSITIONS (budget) : 100
large_jump_gate_ms (G7)  : 30
```

---

## Cursor

```
measurements_file : loops/beatmatch-learn/measurements.jsonl
lines_processed   : 0          # advance only after the verifier passes
```

---

## Convergence counters

```
transitions_processed   : 0
mean_abs_offset_lastN   : —    # over last N measurements
pitch_bends_lastK       : —    # count over last K measurements
predicate_holds         : false
```

---

## Ledger

| iteration | profile | offset_ms (in) | learned_offset (out) | verifier | gate | status |
|-----------|---------|----------------|----------------------|----------|------|--------|
| (initial) | — | — | — | — | — | pending — no runs yet |

<!--
One row per processed transition. Do not delete rows — they are the audit
trail. Valid status: pending · in-progress · done · failed · skipped ·
gate-open · budget-exceeded
-->

---

## Open gate requests

<!-- The loop appends a row here when it needs a human (G1/G2/G3/G4/G7). -->

| gate | profile | reason | proposed value | cleared? |
|------|---------|--------|----------------|----------|
| G1 | — | pre-run sign-off required before first live run | — | NO |

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

- First action required: clear gate **G1** (pre-run sign-off) in
  `~/.claude/skills/beatmatch-learn/HUMAN-GATES.md` before any real iteration.
- If the verifier exits 1, the loop halts and **G2** must be cleared before the
  next run.
- Goal predicate: **mean(|offset_ms|) over last N < OFFSET_THRESHOLD_MS AND
  pitch_bends over last K == 0**.
- Hard budget: **100 transitions** — halt with `budget-exceeded` even if not
  converged.
