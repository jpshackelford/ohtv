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

# Show action summaries with their outputs
ohtv show abc123 -s -O

# Show full action details
ohtv show abc123 -d

# Show thinking/reasoning blocks
ohtv show abc123 -t

# Show user messages with thinking
ohtv show abc123 -u -t

# Include git refs summary at end
ohtv show abc123 -m -R

# Output as JSON
ohtv show abc123 -A -F json -o conversation.json

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
| `-d, --action-details` | Include full tool call details |
| `-O, --outputs` | Include tool call outputs/observations |
| `-t, --thinking` | Show thinking/reasoning blocks (think actions) |
| `-T, --timestamps` | Include timestamps on events |
| `-R, --refs` | Show git refs with write actions at end |

**Shorthand Flags:**
| Flag | Equivalent to |
|------|---------------|
| `-m, --messages` | `-u -a -f` (user + agent + finish) |
| `-A, --all` | All content flags enabled |
| `-S, --stats` | Statistics only, no content |

**Display Options:**
| Flag | Description |
|------|-------------|
| `-r, --reverse` | Show newest events first |
| `-n, --max N` | Maximum number of events to show |
| `-k, --offset N` | Skip first N events |
| `-F, --format` | Output format: `text` (default), `markdown`, `json` |
| `-o, --output FILE` | Write output to file |

---

### `ohtv refs` - Extract Git References

Extracts and displays all repository, issue, and PR/MR references found in a conversation, with annotations showing what actions were taken.

```bash
# Show all references with interaction annotations
ohtv refs abc123

# Show only refs where write actions were detected
ohtv refs abc123 --actions
```

**Detected Interactions:**
- **Repositories:** `cloned`, `pushed`
- **Pull Requests:** `created`, `pushed`, `commented`, `merged`, `closed`, `reviewed`
- **Issues:** `created`, `commented`, `closed`

**Options:**
| Flag | Description |
|------|-------------|
| `-a, --actions` | Show only refs with write actions |

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

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OH_API_KEY` | OpenHands Cloud API key | Required for `sync` |
| `OHTV_CLOUD_URL` | Cloud base URL | `https://app.all-hands.dev` |
| `OHTV_CONVERSATIONS_DIR` | Local CLI conversations directory | `~/.openhands/conversations` |
| `OHTV_CLOUD_CONVERSATIONS_DIR` | Synced cloud conversations directory | `~/.openhands/cloud/conversations` |

## Logging

Logs are written to `~/.openhands/cloud/logs/ohtv.log`:
- Rotates at 1MB, keeps 3 backups
- Use `-v, --verbose` on any command to also print debug output to console
