# Implementing ohtv via Agentic Workflow

This document explores using `lxa` (Long Execution Agent) to implement the `ohtv` trajectory viewer tool autonomously, with minimal human intervention.

## 1. The Vision

Instead of manually implementing `ohtv`, we use an agentic workflow:

1. **Design doc exists** → `DESIGN.md` is complete
2. **Decompose into issues** → Agent parses design, creates GitHub issues for each milestone
3. **Rank issues** → Issues are prioritized on a project board
4. **Agent works through issues** → Picks top issue, implements, creates PR
5. **Human reviews** → Approves or requests changes
6. **Agent refines** → Addresses review comments
7. **Merge and continue** → Repeat until done

This approach could allow overnight autonomous execution where multiple milestones are implemented, reviewed, and merged serially.

## 2. Available Tools

### 2.1 lxa (Long Execution Agent)

Repository: [jpshackelford/lxa](https://github.com/jpshackelford/lxa)

A system for agent-assisted software development built on the OpenHands SDK. Key capabilities:

#### Existing Commands (Merged)

| Command | Purpose |
|---------|---------|
| `lxa implement` | Start implementation from a design document |
| `lxa implement --loop` | Ralph Loop: continuous execution until all milestones complete |
| `lxa refine <PR_URL>` | PR refinement with self-review and response to comments |
| `lxa reconcile` | Update design doc to reference implemented code |
| `lxa board init` | Initialize/configure a GitHub Project board |
| `lxa board scan` | Find existing issues/PRs and add to board |
| `lxa board sync` | Sync board with GitHub state |
| `lxa board status` | Show board summary |
| `lxa board apply` | Apply YAML board configuration |

#### Board Workflow Columns

lxa uses a Kanban-style workflow with these columns:

- **Icebox** - Ideas not yet prioritized
- **Backlog** - Ready to work on
- **Agent Coding** - Agent is implementing
- **Human Review** - PR awaiting human review
- **Agent Refinement** - Agent addressing review comments
- **Final Review** - Ready for final approval
- **Approved** - Approved, ready to merge
- **Done** - Merged
- **Closed** - Closed without merge

### 2.2 OpenPaw (Scheduled Agent Tasks)

Repository: [jpshackelford/OpenPaw](https://github.com/jpshackelford/OpenPaw)

A lightweight, always-on AI assistant with scheduled tasks and chat connectors. Built on OpenHands SDK. Currently early development.

Potential use: Schedule periodic `lxa board work` runs or monitor for new issues.

## 3. What's Missing for Full Agentic Workflow

The user wants to add two new capabilities to lxa:

### 3.1 `lxa board decompose <design_doc>` - Design Doc → Issues

Parse a design document and create GitHub issues from it:
- Extract milestones/tasks from the design doc
- Create issues in the target repo
- Add issues to the board
- Optionally rank them

### 3.2 `lxa board work` - Pick & Implement Top Issue

Pick the top issue from the board and work on it:
- Find the top-ranked issue in "Backlog" or similar column
- Create a branch
- Run the implementation agent on it
- Create a PR
- Move the issue to the next column (Agent Coding → Human Review)

This would create a full agentic workflow:
1. Write design doc
2. `lxa board decompose DESIGN.md` → Creates issues on board
3. `lxa board work` → Agent picks top issue, implements, creates PR
4. Human reviews PR
5. `lxa refine <PR_URL>` → Agent addresses review comments
6. Repeat until done

### 3.3 Proposed CLI Interface

```bash
# Decompose design doc into issues
lxa board decompose DESIGN.md --repo jpshackelford/ohtv

# Options
lxa board decompose DESIGN.md --repo owner/repo \
    --dry-run                    # Preview without creating
    --column Backlog             # Initial column (default: Backlog)
    --labels "milestone,agent"   # Labels to add
    --rank                       # Auto-rank by dependency order
```

```bash
# Work on the top-ranked issue from Backlog
lxa board work

# Options
lxa board work --column Backlog  # Pick from specific column
lxa board work --issue 42        # Work on specific issue
lxa board work --loop            # Continue until backlog empty
lxa board work --auto-pr         # Auto-create PR when done
```

### 3.4 Full Workflow Example

```bash
# 1. Initialize repo with board
gh repo create jpshackelford/ohtv --public
cd ohtv && git init
cp ~/trajectory-viewer/DESIGN.md .
lxa board init --repo jpshackelford/ohtv

# 2. Decompose design into issues
lxa board decompose DESIGN.md --repo jpshackelford/ohtv --rank

# 3. Agent works through issues
lxa board work --loop --auto-pr

# 4. Human reviews PRs, agent refines
lxa refine https://github.com/jpshackelford/ohtv/pull/1

# 5. Repeat until done
```

## 4. Current State of lxa Development

### 4.1 Open PRs (In Flight)

| PR | Feature | Status | Relevance |
|----|---------|--------|-----------|
| **#64** | Project-scoped boards with overview item & mission | Open | 🔥 High - Creates boards tied to a project/design doc |
| **#63** | `lxa board add-item` for manual item addition | Open | 🔥 High - Needed to add decomposed issues |
| **#59** | Auto-discovery scan + gist-based config sync | Open | Medium |
| **#58** | `--multi-pr` autonomous mode (overnight execution) | Open | 🔥 High - Runs through multiple milestones |
| **#49** | Reasoning-focused visualizer | Open | Low |
| **#44** | Design Composition Agent (M1) | Open | 🔥 High - Agent writes design docs |

### 4.2 Open Issues (Planned Features)

| Issue | Feature | Relevance |
|-------|---------|-----------|
| **#62** | Intelligent scanning for project-scoped boards | Medium |
| **#61** | Project-scoped boards (implemented in PR #64) | High |
| **#60** | `add-item` command (implemented in PR #63) | High |
| **#57** | CI Gap Analysis after repeated failures | Medium |
| **#56** | Control Daemon for crash recovery | Medium |
| **#55** | Pre-merge learnings capture | Medium |
| **#54** | Load Skills from target repository | Medium |
| **#53** | Multi-PR autonomous execution (implemented in PR #58) | High |
| **#27** | Agent Specializations | Medium |
| **#26** | Task Parallelization | Medium |
| **#25** | Project Knowledge Base | Medium |
| **#24** | Progress Files for complex debugging | Medium |
| **#23** | Investigation Mode (read-only) | Medium |
| **#22** | **Task Decomposition** (agents break down large tasks) | 🔥 Very High |
| **#21** | Ralph Loop state persistence for crash recovery | Medium |

### 4.3 How Proposed Features Map to Existing Work

#### `decompose` Command

**Closest match: Issue #22 (Task Decomposition)**

Issue #22 describes agents creating sub-plans *during execution*. The `decompose` command extends this to:
- Parse a design doc **before** execution
- Create GitHub issues from milestones
- Add to board and rank

This could be:
- A new command: `lxa board decompose DESIGN.md`
- Or part of the Design Composition Agent flow (PR #44)

#### `work` Command

**Closest match: PR #58 (multi-PR mode) + project-scoped boards (PR #64)**

The multi-PR mode already does:
- Implement milestone → create PR → merge → next milestone

What's missing:
- Pick work from **board** (currently reads from design doc directly)
- Integration with project-scoped boards

## 5. Existing OpenHands Ecosystem Tools

Before building `ohtv`, we surveyed existing tools:

### 5.1 OpenHands CLI (`openhands view`)

The OpenHands CLI already has a basic viewer:

```bash
openhands view <conversation_id> --limit 20
```

Features:
- Views events from local conversations
- Requires full ID (no prefix matching)
- Rich console output only
- No filtering by event type
- No list command

### 5.2 trajectory-visualizer (Web App)

Repository: [OpenHands/trajectory-visualizer](https://github.com/OpenHands/trajectory-visualizer)

A React web application for visualizing trajectories:
- Visual timeline with keyboard navigation
- Upload JSON trajectory files
- GitHub workflow visualization
- Dark/light mode

**Not a CLI tool** - requires browser, doesn't read local `~/.openhands/conversations/` directly.

### 5.3 Gap Analysis: Why `ohtv` is Still Needed

| Feature | `openhands view` | trajectory-visualizer | `ohtv` (proposed) |
|---------|------------------|----------------------|-------------------|
| CLI tool | ✅ | ❌ (web) | ✅ |
| List conversations | ❌ | ❌ | ✅ |
| Short ID / prefix matching | ❌ | ❌ | ✅ |
| Filter by event type | ❌ | ❌ | ✅ |
| Multiple output formats | ❌ | ❌ | ✅ (md, json, text) |
| Slicing (offset/max) | ❌ | ❌ | ✅ |
| Reverse order | ❌ | ❌ | ✅ |
| Stats/counts view | ❌ | ❌ | ✅ |
| Alternate directory | ❌ | ❌ | ✅ |
| Scriptable (pipe to grep, less) | Partial | ❌ | ✅ |

## 6. Recommended Next Steps

### Option A: Build Foundation First

1. **Merge lxa foundation PRs**: #63 (add-item), #64 (project-scoped boards), #58 (multi-pr)
2. **File issues** for `decompose` and `work` commands
3. **Implement** those commands in lxa
4. **Then use lxa** to build ohtv

### Option B: Bootstrap ohtv Manually, Enhance lxa Later

1. **Create ohtv repo** with DESIGN.md
2. **Manually create issues** from milestones
3. **Use existing `lxa implement --loop`** with design doc
4. **Add board integration** to lxa later

### Option C: Parallel Development

1. **Create ohtv repo** as test bed
2. **Implement `decompose`** in lxa using ohtv as first customer
3. **Implement `work`** in lxa
4. **Use full workflow** to complete ohtv

## 7. Design Documents

- **ohtv design**: `DESIGN.md` (in this directory)
- **lxa design composition agent**: `doc/design/design-composition-agent.md` in lxa repo
- **lxa implementation agent**: `doc/design/implementation-agent-design.md` in lxa repo

## 8. References

- [jpshackelford/lxa](https://github.com/jpshackelford/lxa) - Long Execution Agent
- [jpshackelford/OpenPaw](https://github.com/jpshackelford/OpenPaw) - Scheduled agent tasks
- [OpenHands/OpenHands-CLI](https://github.com/OpenHands/OpenHands-CLI) - Official CLI with `view` command
- [OpenHands/trajectory-visualizer](https://github.com/OpenHands/trajectory-visualizer) - Web-based visualizer
- [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) - SDK used by lxa
