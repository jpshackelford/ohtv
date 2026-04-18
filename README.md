# ohtv - OpenHands Trajectory Viewer

CLI tool for viewing and syncing OpenHands conversation histories from both local CLI sessions and OpenHands Cloud.

## Installation

```bash
uv pip install -e .
# or
pip install -e .
```

## Quick Start

```bash
# List recent conversations
ohtv list

# View a conversation's messages
ohtv show <conversation_id> --messages

# Analyze user objectives (requires LLM_API_KEY)
ohtv gen objs <conversation_id>
ohtv gen objs <conversation_id> -v detailed_assess  # with completion status

# Summarize today's conversations (requires LLM_API_KEY)
ohtv gen objs --day

# See what GitHub repos/PRs/issues were referenced
ohtv refs <conversation_id>

# Sync cloud conversations (requires OH_API_KEY)
ohtv sync

# Customize prompts
ohtv prompts init              # Copy prompts to ~/.ohtv/prompts/
ohtv prompts show brief        # View a prompt
```

## Commands

### `ohtv list` - List Conversations

Lists conversations from both local CLI history and synced cloud conversations, sorted by most recent first.

```bash
# Show 10 most recent (default)
ohtv list

# Show all conversations
ohtv list --all

# Show 20 most recent
ohtv list -n 20

# Show oldest first
ohtv list --reverse

# Skip first 5, show next 10
ohtv list -k 5

# Include conversations with no events
ohtv list --include-empty

# Output as JSON or CSV
ohtv list -F json
ohtv list -F csv -o conversations.csv

# Filter by date range
ohtv list --since 2024-01-01
ohtv list --until 2024-06-30
ohtv list --since 2024-01-01 --until 2024-03-31

# Show today's conversations
ohtv list --day

# Show conversations from a specific day
ohtv list --day 2024-03-15

# Show this week's conversations (weeks start Sunday)
ohtv list --week

# Show conversations from a specific week
ohtv list --week 2024-03-15

# Filter by PR (requires indexed database)
ohtv list --pr OpenPaw#17           # Short name
ohtv list --pr owner/repo#123       # Fully qualified
ohtv list --pr https://github.com/owner/repo/pull/123  # URL

# Filter by repository
ohtv list --repo OpenPaw            # Partial match (any repo containing "OpenPaw")
ohtv list --repo owner/repo         # Fully qualified
ohtv list --repo https://github.com/owner/repo  # URL

# Filter by action type (requires indexed database)
ohtv list --action pushed           # Conversations that pushed to any repo
ohtv list --action open-pr          # Conversations that opened PRs

# Combine action + repo for precise filtering
ohtv list --action pushed --repo OpenPaw  # Pushed specifically to OpenPaw
```

**Options:**
| Flag | Description |
|------|-------------|
| `-n, --max N` | Maximum conversations to show (default: 10) |
| `-A, --all` | Show all conversations (no limit) |
| `-k, --offset N` | Skip first N conversations |
| `-r, --reverse` | Show oldest first |
| `-e, --include-empty` | Include conversations with no events |
| `-F, --format` | Output format: `table`, `json`, `csv` |
| `-o, --output FILE` | Write output to file |
| `-S, --since DATE` | Show conversations from DATE onwards |
| `-U, --until DATE` | Show conversations up to DATE |
| `-D, --day [DATE]` | Show conversations from a single day (default: today) |
| `-W, --week [DATE]` | Show conversations from the week containing DATE (default: today, weeks start Sunday) |
| `--pr PATTERN` | Filter by PR reference (URL, `owner/repo#N`, or `repo#N`) |
| `--repo PATTERN` | Filter by repository (URL, `owner/repo`, or name) |
| `--action TYPE` | Filter by action type (e.g., `pushed`, `open-pr`, `git-commit`) |
| `-E, --with-errors` | Include error info column (agent/LLM errors) |
| `--errors-only` | Show only conversations with agent/LLM errors |
| `-v, --verbose` | Show debug output |

**Action Type Aliases:**

| Alias | Action Type |
|-------|-------------|
| `pushed`, `push` | `git-push` |
| `committed`, `commit` | `git-commit` |
| `opened-pr`, `create-pr` | `open-pr` |
| `merged`, `merge` | `merge-pr` |
| `ci`, `checks` | `check-ci` |

**Note:** PR, repo, and action filters require the database to be indexed. Run `ohtv db scan && ohtv db process all` first.

---

### `ohtv show` - View Conversation Content

Displays a conversation's statistics and optionally its content (messages, actions, outputs).

```bash
# Show statistics only (default)
ohtv show abc123

# Show user and agent messages
ohtv show abc123 --messages
ohtv show abc123 -m

# Show everything
ohtv show abc123 --all

# Show messages with timestamps
ohtv show abc123 -m -T

# Show action summaries with truncated outputs
ohtv show abc123 -s -o

# Show action details (human-readable: shows shell commands, file paths, etc.)
ohtv show abc123 -s -d

# Show full outputs (no truncation)
ohtv show abc123 -s -O

# Debug mode: show raw tool_call JSON and observation metadata
ohtv show abc123 -s -d -o --debug-tool-call

# Show thinking/reasoning blocks
ohtv show abc123 -t

# Show user messages with thinking
ohtv show abc123 -u -t

# Include git refs summary at end
ohtv show abc123 -m -R

# Output as JSON
ohtv show abc123 -A -F json --file conversation.json

# Show only last 5 events, newest first
ohtv show abc123 -A -r -n 5
```

**Content Flags:**
| Flag | Description |
|------|-------------|
| `-u, --user-messages` | Include user's messages |
| `-a, --agent-messages` | Include agent's response messages |
| `-f, --finish` | Include finish action message |
| `-s, --action-summaries` | Include brief tool call summaries |
| `-d, --action-details` | Include human-readable tool call details (e.g., `$ git status` for terminal) |
| `-o, --trunc-output` | Include tool outputs (truncated to 2000 chars) with exit codes |
| `-O, --full-output` | Include full tool outputs (no truncation) with exit codes |
| `--debug-tool-call` | Include raw tool_call JSON and observation metadata (working dir, etc.) |
| `-t, --thinking` | Show thinking/reasoning blocks (think actions) |
| `-T, --timestamps` | Include timestamps on events |
| `-R, --refs` | Show git refs with write actions at end |
| `-X, --actions` | Show recognized actions from the database |

**Shorthand Flags:**
| Flag | Equivalent to |
|------|---------------|
| `-m, --messages` | `-u -a -f` (user + agent + finish) |
| `-A, --all` | All content flags enabled (including `--full-output` and `--debug-tool-call`) |
| `-S, --stats` | Statistics only, no content |

**Display Options:**
| Flag | Description |
|------|-------------|
| `-r, --reverse` | Show newest events first |
| `-n, --max N` | Maximum number of events to show |
| `-k, --offset N` | Skip first N events |
| `-F, --format` | Output format: `text` (default), `markdown`, `json` |
| `--file PATH` | Write output to file |

---

### `ohtv refs` - Extract Git References

Extracts and displays repository, issue, and PR/MR references from one or more conversations. Supports both single-conversation mode (rich display) and multi-conversation mode (aggregated output for automation).

**Single Conversation Mode:**
```bash
# Show all references with interaction annotations
ohtv refs abc123

# Show only refs where write actions were detected (pushed, created, etc.)
ohtv refs abc123 --write-only

# Show refs with any detected interactions (including read actions like cloned)
ohtv refs abc123 --actions

# Output just PR URLs, one per line (for piping)
ohtv refs abc123 --prs-only -1

# Output as JSON
ohtv refs abc123 --format json

# Skip database indexing (faster for one-off lookups)
ohtv refs abc123 --no-index
```

**Multi-Conversation Mode (requires at least one filter):**
```bash
# All PRs from today's conversations, one per line
ohtv refs -D --prs-only -1

# All repos touched this week (with write actions)
ohtv refs -W --repos-only --write-only -1

# All refs from conversations that touched a specific PR
ohtv refs --pr owner/repo#42 -1

# Refs with any interactions from today, comma-separated
ohtv refs -D --actions --format csv

# All refs from today as JSON
ohtv refs -D --format json
```

**Output Formats:**
| Format | Description |
|--------|-------------|
| `table` | Rich formatted display (default) |
| `lines` | One URL per line (for piping) |
| `csv` | Comma-separated URLs |
| `json` | JSON object with refs by type |

**Detected Interactions:**

| Type | Write Actions | Read Actions |
|------|--------------|--------------|
| Repositories | `pushed`, `committed` | `cloned` |
| Pull Requests | `created`, `pushed`, `commented`, `merged`, `closed`, `reviewed` | `viewed` |
| Issues | `created`, `commented`, `closed` | `viewed` |

**Options:**
| Flag | Description |
|------|-------------|
| `-n, --max N` | Maximum conversations to process |
| `-A, --all` | Process all matching conversations (no limit) |
| `-k, --offset N` | Skip first N conversations |
| `-S, --since DATE` | Process conversations from DATE onwards |
| `-U, --until DATE` | Process conversations up to DATE |
| `-D, --day [DATE]` | Process conversations from a single day (default: today) |
| `-W, --week [DATE]` | Process conversations from the week containing DATE |
| `--pr PATTERN` | Filter by PR reference |
| `--repo PATTERN` | Filter by repository |
| `--action TYPE` | Filter by action type |
| `--reverse` | Show oldest first |
| `--prs-only` | Output only PR/MR references |
| `--repos-only` | Output only repository references |
| `--issues-only` | Output only issue references |
| `-F, --format` | Output format: `table`, `lines`, `csv`, `json` |
| `-1` | Shorthand for `--format lines` |
| `-a, --actions` | Show only refs with detected interactions (read or write) |
| `-w, --write-only` | Show only refs with write actions (pushed, created, etc.) |
| `--no-index` | Skip database indexing |
| `-v, --verbose` | Show debug output |

---

### `ohtv errors` - Show Agent/LLM Error Summary

Analyzes a conversation for agent and LLM errors that impacted agent behavior. This includes:

- **ConversationErrorEvent**: Terminal errors that stop the conversation (LLM errors, budget exceeded, API failures)
- **AgentErrorEvent**: Agent-level errors (sandbox restarts, tool validation failures)

Note: This does NOT track routine terminal command failures (non-zero exit codes), which are normal during development.

```bash
# Show error summary for a conversation
ohtv errors abc123

# Output as JSON (for automation)
ohtv errors abc123 --format json
```

**Example Output:**
```
Error Summary for 03465880-dbe...
please clone https://github.com/...

Overview: 1 error(s) TERMINAL
Execution status: error

Terminal Error(s):
  [9] 2026-04-14 13:37:49 ConversationError
       Code: LLMBadRequestError
       Detail: litellm.BadRequestError: Error code: 400 - ...
```

**Options:**
| Flag | Description |
|------|-------------|
| `-F, --format` | Output format: `text` (default), `json` |
| `-v, --verbose` | Show debug output |

**Error Filtering in `list` Command:**

You can also filter conversations by error status:

```bash
# Show only conversations with agent/LLM errors
ohtv list --errors-only

# Include error column in regular listing
ohtv list -E  # or --with-errors

# Combine with other filters
ohtv list --errors-only --day
ohtv list --errors-only --week
```

---

### `ohtv gen` - LLM Generation Commands

The `gen` command provides LLM-powered analysis of conversations using customizable prompts. Currently supports `objs` analysis with multiple variants and context levels.

#### `ohtv gen objs` - Extract User Objectives

Analyzes conversations to extract user objectives. Supports single-conversation and multi-conversation (batch) modes, with multiple output variants and context levels for balancing detail vs. token cost.

```bash
# SINGLE-CONVERSATION MODE (with conversation_id)

# Basic analysis (uses default: brief variant, standard context)
ohtv gen objs abc123

# Choose output detail level with variants
ohtv gen objs abc123 -v brief          # 1-2 sentence goal
ohtv gen objs abc123 -v standard       # Goal + primary/secondary outcomes
ohtv gen objs abc123 -v detailed       # Full hierarchical objectives

# Add completion assessment to any variant
ohtv gen objs abc123 -v brief_assess   # Goal + achieved/in_progress/not_achieved
ohtv gen objs abc123 -v standard_assess
ohtv gen objs abc123 -v detailed_assess

# Control how much conversation context is analyzed
ohtv gen objs abc123 -c 1              # Minimal: user messages only (fastest)
ohtv gen objs abc123 -c 2              # Default: user messages + finish action
ohtv gen objs abc123 -c 3              # Full: all messages + action summaries

# Context levels also accept names
ohtv gen objs abc123 -c minimal
ohtv gen objs abc123 -c default
ohtv gen objs abc123 -c full

# Force re-analysis (ignore cache)
ohtv gen objs abc123 --no-cache

# Use a specific model
ohtv gen objs abc123 -m gpt-4o

# Output as JSON
ohtv gen objs abc123 --json

# MULTI-CONVERSATION MODE (without conversation_id)

# Analyze 10 most recent conversations (default)
ohtv gen objs

# Analyze today's conversations
ohtv gen objs --day

# Analyze this week's conversations
ohtv gen objs --week

# Analyze with date range
ohtv gen objs --since 2024-01-01 --until 2024-01-31

# Analyze all conversations (no limit)
ohtv gen objs --all

# Force re-analysis (ignore cache)
ohtv gen objs --no-cache

# Output as markdown (for notes/docs)
ohtv gen objs -F markdown

# Output as JSON
ohtv gen objs -F json

# Filter by PR, repo, or action (same as list command)
ohtv gen objs --pr OpenPaw#17
ohtv gen objs --repo OpenPaw
ohtv gen objs --action pushed --repo OpenPaw

# Skip confirmation for large result sets
ohtv gen objs --action pushed --yes
```

**Variants:**

| Variant | Description |
|---------|-------------|
| `brief` | 1-2 sentence goal description (default) |
| `brief_assess` | Goal + completion status |
| `standard` | Goal + primary/secondary outcomes |
| `standard_assess` | Standard + completion assessment |
| `detailed` | Full hierarchical objectives with subordinate goals |
| `detailed_assess` | Detailed + completion assessment for each objective |

**Context Levels:**

| Level | Name | Includes | Use When |
|-------|------|----------|----------|
| 1 | `minimal` | User messages only | Quick summaries, low token cost |
| 2 | `default` | User messages + finish action | Balanced (default) |
| 3 | `full` | All messages + action summaries | Need to assess what was actually done |

**Example Output (brief):**
```
Goal: Refactor the authentication module to use OAuth2 with refresh token support.

Outputs:
  pushed user/repo
  created user/repo/pull/42
```

**Example Output (detailed_assess):**
```
👷 Refactor Authentication Module
abc123def456

Summary: User wanted to modernize the authentication system...

Objectives:
Primary Objectives
└── ✓ Refactor authentication to use OAuth2 [Achieved]
       Evidence: Implemented OAuth2 client in auth.py...
    ├── ✓ Add OAuth2 client configuration [Achieved]
    ├── → Update user session handling [In Progress]
    └── ✗ Add refresh token support [Not Achieved]

Analyzed: 2024-03-15 14:30 UTC • Model: claude-sonnet-4 • Context: full

Outputs:
  pushed user/repo
  created user/repo/pull/42

LLM cost: $0.0089
```

**Multi-Conversation Example Output (table):**
```
┏━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ID      ┃ Date       ┃ Summary                                             ┃
┡━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ abc1234 │ 2024-03-15 │ Refactor authentication module to use OAuth2 with   │
│         │            │ refresh token support for improved security.        │
│         │            │ → created user/repo/pull/42, pushed user/repo       │
├─────────┼────────────┼─────────────────────────────────────────────────────┤
│ def5678 │ 2024-03-14 │ Fix pagination bug in search results component that │
│         │            │ caused duplicate entries on page boundaries.        │
└─────────┴────────────┴─────────────────────────────────────────────────────┘
Showing 2 of 150 (2/2 cached)
```

**Options (Single-Conversation Mode):**
| Flag | Description |
|------|-------------|
| `-v, --variant` | Output variant (default: `brief`) |
| `-c, --context` | Context level: 1-3 or name (default: from prompt) |
| `--no-cache` | Force re-analysis (ignore cache) |
| `-m, --model` | LLM model to use |
| `--json` | Output as JSON |
| `--no-outputs` | Don't show outputs (repos, PRs, issues) |
| `--verbose` | Show debug output |

**Options (Multi-Conversation Mode):**
| Flag | Description |
|------|-------------|
| `-v, --variant` | Output variant (default: `brief`) |
| `-c, --context` | Context level (default: `minimal` for token efficiency) |
| `-n, --max N` | Maximum conversations to analyze (default: 10) |
| `-A, --all` | Analyze all conversations (no limit) |
| `-k, --offset N` | Skip first N conversations |
| `-S, --since DATE` | Analyze conversations from DATE onwards |
| `-U, --until DATE` | Analyze conversations up to DATE |
| `-D, --day [DATE]` | Analyze conversations from a single day (default: today) |
| `-W, --week [DATE]` | Analyze conversations from the week containing DATE |
| `--pr PATTERN` | Filter by PR reference (URL, `owner/repo#N`, or `repo#N`) |
| `--repo PATTERN` | Filter by repository (URL, `owner/repo`, or name) |
| `--action TYPE` | Filter by action type (e.g., `pushed`, `open-pr`) |
| `--reverse` | Show oldest first |
| `--no-cache` | Force re-analysis (ignore cache) |
| `-m, --model` | LLM model to use |
| `-F, --format` | Output format: `table`, `json`, `markdown` |
| `--no-outputs` | Don't show outputs (repos, PRs, issues modified) |
| `-y, --yes` | Skip confirmation for large result sets (>20 conversations) |
| `-q, --quiet` | Generate/cache summaries without displaying output |
| `--verbose` | Show debug output |

---

### `ohtv prompts` - Manage Analysis Prompts

View and customize the LLM prompts used for analysis. Prompts are organized into families (e.g., `objs`) with variants (e.g., `brief`, `detailed_assess`).

```bash
# List all prompts and their status
ohtv prompts
ohtv prompts list

# Show a specific prompt's content
ohtv prompts show brief
ohtv prompts show objs/detailed_assess

# Copy prompts to ~/.ohtv/prompts/ for customization
ohtv prompts init

# Reset a customized prompt to default
ohtv prompts reset brief
ohtv prompts reset objs/brief

# Reset all prompts to defaults
ohtv prompts reset --all
```

**Example Output (list):**
```
Prompt Families:

  code_review/
    default               (default) Analyze code changes made during the conversation

  objs/
    brief                 (default) Extract user goal in 1-2 sentences
    brief_assess                    Extract user goal and assess completion status
    detailed                        Extract hierarchical objectives with subordinate goals
    detailed_assess                 Extract hierarchical objectives and assess completion status
    standard                        Extract primary and secondary outcomes
    standard_assess                 Extract primary and secondary outcomes and assess completion

User prompts directory: ~/.ohtv/prompts
Run 'ohtv prompts init' to copy prompts for customization.
```

**Customizing Prompts:**

1. Run `ohtv prompts init` to copy default prompts to `~/.ohtv/prompts/`
2. Edit the prompt files (they use YAML frontmatter + Markdown body)
3. Your changes take effect immediately (cache is invalidated automatically)
4. Use `ohtv prompts reset <name>` to restore a prompt to default

**Prompt File Structure:**
```yaml
---
id: objs.brief
description: Extract user goal in 1-2 sentences
default: true

context:
  default: 1
  levels:
    1:
      name: minimal
      include:
        - source: user
          kind: MessageEvent
      truncate: 500
    2:
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent

output:
  schema:
    goal: string
---
Your prompt instructions here...

Respond with JSON:
{"goal": "1-2 sentence description"}
```

**Options:**
| Flag | Description |
|------|-------------|
| `--all` | Reset all prompts (with `reset` action) |

---

### `ohtv sync` - Sync Cloud Conversations

Downloads conversations from OpenHands Cloud. Requires `OH_API_KEY` environment variable.

```bash
# Sync incrementally (only downloads changes)
ohtv sync

# Sync and run all processing stages (recommended)
ohtv sync --process

# Force re-download everything
ohtv sync --force

# Only sync conversations updated after a date
ohtv sync --since 2024-01-01

# Preview what would sync
ohtv sync --dry-run

# Check sync status
ohtv sync --status

# Quiet mode (for cron jobs)
ohtv sync --quiet
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Re-download all conversations |
| `--since DATE` | Only sync conversations updated after date |
| `--dry-run` | Show what would sync without downloading |
| `-s, --status` | Show sync status |
| `-p, --process` | Run all processing stages after sync |
| `-q, --quiet` | Minimal output for cron jobs |

---

### `ohtv db` - Database Management

Manages the SQLite index database that tracks conversations and their relationships to repositories, issues, and PRs. The database enables fast lookups and future aggregate queries.

See [docs/DATABASE.md](docs/DATABASE.md) for detailed documentation.

#### `ohtv db init` - Initialize Database

Creates or migrates the database schema.

```bash
ohtv db init
```

#### `ohtv db scan` - Register Conversations

Scans the filesystem and registers conversations in the database. Uses modification time for fast change detection.

```bash
# Scan and register new/changed conversations
ohtv db scan

# Force update all conversations (after backup restore)
ohtv db scan --force

# Remove entries for deleted conversations
ohtv db scan --remove-missing

# Verbose output
ohtv db scan -v
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Update all conversations regardless of mtime |
| `--remove-missing` | Remove DB entries for conversations no longer on disk |
| `-v, --verbose` | Show detailed output |

#### `ohtv db process` - Run Processing Stages

Runs processing stages on registered conversations. Each stage extracts specific data and stores it in the database.

```bash
# Process refs (repos, issues, PRs) for all pending conversations
ohtv db process refs

# Process actions (file edits, git ops, PRs, etc.)
ohtv db process actions

# Run all stages in sequence
ohtv db process all

# Force reprocess all conversations
ohtv db process refs --force

# Process a specific conversation
ohtv db process refs --conversation abc123

# Verbose output
ohtv db process refs -v
```

**Available Stages:**
| Stage | Description |
|-------|-------------|
| `refs` | Extract repository, issue, and PR references |
| `actions` | Recognize actions (file edits, git ops, PRs, issues, Notion, etc.) |
| `all` | Run all stages in sequence |

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Reprocess all conversations |
| `-c, --conversation ID` | Process only this conversation |
| `-v, --verbose` | Show detailed output |

#### `ohtv db reset` - Delete Database

Deletes the database to start fresh. Source conversation files are NOT affected.

```bash
# Delete with confirmation prompt
ohtv db reset

# Delete without confirmation
ohtv db reset --yes
```

**Options:**
| Flag | Description |
|------|-------------|
| `-y, --yes` | Skip confirmation prompt |

#### `ohtv db status` - Show Database Status

Displays database statistics.

```bash
ohtv db status
```

**Example Output:**
```
Database: /Users/you/.ohtv/index.db
Size: 6.1 MB

Records:
  Conversations: 1297
  Repositories: 156
  References (issues/PRs): 428
  Repo Links: 892
  Reference Links: 1245
  Actions: 17770

Actions by type:
  edit-code: 5258
  study-code: 4098
  edit-docs: 1840
  git-commit: 1569
  git-push: 1335
  check-ci: 1290
  ...
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OH_API_KEY` | OpenHands Cloud API key | Required for `sync` |
| `OHTV_CLOUD_URL` | Cloud base URL | `https://app.all-hands.dev` |
| `OHTV_DIR` | ohtv data directory (database, logs, cache) | `~/.ohtv` |
| `OHTV_DB_PATH` | Direct path to database file | `~/.ohtv/index.db` |
| `OHTV_CONVERSATIONS_DIR` | Local CLI conversations directory | `~/.openhands/conversations` |
| `OHTV_CLOUD_CONVERSATIONS_DIR` | Synced cloud conversations directory | `~/.openhands/cloud/conversations` |
| `OHTV_EXTRA_CONVERSATION_PATHS` | Additional conversation directories (colon-separated paths) | None |
| `LLM_API_KEY` | API key for LLM provider | Required for `gen` |
| `LLM_MODEL` | Default LLM model | Provider default |
| `LLM_BASE_URL` | Custom LLM base URL | Provider default |
| `LLM_TIMEOUT` | LLM request timeout in seconds | `300` |

## Data Directories

ohtv uses two directory trees:

- **`~/.openhands/`** - OpenHands source data (read-only for ohtv, except `sync`)
  - `conversations/` - Local CLI conversations
  - `cloud/conversations/` - Synced cloud conversations

- **`~/.ohtv/`** - ohtv-generated data (override with `OHTV_DIR`)
  - `index.db` - SQLite database
  - `logs/ohtv.log` - Application logs
  - `sync_manifest.json` - Cloud sync state
  - `prompts/` - User-customized prompts (created by `ohtv prompts init`)

## Logging

Logs are written to `~/.ohtv/logs/ohtv.log`:
- Rotates at 1MB, keeps 3 backups
- Use `-v, --verbose` on any command to also print debug output to console
