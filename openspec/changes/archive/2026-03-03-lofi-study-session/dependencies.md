## Dependency Matrix

| Task ID | Depends On | Type | Reason |
|---------|-----------|------|--------|
| 1.1 | — | — | No dependencies, foundational infrastructure |
| 1.2 | 1.1 | FS | Theme helper needs theme loading to exist |
| 1.3 | — | — | Session JSON is data, can be written independently |
| 1.4 | — | — | Font download is independent |
| 2.1 | — | — | Prompt templates are standalone constants |
| 2.2 | 1.2, 2.1 | FS | Needs theme helper (1.2) and prompt templates (2.1) to branch on style |
| 2.3 | 2.2 | FS | Callers can only be updated after the signature change |
| 3.1 | — | — | Standalone animation function, no deps |
| 3.2 | — | — | Standalone particle overlay function, no deps |
| 3.3 | — | — | Standalone brightness modulation function, no deps |
| 3.4 | 3.1, 3.2, 3.3 | FS | Composes all three sub-functions into loop generator |
| 3.5 | 3.4 | FS | Caching wraps the generation function |
| 4.1 | 2.3, 3.5 | FS | Needs artwork generation (2.3) and video loop generator (3.5) |
| 4.2 | 4.1 | FS | Populates list from generated loops |
| 4.3 | 4.1 | SS | Directory creation happens alongside loop generation |
| 5.1 | 1.2 | FS | Needs theme helper to read font/colors |
| 5.2 | 1.2 | FS | Needs theme helper to read particle color |
| 5.3 | 1.2 | FS | Needs theme helper to read waveform color |
| 5.4 | 1.2 | FS | Needs theme helper to read bg_color |
| 5.5 | 1.2 | FS | Needs theme helper to read bg_darken |
| 6.1 | 4.2, 5.5 | FS | Full pipeline must be complete |
| 6.2 | 5.5 | FS | Theme system must be fully applied |
| 6.3 | 4.2 | FS | Video loops must be generated |

## Critical Path

1.1 → 1.2 → 2.2 → 2.3 → 4.1 → 4.2 → 6.1

This is the longest chain (7 tasks). It flows through theme infrastructure → artwork generation with style → video loop integration → end-to-end test.

## Parallel Execution Waves

### Wave 1 (no dependencies)
- 1.1 Add theme loading to session config parser
- 1.3 Create session 4 session.json
- 1.4 Download Quicksand font
- 2.1 Add artwork prompt templates dict
- 3.1 Create Ken Burns frame function
- 3.2 Create ambient particles overlay function
- 3.3 Create light flicker function

### Wave 2 (depends on Wave 1)
- 1.2 Define default theme constants + `_get_session_theme` helper (needs 1.1)
- 3.4 Create `_generate_video_loop_from_artwork` compositor (needs 3.1, 3.2, 3.3)

### Wave 3 (depends on Wave 2)
- 2.2 Modify `_generate_artwork()` to accept theme (needs 1.2, 2.1)
- 3.5 Add caching to video loop generation (needs 3.4)
- 5.1 Theme-driven title rendering (needs 1.2)
- 5.2 Theme-driven particle colors (needs 1.2)
- 5.3 Theme-driven waveform colors (needs 1.2)
- 5.4 Theme-driven background color (needs 1.2)
- 5.5 Theme-driven bg darken factor (needs 1.2)

### Wave 4 (depends on Wave 3)
- 2.3 Update callers of `_generate_artwork()` (needs 2.2)

### Wave 5 (depends on Wave 4)
- 4.1 Auto-generate video loops for realistic sessions (needs 2.3, 3.5)
- 4.3 Store loops in artwork/session N/loops/ (starts with 4.1)

### Wave 6 (depends on Wave 5)
- 4.2 Auto-populate video_backgrounds at runtime (needs 4.1)
- 6.2 Backward compatibility test (needs 5.5)

### Wave 7 (depends on Wave 6)
- 6.1 End-to-end test (needs 4.2, 5.5)
- 6.3 Verify video loop seamlessness (needs 4.2)

## Float / Slack

| Task ID | Float | Notes |
|---------|-------|-------|
| 1.3 | High | Session JSON can be created anytime before 6.1 |
| 1.4 | High | Font file can be added anytime before 5.1 |
| 2.1 | Medium | Needed by Wave 3 but can be done in Wave 1 or 2 |
| 3.1 | Medium | Needed by 3.4 in Wave 2, but independent |
| 3.2 | Medium | Needed by 3.4 in Wave 2, but independent |
| 3.3 | Medium | Needed by 3.4 in Wave 2, but independent |
| 5.1–5.5 | Medium | Theme application tasks can run anytime after 1.2, not on critical path |
| 6.2 | Low | Should run after all theme work, before final delivery |
| 4.3 | Low | Tied to 4.1, just directory placement |

## Text DAG

```
Wave 1:          [1.1]   [1.3]  [1.4]  [2.1]   [3.1] [3.2] [3.3]
                   │                      │        │     │     │
Wave 2:          [1.2]                    │      [3.4]──────────┘
                   │                      │        │
                   ├──────────────────────┤        │
Wave 3:          [2.2]   [5.1] [5.2]   [3.5]
                   │      [5.3] [5.4]     │
                   │      [5.5]           │
Wave 4:          [2.3]                    │
                   │                      │
                   ├──────────────────────┘
Wave 5:          [4.1]──[4.3]
                   │
Wave 6:          [4.2]  [6.2]
                   │
Wave 7:          [6.1]  [6.3]
```
