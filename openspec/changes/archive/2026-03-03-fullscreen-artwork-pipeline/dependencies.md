## Dependency Matrix

| Task ID | Depends On | Type | Reason |
|---------|-----------|------|--------|
| 1.1 | — | — | No dependencies, new helper function |
| 1.2 | 1.1 | FS | Uses `_cover_crop` helper |
| 1.3 | 1.1 | FS | Uses `_cover_crop` helper |
| 2.1 | — | — | Simple constant change |
| 2.2 | — | — | Simple constant change |
| 2.3 | — | — | JSON file edit, independent |
| 3.1 | — | — | New helper function, no dependencies |
| 3.2 | 3.1, 2.1 | FS | Uses gradient helper; makes sense after brightness change |
| 3.3 | 3.1 | FS | Uses gradient helper in Short pipeline |
| 4.1 | 1.1 | FS | Ken Burns needs cover-crop awareness |
| 4.2 | 1.1, 1.3 | FS | Builds on cover-crop and artwork loading changes |
| 5.1 | 1.1 | FS | Short background uses `_cover_crop` |
| 5.2 | 5.1 | FS | Ken Burns for shorts depends on new cover-crop source |
| 5.3 | 2.1 | FS | Uses theme `bg_darken` instead of hardcoded constant |
| 6.1 | — | — | New JSON file, completely independent |
| 6.2 | 6.1 | SS | Part of same file creation |
| 6.3 | 6.1 | SS | Part of same file creation |
| 6.4 | 6.1 | SS | Part of same file creation |
| 7.1 | 6.1, 6.2, 6.3, 6.4 | FS | Validates session.json |
| 7.2 | 1.1, 1.2, 1.3, 2.1, 2.2 | FS | Validates artwork pipeline changes |
| 7.3 | 3.1, 3.2, 2.1 | FS | Validates gradient readability |

## Critical Path

```
1.1 → 1.3 → 4.2 → 7.2
```

This is the longest chain: cover-crop helper → artwork loading integration → Ken Burns integration → visual validation. All other paths are shorter or have more float.

## Parallel Execution Waves

### Wave 1 (no dependencies)
- 1.1 — `_cover_crop` helper function
- 2.1 — `ARTWORK_DARKEN_FACTOR` constant
- 2.2 — `ARTWORK_BLUR_RADIUS` constant
- 2.3 — Session 4 `bg_darken` update
- 3.1 — Waveform gradient helper
- 6.1 + 6.2 + 6.3 + 6.4 — Session 5 configuration (all one file)

### Wave 2 (depends on Wave 1)
- 1.2 — `_generate_artwork` cover-crop (needs 1.1)
- 1.3 — `_load_artwork_images` cover-crop (needs 1.1)
- 3.2 — Waveform gradient in `make_frame` (needs 3.1, 2.1)
- 3.3 — Waveform gradient in Short (needs 3.1)
- 4.1 — Ken Burns cover-crop awareness (needs 1.1)
- 5.1 — Short background cover-crop (needs 1.1)
- 5.3 — Short `bg_darken` from theme (needs 2.1)

### Wave 3 (depends on Wave 2)
- 4.2 — Ken Burns 110% source preparation (needs 1.1, 1.3)
- 5.2 — Short Ken Burns with cover-crop (needs 5.1)

### Wave 4 (validation)
- 7.1 — Session 5 validation (needs Wave 1 session tasks)
- 7.2 — Artwork pipeline validation (needs Waves 1-3 artwork tasks)
- 7.3 — Waveform gradient validation (needs Wave 2 gradient tasks)

## Float / Slack

| Task ID | Float | Notes |
|---------|-------|-------|
| 2.1 | 1 wave | Not on critical path; needed by Wave 2 but not blocking longest chain |
| 2.2 | 1 wave | Independent constant, only needed for validation |
| 2.3 | 3 waves | JSON edit, only validated at Wave 4 |
| 3.1 | 1 wave | Parallel to critical path; only blocks 3.2/3.3 |
| 3.2 | 1 wave | Only blocks validation 7.3 |
| 3.3 | 2 waves | Short gradient, not on critical path |
| 5.1–5.3 | 1 wave | Short pipeline parallel to main pipeline |
| 6.1–6.4 | 3 waves | Completely independent; only blocks 7.1 validation |

## Text DAG

```
                    ┌──→ [1.2] ─────────────────────────┐
                    │                                     │
[1.1] ─────────────┼──→ [1.3] ──→ [4.2] ───────────────┼──→ [7.2]
  (cover_crop)      │              (KB 110%)             │
                    ├──→ [4.1] ─────────────────────────┘
                    │
                    ├──→ [5.1] ──→ [5.2]
                    │
[2.1] ─────────────┼──→ [3.2] ──────────────────────────────→ [7.3]
  (darken=0.85)     │
                    └──→ [5.3]
[2.2]
  (blur=2)

[2.3]
  (s4 json)

[3.1] ─────────────┬──→ [3.2]
  (gradient fn)     └──→ [3.3]

[6.1+6.2+6.3+6.4] ──────────────────────────────────────────→ [7.1]
  (session 5 json)
```
