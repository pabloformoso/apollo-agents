## Dependency Matrix

| Task ID | Depends On | Type | Reason |
|---------|-----------|------|--------|
| 1.1 | — | — | No dependencies, system-level install |
| 1.2 | 1.1 | FS | pyrubberband pip package needs rubberband C lib present |
| 2.1 | 1.2 | FS | Cannot import pyrubberband until installed |
| 2.2 | 2.1 | FS | Helper needs import available; touches main.py |
| 2.3 | 2.2 | FS | Reverse conversion helper; touches same area of main.py |
| 2.4 | 2.3 | FS | Rewrite uses both conversion helpers; touches change_speed() in main.py |
| 2.5 | 2.4 | FS | Rename depends on rewrite being complete; same function in main.py |
| 3.1 | 2.5 | FS | Unit test requires the new implementation |
| 3.2 | 3.1 | FS | Full pipeline run after verifying basic functionality |
| 3.3 | 3.2 | FS | Listening check requires completed mix output |
| 3.4 | 3.2 | FS | Listening check requires completed mix output |

## Critical Path

1.1 → 1.2 → 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 3.1 → 3.2 → 3.3

10 tasks on the critical path. This is an inherently sequential change — each implementation step builds on the previous one in a single file.

## Parallel Execution Waves

### Wave 1 (no dependencies)
- 1.1 Install rubberband system library

### Wave 2
- 1.2 Add pyrubberband to pyproject.toml

### Wave 3
- 2.1 Add import
- 2.2 Create pydub → numpy helper
- 2.3 Create numpy → pydub helper
- 2.4 Rewrite change_speed() internals
- 2.5 Rename to change_tempo()

> Note: Wave 3 tasks are listed together but are serial within main.py. A single agent should execute 2.1–2.5 sequentially as one unit of work.

### Wave 4
- 3.1 Short stretch test

### Wave 5
- 3.2 Full pipeline run
- 3.3 Listen to Phantom Circuit transition (parallel with 3.4)
- 3.4 Listen to Subzero transition (parallel with 3.3)

## Float / Slack

| Task ID | Float | Notes |
|---------|-------|-------|
| 3.4 | Full | Not on critical path — can be done anytime after 3.2, in parallel with 3.3 |

All other tasks are on the critical path with zero float.

## Text DAG

```
[1.1] → [1.2] → [2.1] → [2.2] → [2.3] → [2.4] → [2.5] → [3.1] → [3.2] → [3.3]
                                                                        ↓
                                                                      [3.4]
```

This is essentially a linear pipeline. The only parallelism is the two listening checks (3.3 and 3.4) after the full pipeline run. This change is best executed by a single agent working sequentially.
