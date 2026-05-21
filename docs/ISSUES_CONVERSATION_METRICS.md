# Implementation Issues: Conversation Metrics

This document defines the issues needed to implement conversation metrics tracking.
Each issue has specific acceptance criteria and verification instructions.

---

## Issue 1: Database Schema for Contribution Tracking

**Summary**: Add database tables for tracking PR/push contributions and human input metrics.

**Description**:
Create a new migration that adds three tables:
- `change_refs` - Tracks PRs and direct pushes to main
- `conversation_contributions` - Links conversations to changes they contributed to
- `conversation_human_input` - Stores human word/message counts per conversation

**Files to Create/Modify**:
- `src/ohtv/db/migrations/NNN_contributions.py` (new migration)
- `src/ohtv/db/schema.py` (if schema is defined there)

**Acceptance Criteria**:
1. Migration creates all three tables with correct columns and constraints
2. Migration is idempotent (can run multiple times safely)
3. Foreign key constraints are enforced
4. Unique constraints prevent duplicate entries
5. Migration runs successfully on existing databases with data

**Schema** (from design doc):
```sql
CREATE TABLE change_refs (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    change_type TEXT NOT NULL,          -- "pr" | "direct_push"
    pr_number INTEGER,
    commit_range TEXT,
    branch TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    merged_at TEXT,
    lines_added INTEGER,
    lines_removed INTEGER,
    files_changed INTEGER,
    fetched_at TEXT,
    FOREIGN KEY (repo_id) REFERENCES repositories(id),
    UNIQUE (repo_id, change_type, pr_number, commit_range)
);

CREATE TABLE conversation_contributions (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    change_ref_id INTEGER NOT NULL,
    contribution_type TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    FOREIGN KEY (change_ref_id) REFERENCES change_refs(id),
    UNIQUE (conversation_id, change_ref_id, contribution_type)
);

CREATE TABLE conversation_human_input (
    conversation_id TEXT PRIMARY KEY,
    
    -- Initial prompt (first user message)
    initial_prompt_words INTEGER NOT NULL DEFAULT 0,
    initial_prompt_source TEXT NOT NULL DEFAULT 'unknown',  -- "human" | "automation" | "unknown"
    
    -- Follow-up messages (subsequent user messages)
    followup_word_count INTEGER NOT NULL DEFAULT 0,
    followup_message_count INTEGER NOT NULL DEFAULT 0,
    
    -- Processing metadata
    processed_at TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    CHECK (initial_prompt_source IN ('human', 'automation', 'unknown'))
);

-- Human word count computed at query time:
-- CASE 
--   WHEN initial_prompt_source = 'human' THEN initial_prompt_words + followup_word_count
--   WHEN initial_prompt_source = 'automation' THEN followup_word_count
--   ELSE NULL  -- unknown, needs classification
-- END AS human_word_count
```

**Verification Instructions**:
```bash
# 1. Run migration on fresh database
rm -f ~/.ohtv/index.db
ohtv sync -n 5

# 2. Verify tables exist
sqlite3 ~/.ohtv/index.db ".schema change_refs"
sqlite3 ~/.ohtv/index.db ".schema conversation_contributions"
sqlite3 ~/.ohtv/index.db ".schema conversation_human_input"

# 3. Verify foreign keys work (should fail)
sqlite3 ~/.ohtv/index.db "INSERT INTO change_refs (repo_id, change_type, status) VALUES (99999, 'pr', 'pending');"
# Expected: FOREIGN KEY constraint failed

# 4. Run migration again (idempotent)
ohtv sync -n 1
# Expected: No errors
```

**Test Requirements**:
- Unit test: Migration creates tables with correct schema
- Unit test: Foreign key constraints are enforced
- Unit test: Unique constraints prevent duplicates
- Integration test: Migration runs on database with existing data

**Dependencies**: None (foundational)

---

## Issue 2: Human Input Counting Stage

**Summary**: Add processing stage that counts human words and messages per conversation, distinguishing between initial prompt and follow-up messages.

**Description**:
Create a new processing stage `human_input` that:
1. Iterates through conversation events
2. Identifies `MessageEvent` with `source: "user"`
3. Distinguishes **initial prompt** (first user message) from **follow-up messages** (subsequent)
4. Extracts text content and counts words separately for each category
5. Stores results in `conversation_human_input` table

**Why Distinguish Initial Prompt from Follow-ups?**

For research purposes, we care about:
- **Initial prompt**: The task definition that starts the conversation (could be human or automated)
- **Follow-up messages**: Human guidance/corrections during execution (always human intervention)

The hypothesis is that orchestration reduces the need for follow-up messages (less human steering).

**Data Model Clarification**:

In the trace data, both initial prompt and follow-ups are structurally identical:
- Same type: `MessageEvent` with `source: "user"`
- Same structure: `llm_message.content[].text`
- Only difference: **position** in event sequence

The first `MessageEvent` with `source: "user"` is the initial prompt. All subsequent ones are follow-ups.

**Files to Create/Modify**:
- `src/ohtv/db/stages/human_input.py` (new)
- `src/ohtv/db/stages/__init__.py` (register stage)

**Acceptance Criteria**:
1. Stage processes all conversations without `conversation_human_input` entries
2. Correctly identifies user messages (source="user", kind="MessageEvent")
3. **Separately counts initial prompt vs follow-up messages**
4. Extracts text from `llm_message.content[].text` structure
5. Word count uses whitespace splitting (simple, reproducible)
6. Stores all metrics in `conversation_human_input` table
7. Stage is idempotent - reprocessing same conversation produces same results
8. Stage skips already-processed conversations (based on event_count match)

**Algorithm**:
```python
@dataclass
class HumanInputMetrics:
    # Initial prompt (first user message)
    initial_prompt_words: int
    
    # Follow-up messages (all subsequent user messages)
    followup_word_count: int
    followup_message_count: int
    
    # Totals (for convenience)
    total_word_count: int  # initial + followups
    total_message_count: int  # 1 (if has initial) + followups


def count_human_input(events: list[dict]) -> HumanInputMetrics:
    """Count human input, separating initial prompt from follow-ups."""
    initial_prompt_words = 0
    followup_word_count = 0
    followup_message_count = 0
    found_initial = False
    
    for event in events:
        if event.get("kind") != "MessageEvent":
            continue
        if event.get("source") != "user":
            continue
        
        # Extract text from llm_message.content
        llm_message = event.get("llm_message", {})
        content_list = llm_message.get("content", [])
        
        words = 0
        for content_item in content_list:
            if isinstance(content_item, dict) and content_item.get("type") == "text":
                text = content_item.get("text", "")
                words += len(text.split())
        
        if not found_initial:
            # First user message is the initial prompt
            initial_prompt_words = words
            found_initial = True
        else:
            # Subsequent messages are follow-ups
            followup_word_count += words
            followup_message_count += 1
    
    return HumanInputMetrics(
        initial_prompt_words=initial_prompt_words,
        followup_word_count=followup_word_count,
        followup_message_count=followup_message_count,
        total_word_count=initial_prompt_words + followup_word_count,
        total_message_count=(1 if found_initial else 0) + followup_message_count,
    )
```

**Verification Instructions**:
```bash
# 1. Sync some conversations
ohtv sync -n 20

# 2. Check human_input stage ran (should show in stage list)
# Look for human_input in processing output

# 3. Query results
sqlite3 ~/.ohtv/index.db "SELECT conversation_id, human_word_count, human_message_count FROM conversation_human_input LIMIT 10;"

# 4. Verify a specific conversation manually
# Pick a conversation_id from above, then:
ohtv show <conversation_id>
# Manually count user messages and compare

# 5. Verify idempotency - run sync again
ohtv sync -n 0
# Check that word counts haven't changed for existing conversations
```

**Test Requirements**:
- Unit test: `count_human_input` with sample events returns correct counts
- Unit test: Handles empty conversations (0 words, 0 messages)
- Unit test: Handles conversations with no user messages (orchestrator workers)
- Unit test: Handles malformed events gracefully
- Integration test: Stage populates database correctly
- Integration test: Stage skips already-processed conversations

**Dependencies**: Issue 1 (schema)

---

## Issue 3: PR Contribution Detection

**Summary**: Detect when conversations create, push to, or merge PRs.

**Description**:
Extend the processing pipeline to detect PR contributions by analyzing existing `actions` data:
1. `open-pr` action → contribution_type="created"
2. `merge-pr` action → contribution_type="merged"  
3. `git-push` to a PR branch → contribution_type="pushed"

Create `change_refs` entries for each PR and link via `conversation_contributions`.

**Files to Create/Modify**:
- `src/ohtv/db/stages/contributions.py` (new)
- `src/ohtv/db/stages/__init__.py` (register stage)
- `src/ohtv/db/stores/contributions_store.py` (new, for DB operations)

**Acceptance Criteria**:
1. Detects `open-pr` actions and creates change_ref with contribution_type="created"
2. Detects `merge-pr` actions and creates change_ref with contribution_type="merged"
3. Links PR branch pushes to existing PR change_refs (contribution_type="pushed")
4. Does not create duplicate change_refs for same PR
5. Multiple conversations can contribute to same PR (many-to-many)
6. Extracts repo from action metadata and links to existing `repositories` table
7. PR change_refs have status="pending" initially

**Key Logic**:
```python
def process_contributions(conversation_id: str, actions: list[Action]) -> list[Contribution]:
    contributions = []
    
    for action in actions:
        if action.action_type == "open-pr":
            # Get or create change_ref for this PR
            change_ref = get_or_create_pr_change_ref(
                repo=action.metadata["repo"],
                pr_number=action.metadata["pr_number"],
            )
            contributions.append(Contribution(
                conversation_id=conversation_id,
                change_ref_id=change_ref.id,
                contribution_type="created",
            ))
        
        elif action.action_type == "merge-pr":
            change_ref = get_or_create_pr_change_ref(
                repo=action.metadata["repo"],
                pr_number=action.metadata["pr_number"],
            )
            contributions.append(Contribution(
                conversation_id=conversation_id,
                change_ref_id=change_ref.id,
                contribution_type="merged",
            ))
        
        # git-push to PR branch handled separately (need to match branch to PR)
    
    return contributions
```

**Verification Instructions**:
```bash
# 1. Sync conversations that include PR activity
ohtv sync -n 50

# 2. Check change_refs were created
sqlite3 ~/.ohtv/index.db "SELECT cr.*, r.fqn FROM change_refs cr JOIN repositories r ON cr.repo_id = r.id WHERE change_type = 'pr';"

# 3. Check conversation_contributions links
sqlite3 ~/.ohtv/index.db "
SELECT 
    cc.conversation_id,
    cc.contribution_type,
    cr.pr_number,
    r.fqn as repo
FROM conversation_contributions cc
JOIN change_refs cr ON cc.change_ref_id = cr.id
JOIN repositories r ON cr.repo_id = r.id
LIMIT 20;
"

# 4. Verify a specific PR has correct contributors
# Find a PR number from above, then check which conversations contributed:
sqlite3 ~/.ohtv/index.db "
SELECT cc.conversation_id, cc.contribution_type
FROM conversation_contributions cc
JOIN change_refs cr ON cc.change_ref_id = cr.id
WHERE cr.pr_number = <PR_NUMBER>;
"

# 5. Cross-reference with ohtv show to verify
ohtv show <conversation_id>
# Confirm it shows open-pr or merge-pr action for that PR
```

**Test Requirements**:
- Unit test: Detects open-pr action and creates contribution
- Unit test: Detects merge-pr action and creates contribution
- Unit test: Same PR from multiple conversations creates one change_ref, multiple contributions
- Unit test: Handles missing metadata gracefully
- Integration test: End-to-end with real synced data

**Dependencies**: Issue 1 (schema), requires existing `actions` stage data

---

## Issue 4: Direct Push to Main Detection

**Summary**: Detect direct pushes to main/master branch (not via PR).

**Description**:
Analyze `git-push` actions where the target branch is main or master. Extract commit range from the push output and create `change_refs` entries with `change_type="direct_push"`.

**Files to Modify**:
- `src/ohtv/db/stages/contributions.py` (extend)
- `src/ohtv/recognizers/git_operations.py` (may need to extract commit range)

**Acceptance Criteria**:
1. Detects git-push actions to main/master branches
2. Extracts commit range from push output (e.g., "418680a..6ecae71")
3. Creates change_ref with change_type="direct_push", status="merged" (already landed)
4. Stores commit_range and branch fields
5. Does not duplicate change_refs for same commit range
6. Links to repository correctly

**Commit Range Extraction**:
```python
import re

# Pattern: "418680a..6ecae71  main -> main"
PUSH_RANGE_PATTERN = re.compile(
    r'([a-f0-9]{7,40})\.\.([a-f0-9]{7,40})\s+(\S+)\s+->\s+(\S+)'
)

def extract_push_info(terminal_output: str) -> dict | None:
    """Extract commit range and branch from git push output."""
    match = PUSH_RANGE_PATTERN.search(terminal_output)
    if match:
        return {
            "base_commit": match.group(1),
            "head_commit": match.group(2),
            "local_branch": match.group(3),
            "remote_branch": match.group(4),
            "commit_range": f"{match.group(1)}..{match.group(2)}",
        }
    return None
```

**Verification Instructions**:
```bash
# 1. Sync conversations with direct pushes to main
ohtv sync -n 50

# 2. Check for direct_push change_refs
sqlite3 ~/.ohtv/index.db "
SELECT cr.*, r.fqn 
FROM change_refs cr 
JOIN repositories r ON cr.repo_id = r.id 
WHERE change_type = 'direct_push';
"

# 3. Verify commit_range is populated
sqlite3 ~/.ohtv/index.db "
SELECT commit_range, branch, status 
FROM change_refs 
WHERE change_type = 'direct_push' AND commit_range IS NOT NULL;
"

# 4. Cross-reference with conversation
# Pick a conversation_id from conversation_contributions for a direct_push
ohtv show <conversation_id>
# Verify it shows a git push to main in the actions
```

**Test Requirements**:
- Unit test: `extract_push_info` parses various push output formats
- Unit test: Correctly identifies main/master as target branches
- Unit test: Ignores pushes to feature branches
- Unit test: Handles force pushes (different output format)
- Integration test: Creates change_refs for direct pushes

**Dependencies**: Issue 1 (schema), Issue 3 (contributions stage structure)

---

## Issue 5: GitHub API LOC Fetching

**Summary**: Fetch lines added/removed from GitHub API for merged PRs and direct pushes.

**Description**:
Create a new CLI command `ohtv fetch-loc` that:
1. Finds change_refs where LOC data is missing
2. Calls GitHub API to get additions/deletions
3. Updates change_refs with LOC data and merged status
4. Caches results (only fetches once unless --force)

**Files to Create/Modify**:
- `src/ohtv/commands/fetch_loc.py` (new)
- `src/ohtv/github_client.py` (new, minimal GitHub API client)
- `src/ohtv/cli.py` (register command)

**Acceptance Criteria**:
1. Command fetches LOC for PRs via `GET /repos/{owner}/{repo}/pulls/{number}`
2. Command fetches LOC for direct pushes via `GET /repos/{owner}/{repo}/compare/{base}...{head}`
3. Updates change_refs with: lines_added, lines_removed, files_changed, fetched_at
4. For PRs: also updates status (merged/open/closed) and merged_at
5. Respects GitHub rate limits (shows warning when approaching limit)
6. Skips already-fetched entries unless --force flag
7. Requires GITHUB_TOKEN environment variable
8. Shows progress during fetch
9. Handles API errors gracefully (404 for deleted PRs, etc.)

**CLI Interface**:
```bash
ohtv fetch-loc                    # Fetch all pending
ohtv fetch-loc --repo owner/repo  # Filter by repo
ohtv fetch-loc --force            # Re-fetch even if cached
ohtv fetch-loc --dry-run          # Show what would be fetched
```

**Verification Instructions**:
```bash
# 1. Ensure GITHUB_TOKEN is set
echo $GITHUB_TOKEN

# 2. Check pending change_refs
sqlite3 ~/.ohtv/index.db "SELECT COUNT(*) FROM change_refs WHERE fetched_at IS NULL;"

# 3. Run fetch (dry-run first)
ohtv fetch-loc --dry-run

# 4. Run actual fetch
ohtv fetch-loc

# 5. Verify LOC data populated
sqlite3 ~/.ohtv/index.db "
SELECT pr_number, status, lines_added, lines_removed, files_changed, fetched_at
FROM change_refs
WHERE lines_added IS NOT NULL
LIMIT 10;
"

# 6. Verify merged PRs have merged_at
sqlite3 ~/.ohtv/index.db "
SELECT pr_number, status, merged_at 
FROM change_refs 
WHERE status = 'merged';
"

# 7. Test --force re-fetches
ohtv fetch-loc --force --repo <some-repo>
# Verify fetched_at timestamp updated

# 8. Test with invalid token (should error gracefully)
GITHUB_TOKEN=invalid ohtv fetch-loc
# Expected: Authentication error message
```

**Test Requirements**:
- Unit test: GitHub client parses PR response correctly
- Unit test: GitHub client parses compare response correctly
- Unit test: Handles 404 (deleted PR) gracefully
- Unit test: Handles rate limit response
- Integration test: Mock GitHub API responses
- Integration test: Updates database correctly

**Dependencies**: Issue 1 (schema), Issue 3 or 4 (change_refs populated)

---

## Issue 6: Velocity Report Command

**Summary**: Generate weekly velocity report showing PRs, LOC, and human input metrics.

**Description**:
Create `ohtv report velocity` command that aggregates data by week and outputs a formatted table or CSV.

**Files to Create/Modify**:
- `src/ohtv/commands/report.py` (new)
- `src/ohtv/cli.py` (register command)

**Acceptance Criteria**:
1. Aggregates merged PRs by week (using merged_at)
2. Shows: week, pr_count, lines_added, lines_removed, human_words, human_messages
3. Calculates derived metrics: total_loc, words_per_loc ratio
4. Supports --format table (default) and --format csv
5. Supports --repo filter
6. Supports --since and --until date filters
7. Handles weeks with no data (shows zeros or skips)
8. CSV output includes header row

**CLI Interface**:
```bash
ohtv report velocity                      # All time, table format
ohtv report velocity --format csv         # CSV for charting
ohtv report velocity --since 2024-01-01   # Filter by date
ohtv report velocity --repo owner/repo    # Filter by repo
```

**Expected Output (table)**:
```
Week        PRs   +Lines   -Lines   Words   Msgs   Words/LOC
────────────────────────────────────────────────────────────
2024-W10      3      450      120     340      8       0.60
2024-W11      5      890      230     125      3       0.11
2024-W12      8     1240      180      45      2       0.03
────────────────────────────────────────────────────────────
Total        16     2580      530     510     13       0.16
```

**Expected Output (CSV)**:
```csv
week,prs_merged,lines_added,lines_removed,total_loc,human_words,human_messages,words_per_loc
2024-W10,3,450,120,570,340,8,0.60
2024-W11,5,890,230,1120,125,3,0.11
2024-W12,8,1240,180,1420,45,2,0.03
```

**SQL Query**:
```sql
SELECT 
    strftime('%Y-W%W', cr.merged_at) AS week,
    COUNT(DISTINCT cr.id) AS prs_merged,
    SUM(cr.lines_added) AS lines_added,
    SUM(cr.lines_removed) AS lines_removed,
    SUM(chi.human_word_count) AS human_words,
    SUM(chi.human_message_count) AS human_messages
FROM change_refs cr
JOIN conversation_contributions cc ON cr.id = cc.change_ref_id
JOIN conversation_human_input chi ON cc.conversation_id = chi.conversation_id
WHERE cr.status = 'merged'
GROUP BY week
ORDER BY week;
```

**Verification Instructions**:
```bash
# 1. Ensure data is populated
ohtv fetch-loc

# 2. Run report
ohtv report velocity

# 3. Verify numbers make sense
# Cross-check a week's PR count:
sqlite3 ~/.ohtv/index.db "
SELECT COUNT(*) FROM change_refs 
WHERE status = 'merged' 
AND strftime('%Y-W%W', merged_at) = '2024-W10';
"

# 4. Test CSV output
ohtv report velocity --format csv > velocity.csv
head velocity.csv
# Verify header row and data format

# 5. Test filters
ohtv report velocity --repo jpshackelford/voice-relay
ohtv report velocity --since 2024-05-01
```

**Test Requirements**:
- Unit test: Weekly aggregation logic
- Unit test: Words per LOC calculation (handles division by zero)
- Unit test: CSV format output
- Unit test: Date filtering
- Integration test: Full report with sample data

**Dependencies**: Issues 1-5 (all data must be populated)

---

## Issue 7: Charting Script

**Summary**: Python script to generate publication-quality charts from CSV export.

**Description**:
Create a standalone script that reads the velocity CSV and generates PNG/SVG charts suitable for papers/presentations.

**Files to Create**:
- `scripts/chart_velocity.py`
- `scripts/requirements-charts.txt` (matplotlib, pandas)

**Acceptance Criteria**:
1. Reads CSV from stdin or file argument
2. Generates multi-panel figure:
   - Panel 1: PRs merged per week (bar chart)
   - Panel 2: LOC per week (stacked bar: added/removed)
   - Panel 3: Human words per LOC ratio (line chart)
3. Supports --output flag for filename (default: velocity.png)
4. Supports --format flag (png, svg, pdf)
5. Supports --mark-date flag to add vertical line (e.g., orchestration start date)
6. Publication quality: clear labels, legend, appropriate fonts

**CLI Interface**:
```bash
# Basic usage
ohtv report velocity --format csv | python scripts/chart_velocity.py

# With options
python scripts/chart_velocity.py velocity.csv \
    --output figures/velocity.png \
    --format png \
    --mark-date 2024-03-01 \
    --title "Development Velocity Before/After Orchestration"
```

**Verification Instructions**:
```bash
# 1. Generate CSV
ohtv report velocity --format csv > velocity.csv

# 2. Install chart dependencies
pip install -r scripts/requirements-charts.txt

# 3. Generate chart
python scripts/chart_velocity.py velocity.csv --output velocity.png

# 4. View chart
# Open velocity.png in image viewer

# 5. Test with mark date
python scripts/chart_velocity.py velocity.csv \
    --output velocity_marked.png \
    --mark-date 2024-05-01

# 6. Test SVG output
python scripts/chart_velocity.py velocity.csv \
    --output velocity.svg \
    --format svg
```

**Test Requirements**:
- Unit test: CSV parsing handles edge cases
- Unit test: Date marking calculates correct position
- Manual test: Visual inspection of output charts

**Dependencies**: Issue 6 (CSV export)

---

## Issue 8: Conversation Classification Command

**Summary**: CLI command to classify conversations by initial prompt source (human vs automation).

**Description**:
Create `ohtv classify` command that allows:
1. Setting `initial_prompt_source` for individual conversations
2. Bulk classification based on heuristics
3. Listing conversations that need classification

This is necessary because the trace data doesn't distinguish human-initiated from automation-initiated conversations. Manual or heuristic-based classification is required for accurate human input metrics.

**Files to Create/Modify**:
- `src/ohtv/commands/classify.py` (new)
- `src/ohtv/cli.py` (register command)

**Acceptance Criteria**:
1. Can set source for a single conversation by ID
2. Can bulk classify using heuristics:
   - `--no-followups` → conversations with 0 follow-up messages
   - `--has-followups` → conversations with 1+ follow-up messages
   - `--repo` → filter by repository
3. Can list conversations with `initial_prompt_source = 'unknown'`
4. Shows count of affected conversations before applying bulk changes
5. Requires `--confirm` flag for bulk operations (safety)
6. Updates trigger recomputation flag so reports know to refresh

**CLI Interface**:
```bash
# Set source for a single conversation
ohtv classify <conversation_id> --source human
ohtv classify <conversation_id> --source automation

# List conversations needing classification
ohtv classify --list-unknown
ohtv classify --list-unknown --repo owner/repo

# Bulk classify with heuristics
ohtv classify --no-followups --source automation --confirm
ohtv classify --has-followups --source human --confirm

# Preview bulk changes (no --confirm)
ohtv classify --no-followups --source automation
# Output: "Would classify 47 conversations as 'automation'. Add --confirm to apply."

# Bulk classify for specific repo
ohtv classify --repo owner/repo --no-followups --source automation --confirm
```

**Heuristics Rationale**:
- **No follow-ups** → Likely orchestrator worker (automation ran to completion without human intervention)
- **Has follow-ups** → Likely human-initiated (human provided steering during execution)

These are imperfect heuristics but provide a reasonable starting point. Users can manually override individual conversations.

**Verification Instructions**:
```bash
# 1. Sync and process conversations
ohtv sync -n 50

# 2. Check initial state (all should be 'unknown')
sqlite3 ~/.ohtv/index.db "SELECT initial_prompt_source, COUNT(*) FROM conversation_human_input GROUP BY initial_prompt_source;"

# 3. List unknown conversations
ohtv classify --list-unknown

# 4. Preview bulk classification
ohtv classify --no-followups --source automation
# Should show count, not apply changes

# 5. Apply bulk classification
ohtv classify --no-followups --source automation --confirm

# 6. Verify changes
sqlite3 ~/.ohtv/index.db "SELECT initial_prompt_source, COUNT(*) FROM conversation_human_input GROUP BY initial_prompt_source;"

# 7. Manually classify one as human
ohtv classify <conversation_id> --source human

# 8. Verify individual change
sqlite3 ~/.ohtv/index.db "SELECT initial_prompt_source FROM conversation_human_input WHERE conversation_id = '<id>';"
```

**Test Requirements**:
- Unit test: Single conversation classification
- Unit test: Bulk classification with --no-followups filter
- Unit test: Bulk classification requires --confirm
- Unit test: --list-unknown output format
- Integration test: Classification persists in database

**Dependencies**: Issue 1 (schema), Issue 2 (human_input data populated)

---

## Implementation Order

```
Issue 1: Schema
    ↓
Issue 2: Human Input ──────────────┐
    ↓                              │
Issue 3: PR Contributions          │
    ↓                              │
Issue 4: Direct Push Detection     │
    ↓                              │
Issue 5: GitHub API Fetch          │
    ↓                              │
Issue 6: Report Command ←──────────┘
    ↓                              │
Issue 7: Charting Script           │
                                   │
Issue 8: Classification Command ←──┘
```

Issues 2, 3, and 4 can be worked in parallel after Issue 1.
Issue 5 requires at least one of Issues 3 or 4.
Issue 6 requires all data issues (1-5).
Issue 7 only requires Issue 6.
Issue 8 can start after Issue 2.

---

## Notes for Implementers

1. **Use existing patterns**: Follow the existing stage/store patterns in ohtv
2. **Error handling**: All stages should handle malformed data gracefully
3. **Logging**: Use appropriate log levels (debug for details, info for progress)
4. **Tests first**: Write tests before implementation where possible
5. **Small PRs**: Each issue should be one PR, don't combine issues
