## Dependency Matrix

| Task ID | Depends On | Type | Reason |
|---------|-----------|------|--------|
| 1.1 | — | — | No dependencies, standalone font download |
| 2.1 | — | — | No dependencies, standalone code change to main.py |
| 3.1 | — | — | No dependencies, directory creation |
| 3.2 | 3.1 | FS | Directory must exist before writing session.json |
| 3.3 | 3.2 | FS | Session.json must exist before adding playlist entries |
| 3.4 | 3.3 | FS | Playlist entries must exist before assigning Camelot keys |
| 3.5 | 3.3 | FS | Playlist entries must exist before assigning genres |
| 4.1 | 3.3 | FS | Need track names from playlist to generate matching audio |
| 4.2 | 4.1 | FS | Tracks must be generated before verification |
| 5.1 | — | — | No dependencies, directory creation |
| 5.2 | 3.3 | FS | Need session name/subtitle for YouTube title |
| 5.3 | 3.3 | FS | Need playlist info for narrative arc description |
| 5.4 | 4.2 | FS | Need actual track durations for timestamp calculation |
| 5.5 | 5.3 | FS | Description must exist before adding tags/hashtags section |
| 6.1 | 3.5, 4.2 | FS | Need complete session.json and all WAV files |
| 6.2 | 2.1 | FS | Need artwork prompt to exist before testing it |
| 6.3 | 1.1 | FS | Need font file to exist before testing it |

## Critical Path

```
3.1 → 3.2 → 3.3 → 4.1 → 4.2 → 5.4 → 6.1
```

This is the longest chain (7 tasks). Track generation (4.1) is the bottleneck — it requires the playlist to be defined and produces the WAV files needed for timestamp calculation and validation.

## Parallel Execution Waves

### Wave 1 (no dependencies)
- 1.1 — Download Share Tech Mono font
- 2.1 — Add dark-techno artwork prompt to main.py
- 3.1 — Create `tracks/session 6/` directory
- 5.1 — Create `output/session 6/` directory

### Wave 2 (depends on Wave 1)
- 3.2 — Create session.json with name, description, theme (depends on 3.1)

### Wave 3 (depends on Wave 2)
- 3.3 — Define playlist with ~20 tracks (depends on 3.2)
- 6.2 — Verify artwork prompt (depends on 2.1)
- 6.3 — Verify font loads (depends on 1.1)

### Wave 4 (depends on Wave 3)
- 3.4 — Assign Camelot keys (depends on 3.3)
- 3.5 — Assign genre tags (depends on 3.3)
- 4.1 — Generate WAV tracks via Suno (depends on 3.3)
- 5.2 — Write YouTube title (depends on 3.3)
- 5.3 — Write YouTube description body (depends on 3.3)

### Wave 5 (depends on Wave 4)
- 4.2 — Verify all WAV files (depends on 4.1)
- 5.5 — Add tags/hashtags/thumbnail ideas (depends on 5.3)

### Wave 6 (depends on Wave 5)
- 5.4 — Calculate timestamps and add tracklist (depends on 4.2)
- 6.1 — End-to-end validation (depends on 3.5, 4.2)

## Float / Slack

| Task ID | Float | Notes |
|---------|-------|-------|
| 1.1 | High | Can be delayed until Wave 3 (only blocks 6.3) |
| 2.1 | High | Can be delayed until Wave 3 (only blocks 6.2) |
| 5.1 | High | Can be delayed until before 5.2 |
| 3.4 | Medium | Can run parallel with 3.5, only blocks 6.1 |
| 3.5 | Medium | Can run parallel with 3.4, only blocks 6.1 |
| 5.2 | Medium | Independent of track generation, only needs playlist names |
| 5.3 | Medium | Independent of track generation, only needs playlist structure |
| 5.5 | Medium | Can be delayed, only needs description to exist |
| 6.2 | High | Standalone verification, no downstream dependencies |
| 6.3 | High | Standalone verification, no downstream dependencies |

## Text DAG

```
Wave 1          Wave 2      Wave 3       Wave 4         Wave 5      Wave 6
──────          ──────      ──────       ──────         ──────      ──────

[1.1 font] ─────────────────────────────────────────── [6.3 verify font]

[2.1 prompt] ───────────────────────────────────────── [6.2 verify prompt]

[3.1 dir] ──→ [3.2 json] ──→ [3.3 playlist] ──┬──→ [3.4 keys] ──┐
                                                ├──→ [3.5 genres] ┼──→ [6.1 e2e]
                                                ├──→ [4.1 gen] ──→ [4.2 verify] ─┤
                                                ├──→ [5.2 title]                  │
                                                └──→ [5.3 desc] ──→ [5.5 tags]   │
                                                                                  │
[5.1 dir] ──────────────────────────────── [5.4 timestamps] ◄────────────────────┘
```
