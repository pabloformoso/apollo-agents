## Configuration

- **Agent count**: 3
- **Total tasks**: 18
- **Tasks per agent**: 6 each

## Token Cost Warning

> **Multi-agent execution scales token costs.** Each agent maintains its own context window.
> With 3 agents, expect roughly 3× the token usage of a single-agent run.
> Estimated cost multiplier: **3×**

## Feasibility Assessment

3 agents is a good fit for this change. The work divides cleanly into three independent streams with minimal cross-agent dependencies:

1. **Session config & playlist** — `tracks/session 6/session.json` (self-contained)
2. **Code & font** — `main.py` and font file (self-contained)
3. **YouTube metadata** — `output/session 6/youtube.md` (depends on Agent 1's playlist for timestamps)

Only 1 cross-agent sync point exists: Agent 3 (YouTube) needs the finalized session.json from Agent 1 to calculate accurate timestamps. All other work is fully parallel.

Note: Track generation (task 4.1) is listed but requires manual Suno AI work — agents can prepare everything else and leave 4.1/4.2 for the user.

## Agent Assignments

### Agent 1: session-config

**Tasks:**
- 3.1 — Create `tracks/session 6/` directory
- 3.2 — Create session.json with name, description, theme block
- 3.3 — Define curated playlist with ~20 tracks
- 3.4 — Assign Camelot keys
- 3.5 — Assign genre tags
- 6.1 — End-to-end validation (partial — verify session loads)

**File ownership:**
- `tracks/session 6/session.json`
- `tracks/session 6/` (directory)

**Execution order:**
3.1 → 3.2 → 3.3 → 3.4 + 3.5 (parallel) → 6.1

**Cross-agent dependencies:**
- None — fully independent

### Agent 2: code-and-font

**Tasks:**
- 1.1 — Download Share Tech Mono font
- 2.1 — Add `"dark-techno"` entry to `ARTWORK_PROMPTS` in main.py
- 6.2 — Verify artwork prompt template works
- 6.3 — Verify font loads via PIL

**File ownership:**
- `main.py`
- `fonts/ShareTechMono-Regular.ttf`

**Execution order:**
1.1 + 2.1 (parallel) → 6.2 + 6.3 (parallel)

**Cross-agent dependencies:**
- None — fully independent

### Agent 3: youtube-metadata

**Tasks:**
- 5.1 — Create `output/session 6/` directory
- 5.2 — Write YouTube title
- 5.3 — Write YouTube description body
- 5.4 — Add timestamped tracklist (needs track durations)
- 5.5 — Add tags, hashtags, thumbnail text ideas

**File ownership:**
- `output/session 6/youtube.md`
- `output/session 6/` (directory)

**Execution order:**
5.1 → 5.2 + 5.3 (parallel) → 5.5 → 5.4 (last — needs track durations)

**Cross-agent dependencies:**
- Depends on Agent 1 completing 3.3 (playlist names for title/description)
- Task 5.4 depends on track WAV files existing (4.1/4.2 — user manual step)

## File Ownership Isolation

| File | Owner Agent | Notes |
|------|-------------|-------|
| `tracks/session 6/session.json` | Agent 1 (session-config) | Sole owner |
| `tracks/session 6/*.wav` | User (manual) | Generated via Suno AI |
| `main.py` | Agent 2 (code-and-font) | Sole owner |
| `fonts/ShareTechMono-Regular.ttf` | Agent 2 (code-and-font) | Sole owner |
| `output/session 6/youtube.md` | Agent 3 (youtube-metadata) | Sole owner |

No file conflicts. Each agent has exclusive write access to its files.

## Cross-Agent Dependencies

| Waiting Agent | Blocked Task | Depends On | Owning Agent |
|---------------|-------------|------------|--------------|
| Agent 3 (youtube) | 5.2 (title) | 3.3 (playlist) | Agent 1 (session-config) |
| Agent 3 (youtube) | 5.3 (description) | 3.3 (playlist) | Agent 1 (session-config) |
| Agent 3 (youtube) | 5.4 (timestamps) | 4.2 (WAV verify) | User (manual) |

## Claude Code Team Setup

To execute this plan, run `/opsx:multiagent-apply` on this change. It will automate the steps below.

Alternatively, set up the team manually:

**1. Create the team** using `TeamCreate`:
- `team_name`: `dark-techno-session`
- `description`: "Session 6 — Dark Techno: config, code, and YouTube metadata"

**2. Populate the shared task list** using `TaskCreate` for each task:
- `subject`: task description (e.g., "3.1 Create tracks/session 6/ directory")
- `description`: include the `Files:` annotation and relevant context
- `activeForm`: present-continuous form (e.g., "Creating session directory")

Then use `TaskUpdate` with `addBlockedBy` to set dependency relationships, and `TaskUpdate` with `owner` to pre-assign tasks per the agent assignments above.

**3. Spawn teammates** using the `Agent` tool for each agent:
- Agent 1: `name: "session-config"`, `team_name: "dark-techno-session"`, `subagent_type: "general-purpose"`, `isolation: "worktree"`
- Agent 2: `name: "code-and-font"`, `team_name: "dark-techno-session"`, `subagent_type: "general-purpose"`, `isolation: "worktree"`
- Agent 3: `name: "youtube-metadata"`, `team_name: "dark-techno-session"`, `subagent_type: "general-purpose"`, `isolation: "worktree"`

**4. Monitor and shutdown:** Use `TaskList` to track progress. Send `shutdown_request` via `SendMessage` when all tasks are complete.
