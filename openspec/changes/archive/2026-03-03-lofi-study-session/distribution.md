## Configuration

- **Agent count**: 3
- **Total tasks**: 22
- **Tasks per agent**: ~7-8

## Token Cost Warning

> **Multi-agent execution scales token costs.** Each agent maintains its own context window.
> With 3 agents, expect roughly 3x the token usage of a single-agent run.
> Estimated cost multiplier: **3x**

## Feasibility Assessment

3 agents is feasible. The task structure naturally clusters into three domains:

1. **Session config + theme infrastructure** — foundational work that others depend on, plus data files (session.json, font)
2. **Artwork + video loop pipeline** — new generation functions and integration with existing video bg system
3. **Visual theme application + testing** — applying theme values throughout the rendering pipeline and validating

The main constraint: all three agents touch `main.py`. To avoid merge conflicts, we assign distinct line ranges/function areas to each agent and use worktree isolation. Agent 1 builds the theme infrastructure that Agents 2 and 3 consume, creating a serialization point after Wave 2. However, Agent 1's foundational tasks (1.1, 1.2) are small enough that Agent 2 and Agent 3 can begin their independent work (prompt templates, animation functions) in parallel during Wave 1.

## Agent Assignments

### Agent 1: config-and-theme

**Tasks:**
- 1.1 Add theme loading to session config parser
- 1.2 Define default theme constants + `_get_session_theme` helper
- 1.3 Create `tracks/session 4/session.json`
- 1.4 Download Quicksand font
- 5.1 Theme-driven title rendering
- 5.2 Theme-driven particle colors
- 5.3 Theme-driven waveform colors
- 5.4 Theme-driven background color
- 5.5 Theme-driven bg darken factor

**File ownership:**
- `main.py` — Configuration section (~lines 23-60), `_get_session_theme()` new function, `generate_video()` visual theming reads (~lines 995+, title/particle/waveform/bg sections)
- `tracks/session 4/session.json` (new file)
- `fonts/Quicksand-Regular.ttf` (new file)

**Execution order:**
1. 1.3 (session.json — no deps, can start immediately)
2. 1.4 (font download — no deps)
3. 1.1 (theme loading in config parser)
4. 1.2 (theme helper function)
5. 5.1 → 5.2 → 5.3 → 5.4 → 5.5 (apply theme throughout generate_video)

**Cross-agent dependencies:**
- None — this agent's work is upstream of others

### Agent 2: artwork-and-loops

**Tasks:**
- 2.1 Add artwork prompt templates dict
- 2.2 Modify `_generate_artwork()` for theme-based style
- 2.3 Update callers of `_generate_artwork()`
- 3.1 Create Ken Burns frame function
- 3.2 Create ambient particles overlay function
- 3.3 Create light flicker function
- 3.4 Create `_generate_video_loop_from_artwork` compositor
- 3.5 Add caching to video loop generation

**File ownership:**
- `main.py` — `_generate_artwork()` function (~line 783), new animation functions (`_ken_burns_frame`, `_ambient_particles_overlay`, `_light_flicker`, `_generate_video_loop_from_artwork`) inserted before the existing `_predecode_video_loop`

**Execution order:**
1. 2.1 (prompt templates — no deps)
2. 3.1, 3.2, 3.3 (animation sub-functions — no deps, can be parallel)
3. 3.4 (compositor — needs 3.1-3.3)
4. 3.5 (caching wrapper — needs 3.4)
5. Wait for Agent 1's task 1.2 (theme helper)
6. 2.2 (modify _generate_artwork with theme — needs 1.2, 2.1)
7. 2.3 (update callers — needs 2.2)

**Cross-agent dependencies:**
- Depends on Agent 1 task 1.2 (`_get_session_theme` helper) before starting 2.2

### Agent 3: integration

**Tasks:**
- 4.1 Auto-generate video loops for realistic sessions
- 4.2 Auto-populate video_backgrounds at runtime
- 4.3 Store loops in artwork/session N/loops/
- 6.1 End-to-end test
- 6.2 Backward compatibility test
- 6.3 Verify video loop seamlessness

**File ownership:**
- `main.py` — integration logic in the main pipeline between artwork generation and video rendering (~lines 900-990), plus new `artwork/session N/loops/` directory creation

**Execution order:**
1. Wait for Agent 2's tasks 2.3 and 3.5 (artwork gen + video loop gen ready)
2. 4.1 (auto-generate loops)
3. 4.3 (loops directory — starts with 4.1)
4. 4.2 (auto-populate video_backgrounds)
5. Wait for Agent 1's task 5.5 (all theme application done)
6. 6.2 (backward compat test)
7. 6.1 (end-to-end test)
8. 6.3 (loop seamlessness verification)

**Cross-agent dependencies:**
- Depends on Agent 2 tasks 2.3, 3.5 before starting 4.1
- Depends on Agent 1 task 5.5 before starting 6.1, 6.2

## File Ownership Isolation

| File | Owner Agent | Notes |
|------|-------------|-------|
| `tracks/session 4/session.json` | Agent 1 (config-and-theme) | New file, no conflict |
| `fonts/Quicksand-Regular.ttf` | Agent 1 (config-and-theme) | New file, no conflict |
| `main.py` — config section + theme helper + generate_video theming | Agent 1 (config-and-theme) | Distinct code regions |
| `main.py` — artwork generation + animation functions | Agent 2 (artwork-and-loops) | Distinct code regions |
| `main.py` — pipeline integration (loop orchestration) | Agent 3 (integration) | Distinct code regions |

**Conflict note**: All 3 agents edit `main.py`. Using `isolation: "worktree"` gives each agent an isolated copy. The team lead merges worktrees sequentially: Agent 1 first (foundational), Agent 2 second (new functions), Agent 3 last (integration + tests). Merge order follows dependency flow.

## Cross-Agent Dependencies

| Waiting Agent | Blocked Task | Depends On | Owning Agent |
|---------------|-------------|------------|--------------|
| Agent 2 (artwork-and-loops) | 2.2 | 1.2 (_get_session_theme helper) | Agent 1 (config-and-theme) |
| Agent 3 (integration) | 4.1 | 2.3 (artwork callers updated) | Agent 2 (artwork-and-loops) |
| Agent 3 (integration) | 4.1 | 3.5 (video loop gen with cache) | Agent 2 (artwork-and-loops) |
| Agent 3 (integration) | 6.1, 6.2 | 5.5 (all theme applied) | Agent 1 (config-and-theme) |

## Claude Code Team Setup

To execute this plan, run `/opsx:multiagent-apply` on this change. It will automate the steps below.

Alternatively, set up the team manually:

**1. Create the team** using `TeamCreate`:
- `team_name`: `lofi-study-session`
- `description`: "LoFi study session: ~120min mix with realistic cosy room video backgrounds and warm visual theme"

**2. Populate the shared task list** using `TaskCreate` for each task:
- `subject`: task description (e.g., "1.1 Add theme loading to session config parser")
- `description`: include the `Files:` annotation and relevant context
- `activeForm`: present-continuous form (e.g., "Adding theme loading to config parser")

Then use `TaskUpdate` with `addBlockedBy` to set dependency relationships, and `TaskUpdate` with `owner` to pre-assign tasks per the agent assignments above.

**3. Spawn teammates** using the `Agent` tool for each agent:
- `name`: agent name from assignments above (config-and-theme, artwork-and-loops, integration)
- `team_name`: `lofi-study-session`
- `subagent_type`: "general-purpose"
- `isolation`: "worktree"
- `prompt`: include assigned tasks, file ownership, execution order, and cross-agent dependencies

**4. Merge order**: After all agents complete:
1. Merge Agent 1's worktree (config-and-theme) first
2. Merge Agent 2's worktree (artwork-and-loops) second
3. Merge Agent 3's worktree (integration) last

**5. Monitor and shutdown:** Use `TaskList` to track progress. Send `shutdown_request` via `SendMessage` when all tasks are complete.
