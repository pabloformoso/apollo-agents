## Configuration

- **Agent count**: 3
- **Total tasks**: 20 (17 implementation + 3 validation)
- **Tasks per agent**: ~6-7

## Token Cost Warning

> **Multi-agent execution scales token costs.** Each agent maintains its own context window.
> With 3 agents, expect roughly 3× the token usage of a single-agent run.
> Estimated cost multiplier: **3×**

## Feasibility Assessment

3 agents is a good fit for this change. The work naturally splits into three independent streams:

1. **Artwork pipeline** — core `main.py` changes for cover-crop, brightness, blur (most complex, critical path)
2. **Overlay & Short** — waveform gradient and YouTube Short updates in `main.py` (depends on Agent 1's constants and `_cover_crop` helper)
3. **Session config** — purely `session.json` creation (completely independent, no code)

The main constraint is that Agents 1 and 2 both modify `main.py`. To avoid conflicts, Agent 1 works on the artwork/scaling functions and constants at the top of the file, while Agent 2 works on the `make_frame` inner function and Short-related functions. File ownership is divided by function scope within `main.py`.

## Agent Assignments

### Agent 1: artwork-pipeline

**Focus**: Cover-crop helper, artwork loading/generation, brightness & blur constants, Ken Burns integration

**Tasks:**
- 1.1 — Add `_cover_crop` helper function
- 1.2 — Update `_generate_artwork` to use `_cover_crop`
- 1.3 — Update `_load_artwork_images` to use `_cover_crop`
- 2.1 — Change `ARTWORK_DARKEN_FACTOR` to 0.85
- 2.2 — Change `ARTWORK_BLUR_RADIUS` to 2
- 4.1 — Update `_ken_burns_frame` for cover-crop awareness
- 4.2 — Update `_load_artwork_images` for 110% Ken Burns source
- 7.2 — Validate artwork pipeline (visual check)

**File ownership:**
- `main.py` lines 1–80 (constants)
- `main.py` functions: `_cover_crop` (new), `_generate_artwork`, `_load_artwork_images`, `_ken_burns_frame`

**Execution order:**
1. 2.1, 2.2 (constants — immediate)
2. 1.1 (`_cover_crop` helper)
3. 1.2, 1.3 (integration into artwork functions)
4. 4.1, 4.2 (Ken Burns integration)
5. 7.2 (validation)

**Cross-agent dependencies:**
- None — this agent is on the critical path and has no upstream dependencies

### Agent 2: overlay-and-short

**Focus**: Waveform gradient, Short pipeline fullscreen artwork, overlay readability

**Tasks:**
- 3.1 — Add `_apply_waveform_gradient` helper
- 3.2 — Integrate gradient in `generate_video` `make_frame`
- 3.3 — Integrate gradient in `_render_short_frame`
- 5.1 — Short background cover-crop
- 5.2 — Short Ken Burns with cover-crop
- 5.3 — Short `bg_darken` from theme
- 7.3 — Validate waveform gradient readability

**File ownership:**
- `main.py` functions: `_apply_waveform_gradient` (new), `generate_video` (only the `make_frame` inner function, gradient insertion point), `_render_short_frame`, `generate_short`, `_short_ken_burns_frame`

**Execution order:**
1. 3.1 (`_apply_waveform_gradient` helper — immediate)
2. 5.1, 5.3 (Short cover-crop and theme darken — after Agent 1 provides `_cover_crop`)
3. 3.2 (gradient in `make_frame` — after Agent 1 sets brightness constant)
4. 3.3, 5.2 (Short gradient and Ken Burns)
5. 7.3 (validation)

**Cross-agent dependencies:**
- Waits for Agent 1's task 1.1 (`_cover_crop` helper) before starting 5.1
- Waits for Agent 1's task 2.1 (brightness constant) before starting 3.2

### Agent 3: session-config

**Focus**: Session 5 JSON configuration file

**Tasks:**
- 2.3 — Update Session 4 `bg_darken` to 0.85
- 6.1 — Create `session.json` with name, description, theme
- 6.2 — Curated playlist order
- 6.3 — Camelot keys and genre tags
- 6.4 — Set `bg_darken` to 0.85
- 7.1 — Validate Session 5 loads correctly

**File ownership:**
- `tracks/session 4/session.json`
- `tracks/session 5/session.json` (new file)

**Execution order:**
1. 2.3 (Session 4 JSON update — immediate)
2. 6.1 + 6.2 + 6.3 + 6.4 (all part of creating one file — immediate)
3. 7.1 (validation — after file created)

**Cross-agent dependencies:**
- None — completely independent from Agents 1 and 2

## File Ownership Isolation

| File | Owner Agent | Notes |
|------|-------------|-------|
| `main.py` (constants, lines 1-80) | artwork-pipeline | Constants `ARTWORK_DARKEN_FACTOR`, `ARTWORK_BLUR_RADIUS` |
| `main.py` (`_cover_crop`, `_generate_artwork`, `_load_artwork_images`, `_ken_burns_frame`) | artwork-pipeline | Artwork scaling functions |
| `main.py` (`_apply_waveform_gradient`, `make_frame` gradient section, `_render_short_frame`, `generate_short`, `_short_ken_burns_frame`) | overlay-and-short | Overlay and Short functions |
| `tracks/session 4/session.json` | session-config | Theme `bg_darken` update |
| `tracks/session 5/session.json` | session-config | New file |

**Conflict note**: Both Agent 1 and Agent 2 modify `main.py`. They work on non-overlapping functions. Agent 2 should rebase on Agent 1's changes before merging if using worktrees. The `/opsx:multiagent-apply` workflow handles this via worktree isolation and sequential merge.

## Cross-Agent Dependencies

| Waiting Agent | Blocked Task | Depends On | Owning Agent |
|---------------|-------------|------------|--------------|
| overlay-and-short | 5.1 (Short cover-crop) | 1.1 (`_cover_crop` helper) | artwork-pipeline |
| overlay-and-short | 3.2 (gradient in make_frame) | 2.1 (brightness constant) | artwork-pipeline |

## Claude Code Team Setup

To execute this plan, run `/opsx:multiagent-apply` on this change. It will automate the steps below.

Alternatively, set up the team manually:

**1. Create the team** using `TeamCreate`:
- `team_name`: `fullscreen-artwork-pipeline`
- `description`: "Fullscreen artwork pipeline: cover-crop scaling, 85% brightness, waveform gradient, Session 5 config"

**2. Populate the shared task list** using `TaskCreate` for each task:
- `subject`: task description (e.g., "1.1 Add _cover_crop helper function")
- `description`: include the `Files:` annotation and relevant context
- `activeForm`: present-continuous form (e.g., "Adding _cover_crop helper function")

Then use `TaskUpdate` with `addBlockedBy` to set dependency relationships, and `TaskUpdate` with `owner` to pre-assign tasks per the agent assignments above.

**3. Spawn teammates** using the `Agent` tool for each agent:
- `name`: agent name from assignments above (`artwork-pipeline`, `overlay-and-short`, `session-config`)
- `team_name`: `fullscreen-artwork-pipeline`
- `subagent_type`: "general-purpose"
- `isolation`: "worktree"
- `prompt`: include assigned tasks, file ownership, execution order, and cross-agent dependencies

**4. Monitor and shutdown:** Use `TaskList` to track progress. Send `shutdown_request` via `SendMessage` when all tasks are complete.
