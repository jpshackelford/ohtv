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
ohtv objectives <conversation_id>

# Summarize today's conversations (requires LLM_API_KEY)
ohtv summary --day

# See what GitHub repos/PRs/issues were referenced
ohtv refs <conversation_id>

# Sync cloud conversations (requires OH_API_KEY)
ohtv sync
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

# Show only refs where write actions were detected
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

# All repos touched this week
ohtv refs -W --repos-only -1

# All refs from conversations that touched a specific PR
ohtv refs --pr owner/repo#42 -1

# Refs with write actions from today, comma-separated
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
- **Repositories:** `cloned`, `pushed`
- **Pull Requests:** `created`, `pushed`, `commented`, `merged`, `closed`, `reviewed`
- **Issues:** `created`, `commented`, `closed`

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
| `-a, --actions` | Show only refs with write actions |
| `--no-index` | Skip database indexing |
| `-v, --verbose` | Show debug output |

---

### `ohtv objectives` - Analyze User Objectives

Uses an LLM to extract and categorize user objectives from a conversation into a hierarchy of primary and subordinate goals. Results are cached for quick subsequent lookups.

```bash
# Analyze objectives (uses cache if available)
ohtv objectives abc123

# Force re-analysis (ignore cache)
ohtv objectives abc123 --refresh

# Use a specific model
ohtv objectives abc123 --model gpt-4o

# Output as JSON
ohtv objectives abc123 --json
```

**Example Output:**
```
Summary: User wanted to refactor the authentication module...

Objectives:
Primary Objectives
└── ✓ Refactor authentication to use OAuth2 [Achieved]
    ├── ✓ Add OAuth2 client configuration [Achieved]
    ├── ◐ Update user session handling [Partially Achieved]
    └── ✗ Add refresh token support [Not Achieved]
```

**Options:**
| Flag | Description |
|------|-------------|
| `-r, --refresh` | Force re-analysis (ignore cache) |
| `-m, --model` | LLM model to use for analysis |
| `--json` | Output as JSON |

**Environment Variables:**
| Variable | Description |
|----------|-------------|
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_MODEL` | Default model to use (optional) |
| `LLM_BASE_URL` | Custom LLM base URL (optional) |

---

### `ohtv summary` - Summarize Multiple Conversations

Analyzes multiple conversations and displays a summary table of their goals. Uses the most token-efficient LLM settings (minimal context, brief output) and caches results. Shares cache with `objectives` command.

```bash
# Summarize 10 most recent conversations (default)
ohtv summary

# Summarize today's conversations
ohtv summary --day

# Summarize this week's conversations
ohtv summary --week

# Summarize with date range
ohtv summary --since 2024-01-01 --until 2024-01-31

# Summarize all conversations (no limit)
ohtv summary --all

# Force re-analysis (ignore cache)
ohtv summary --refresh

# Output as markdown (for notes/docs)
ohtv summary -F markdown

# Output as JSON
ohtv summary -F json

# Filter by PR, repo, or action (same as list command)
ohtv summary --pr OpenPaw#17
ohtv summary --repo OpenPaw
ohtv summary --action pushed --repo OpenPaw

# Skip confirmation for large result sets
ohtv summary --action pushed --yes
```

**Example Output (table):**
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

**Example Output (markdown):**
```markdown
- **abc1234** (2024-03-15): Refactor authentication to use OAuth2 with refresh tokens
  - created: user/repo/pull/42
  - pushed: user/repo
- **def5678** (2024-03-14): Fix pagination bug in search results component
```

**Options:**
| Flag | Description |
|------|-------------|
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
| `-r, --refresh` | Force re-analysis (ignore cache) |
| `-m, --model` | LLM model to use for analysis |
| `-F, --format` | Output format: `table`, `json`, `markdown` |
| `--no-outputs` | Don't show outputs (repos, PRs, issues modified) |
| `-y, --yes` | Skip confirmation for large result sets (>20 conversations) |
| `-v, --verbose` | Show debug output |

**Environment Variables:**
| Variable | Description |
|----------|-------------|
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_MODEL` | Default model to use (optional) |
| `LLM_BASE_URL` | Custom LLM base URL (optional) |

---

### `ohtv sync` - Sync Cloud Conversations

Downloads conversations from OpenHands Cloud. Requires `OH_API_KEY` environment variable.

```bash
# Sync incrementally (only downloads changes)
ohtv sync

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
| `LLM_API_KEY` | API key for LLM provider | Required for `objectives`, `summary` |
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

## Logging

Logs are written to `~/.ohtv/logs/ohtv.log`:
- Rotates at 1MB, keeps 3 backups
- Use `-v, --verbose` on any command to also print debug output to console
