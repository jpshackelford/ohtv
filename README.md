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
| `-v, --verbose` | Show debug output |

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

Extracts and displays all repository, issue, and PR/MR references found in a conversation, with annotations showing what actions were taken. Automatically indexes the conversation in the database for future queries.

```bash
# Show all references with interaction annotations
ohtv refs abc123

# Show only refs where write actions were detected
ohtv refs abc123 --actions

# Skip database indexing (faster for one-off lookups)
ohtv refs abc123 --no-index
```

**Detected Interactions:**
- **Repositories:** `cloned`, `pushed`
- **Pull Requests:** `created`, `pushed`, `commented`, `merged`, `closed`, `reviewed`
- **Issues:** `created`, `commented`, `closed`

**Options:**
| Flag | Description |
|------|-------------|
| `-a, --actions` | Show only refs with write actions |
| `--no-index` | Skip database indexing |

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
| `--reverse` | Show oldest first |
| `-r, --refresh` | Force re-analysis (ignore cache) |
| `-m, --model` | LLM model to use for analysis |
| `-F, --format` | Output format: `table`, `json`, `markdown` |
| `--no-outputs` | Don't show outputs (repos, PRs, issues modified) |
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

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Reprocess all conversations |
| `-c, --conversation ID` | Process only this conversation |
| `-v, --verbose` | Show detailed output |

#### `ohtv db status` - Show Database Status

Displays database statistics.

```bash
ohtv db status
```

**Example Output:**
```
Database: /Users/you/.ohtv/index.db
Size: 156.2 KB

Records:
  Conversations: 42
  Repositories: 15
  References (issues/PRs): 28
  Repo Links: 52
  Reference Links: 71

References by type:
  issue: 12
  pr: 16
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
