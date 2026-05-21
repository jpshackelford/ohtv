# Design: Conversation Metrics (Human Input + Merged LOC)

## Research Goal

Measure the impact of agent orchestration on development velocity:

1. **Velocity metrics by week**:
   - Merged PR count
   - Lines changed (added + removed)
   - Track before/after orchestration introduction

2. **Human input metrics**:
   - Human messages per PR
   - Human words per PR
   - Ratio: human words / lines changed

Key question: Does orchestration increase velocity while reducing human input per unit of output?

## Data Sources in Trace

### Event Types Available

The trace data stored in `~/.openhands/cloud/conversations/<id>/events/` contains these relevant event types:

| Event Kind | Source | Contains | Usage |
|------------|--------|----------|-------|
| `MessageEvent` | `user` | `llm_message.content[].text` | Human messages |
| `MessageEvent` | `agent` | Agent responses | N/A for human words |
| `ActionEvent` | `agent` | Actions: terminal, file_editor, finish | Commands, file edits |
| `ObservationEvent` | `environment` | Results of actions | Git output, file content |

### Human Message Structure

```json
{
  "kind": "MessageEvent",
  "source": "user",
  "llm_message": {
    "content": [
      {"type": "text", "text": "The actual human message text"}
    ]
  },
  "activated_skills": [],
  "sender": null  // null for human, may have value for automation
}
```

### File Edit Observation Structure

```json
{
  "kind": "ObservationEvent",
  "observation": {
    "kind": "FileEditorObservation",
    "command": "str_replace",
    "path": "/workspace/project/file.ts",
    "old_content": "... original content ...",
    "new_content": "... updated content ...",
    "is_error": false
  }
}
```

### Git Push Output Structure

```json
{
  "kind": "ObservationEvent",
  "observation": {
    "kind": "TerminalObservation",
    "content": [{"text": "... 418680a..6ecae71  main -> main ..."}],
    "command": "git push origin main",
    "exit_code": 0
  }
}
```

## Challenges

### 1. Human vs Automated Messages

Not all `MessageEvent` with `source: "user"` are truly human:
- **Human-initiated**: User types in chat interface
- **Automation-initiated**: API call from orchestrator, plugin, webhook

Distinguishing factors (heuristics):
- Conversations with 0 user messages are likely orchestrator-spawned workers
- Conversations that start with a GitHub issue reference (from `selected_repository`) may be automation
- The `sender` field may indicate automation source

**Proposed Approach**: 
1. Default to counting all `source: "user"` MessageEvents as human
2. Add optional `--exclude-automated` flag with heuristics
3. Consider adding conversation tagging/labeling in a future stage

### 2. CLOC Computation: Net Merged Lines

**Challenge**: We care about the **net effect that landed in the repo**, not:
- Intermediate file edits (double-counting)
- Individual commit stats (may include reverts/refactors that cancel out)

**Solution**: Use GitHub API to get the true net change.

#### Two Scenarios

| Scenario | Detection | GitHub API | Returns |
|----------|-----------|------------|---------|
| **Merged PR** | PR ref with `link_type='write'` in database, PR is merged | `GET /repos/{owner}/{repo}/pulls/{number}` | `additions`, `deletions`, `changed_files` |
| **Direct push to main** | Push output with no associated PR | `GET /repos/{owner}/{repo}/compare/{base}...{head}` | Sum of file additions/deletions |

#### Example: Merged PR Stats
```bash
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/owner/repo/pulls/258"
```
```json
{
  "merged": true,
  "additions": 305,
  "deletions": 32,
  "changed_files": 2
}
```

#### Example: Direct Push Stats (using commit range from push output)
Push output shows: `418680a..6ecae71  main -> main`

```bash
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/owner/repo/compare/418680a...6ecae71"
```
```json
{
  "total_commits": 1,
  "files": [
    {"filename": "WORKLOG.md", "additions": 34, "deletions": 0}
  ]
}
```

#### Why Not Local-Only Options?

| Approach | Problem |
|----------|---------|
| File editor observations | Double-counts intermediate edits |
| Git commit output stats | Doesn't account for reverts/refactors across commits |
| Sum all commits | Same issue - commits may cancel each other out |

**The net merged CLOC is only knowable from the final state comparison** - which is what GitHub's PR diff and Compare API provide.

## Data Model

### Core Principle

**LOC metrics live on the PR/commit, not the conversation.**

- One PR = one set of LOC metrics (even if multiple conversations contributed)
- Conversations link to PRs via contributions
- Human input metrics live on conversations
- Research queries join these to compute ratios

### Database Schema

```sql
-- Track PRs and direct pushes to main
-- LOC is fetched once per change, not per conversation
CREATE TABLE change_refs (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    
    -- What kind of change
    change_type TEXT NOT NULL,          -- "pr" | "direct_push"
    pr_number INTEGER,                  -- For PRs
    commit_range TEXT,                  -- For direct push: "abc123..def456"
    branch TEXT,                        -- Target branch (main, master)
    
    -- Status (direct_push is always merged; PRs need checking)
    status TEXT NOT NULL DEFAULT 'pending',  -- "pending" | "merged" | "open" | "closed"
    merged_at TEXT,                     -- When merged (for time-series analysis)
    
    -- LOC metrics (populated via GitHub API for merged changes)
    lines_added INTEGER,
    lines_removed INTEGER,
    files_changed INTEGER,
    
    -- Fetch tracking
    fetched_at TEXT,                    -- When we last called GitHub API
    
    FOREIGN KEY (repo_id) REFERENCES repositories(id),
    UNIQUE (repo_id, change_type, pr_number, commit_range)
);

-- Link conversations to changes they contributed to
-- Multiple conversations can contribute to one PR
CREATE TABLE conversation_contributions (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    change_ref_id INTEGER NOT NULL,
    contribution_type TEXT NOT NULL,    -- "created" | "pushed" | "merged"
    
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    FOREIGN KEY (change_ref_id) REFERENCES change_refs(id),
    UNIQUE (conversation_id, change_ref_id, contribution_type)
);

-- Human input metrics per conversation (computed locally, no API)
-- Distinguishes initial prompt from follow-up messages
CREATE TABLE conversation_human_input (
    conversation_id TEXT PRIMARY KEY,
    
    -- Initial prompt (first user message)
    initial_prompt_words INTEGER NOT NULL DEFAULT 0,
    initial_prompt_source TEXT NOT NULL DEFAULT 'unknown',  -- "human" | "automation" | "unknown"
    
    -- Follow-up messages (subsequent user messages - human steering)
    followup_word_count INTEGER NOT NULL DEFAULT 0,
    followup_message_count INTEGER NOT NULL DEFAULT 0,
    
    -- Processing metadata
    processed_at TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    CHECK (initial_prompt_source IN ('human', 'automation', 'unknown'))
);

-- Human word count computed at query time based on initial_prompt_source:
-- CASE 
--   WHEN initial_prompt_source = 'human' THEN initial_prompt_words + followup_word_count
--   WHEN initial_prompt_source = 'automation' THEN followup_word_count
--   ELSE NULL  -- unknown, exclude from analysis until classified
-- END AS human_word_count
```

### Processing Pipeline

**Stage 1: `contributions` (post-sync, fast, local)**
- Scan conversations for PR/push actions
- Create `change_refs` entries with `status = 'pending'`
- Create `conversation_contributions` links
- Compute `conversation_human_input` (word/message counts)
- No API calls

**Stage 2: `ohtv fetch-loc` (on-demand command, network)**
- For PRs with `status = 'pending'`: check GitHub, update status
- For `status = 'merged'` or direct pushes: fetch LOC if not yet fetched
- Cache results; re-run with `--force` to refresh

### Pipeline Integration

Stage order: `refs → actions → branch_context → push_pr_links → summaries → contributions`

The new `contributions` stage runs last in the automatic pipeline.

## Research Queries

### Weekly Velocity (Merged PRs + LOC)

```sql
-- Merged PRs per week with LOC
SELECT 
    strftime('%Y-W%W', cr.merged_at) AS week,
    COUNT(*) AS merged_pr_count,
    SUM(cr.lines_added) AS total_lines_added,
    SUM(cr.lines_removed) AS total_lines_removed,
    SUM(cr.lines_added + cr.lines_removed) AS total_lines_changed
FROM change_refs cr
WHERE cr.status = 'merged'
  AND cr.change_type = 'pr'
GROUP BY week
ORDER BY week;
```

### Human Input per PR

```sql
-- For each merged PR: total human words from all contributing conversations
SELECT 
    cr.id AS change_ref_id,
    r.fqn AS repo,
    cr.pr_number,
    cr.merged_at,
    cr.lines_added,
    cr.lines_removed,
    SUM(chi.human_word_count) AS total_human_words,
    SUM(chi.human_message_count) AS total_human_messages,
    COUNT(DISTINCT cc.conversation_id) AS conversation_count
FROM change_refs cr
JOIN repositories r ON cr.repo_id = r.id
JOIN conversation_contributions cc ON cr.id = cc.change_ref_id
JOIN conversation_human_input chi ON cc.conversation_id = chi.conversation_id
WHERE cr.status = 'merged'
GROUP BY cr.id;
```

### Human Words per Line Changed (Ratio Over Time)

```sql
-- Weekly ratio: human words per line of code changed
SELECT 
    strftime('%Y-W%W', cr.merged_at) AS week,
    SUM(chi.human_word_count) AS total_human_words,
    SUM(cr.lines_added + cr.lines_removed) AS total_loc,
    ROUND(CAST(SUM(chi.human_word_count) AS FLOAT) / 
          NULLIF(SUM(cr.lines_added + cr.lines_removed), 0), 2) AS words_per_loc
FROM change_refs cr
JOIN conversation_contributions cc ON cr.id = cc.change_ref_id
JOIN conversation_human_input chi ON cc.conversation_id = chi.conversation_id
WHERE cr.status = 'merged'
GROUP BY week
ORDER BY week;
```

### Before/After Orchestration Comparison

```sql
-- Compare metrics before/after a specific date
WITH metrics AS (
    SELECT 
        CASE WHEN cr.merged_at < '2024-03-01' THEN 'before' ELSE 'after' END AS period,
        cr.lines_added + cr.lines_removed AS loc,
        chi.human_word_count AS words
    FROM change_refs cr
    JOIN conversation_contributions cc ON cr.id = cc.change_ref_id
    JOIN conversation_human_input chi ON cc.conversation_id = chi.conversation_id
    WHERE cr.status = 'merged'
)
SELECT 
    period,
    COUNT(*) AS pr_count,
    SUM(loc) AS total_loc,
    SUM(words) AS total_human_words,
    ROUND(CAST(SUM(words) AS FLOAT) / NULLIF(SUM(loc), 0), 2) AS words_per_loc
FROM metrics
GROUP BY period;
```

## Algorithms

### Human Word Counting (Local, Fast)

```python
def count_human_words(events: list[dict]) -> tuple[int, int]:
    """Return (word_count, message_count) from user messages."""
    word_count = 0
    message_count = 0
    
    for event in events:
        if event.get("source") == "user" and event.get("kind") == "MessageEvent":
            content = extract_message_content(event)
            words = content.split()
            word_count += len(words)
            message_count += 1
    
    return word_count, message_count
```

### Detect PR Contributions (Local, Fast)

```python
def detect_contributions(conversation_id: str, events: list[dict], actions: list[Action]) -> list[dict]:
    """Detect PRs/pushes this conversation contributed to."""
    contributions = []
    
    for action in actions:
        if action.action_type == "open-pr":
            contributions.append({
                "change_type": "pr",
                "pr_number": action.metadata.get("pr_number"),
                "repo": action.metadata.get("repo"),
                "contribution_type": "created",
            })
        elif action.action_type == "merge-pr":
            contributions.append({
                "change_type": "pr",
                "pr_number": action.metadata.get("pr_number"),
                "repo": action.metadata.get("repo"),
                "contribution_type": "merged",
            })
        elif action.action_type == "git-push":
            branch = action.metadata.get("branch")
            if branch in ("main", "master"):
                # Direct push to main
                contributions.append({
                    "change_type": "direct_push",
                    "commit_range": action.metadata.get("commit_range"),
                    "repo": action.metadata.get("repo"),
                    "branch": branch,
                    "contribution_type": "pushed",
                })
            else:
                # Push to PR branch - need to find associated PR
                # (handled by linking branch to PR via refs)
                pass
    
    return contributions
```

### Fetch LOC from GitHub (On-Demand, Network)

```python
async def fetch_loc_for_change(change_ref: ChangeRef, token: str) -> dict:
    """Fetch LOC for a single change_ref from GitHub API."""
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        if change_ref.change_type == "pr":
            url = f"https://api.github.com/repos/{change_ref.repo}/pulls/{change_ref.pr_number}"
            resp = await client.get(url, headers=headers)
            data = resp.json()
            return {
                "status": "merged" if data.get("merged") else ("closed" if data.get("state") == "closed" else "open"),
                "merged_at": data.get("merged_at"),
                "lines_added": data.get("additions") if data.get("merged") else None,
                "lines_removed": data.get("deletions") if data.get("merged") else None,
                "files_changed": data.get("changed_files") if data.get("merged") else None,
            }
        else:  # direct_push
            base, head = change_ref.commit_range.split("..")
            url = f"https://api.github.com/repos/{change_ref.repo}/compare/{base}...{head}"
            resp = await client.get(url, headers=headers)
            data = resp.json()
            lines_added = sum(f.get("additions", 0) for f in data.get("files", []))
            lines_removed = sum(f.get("deletions", 0) for f in data.get("files", []))
            return {
                "status": "merged",  # Direct pushes are always merged
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "files_changed": len(data.get("files", [])),
            }
```

## CLI Interface

```bash
# After sync, human input is already computed (fast, local)
# View conversation with human input metrics
ohtv show <conversation_id>

# Fetch LOC from GitHub for pending changes
ohtv fetch-loc                    # All pending
ohtv fetch-loc --repo owner/repo  # Specific repo
ohtv fetch-loc --force            # Re-fetch even if cached

# Research queries (after fetch-loc)
ohtv report velocity --weekly     # PRs merged + LOC per week
ohtv report human-input           # Human words per PR
ohtv report efficiency            # Words per LOC ratio over time

# Export for analysis
ohtv report velocity --format csv > velocity.csv
```

## Files to Create/Modify

### New Files
- `src/ohtv/db/models/contributions.py` - ChangeRef, Contribution dataclasses
- `src/ohtv/db/stores/contributions_store.py` - Database operations  
- `src/ohtv/db/stages/contributions.py` - Processing stage (local, fast)
- `src/ohtv/db/migrations/NNN_contributions.py` - Schema migration
- `src/ohtv/commands/fetch_loc.py` - GitHub API fetch command
- `src/ohtv/commands/report.py` - Research report generation

### Modified Files
- `src/ohtv/db/stages/__init__.py` - Register contributions stage
- `src/ohtv/cli.py` - Add `fetch-loc` and `report` commands

## Implementation Priority

1. **Phase 1: Schema + contributions stage** (local, fast)
   - Add `change_refs`, `conversation_contributions`, `conversation_human_input` tables
   - Implement `contributions` processing stage
   - Human word counting
   - PR/push contribution detection

2. **Phase 2: fetch-loc command** (network, cached)
   - GitHub API integration for PR status + LOC
   - Compare API for direct pushes
   - Caching and re-fetch logic

3. **Phase 3: Research reports**
   - `ohtv report velocity` - weekly PR count + LOC
   - `ohtv report efficiency` - human words per LOC ratio
   - CSV export for further analysis
