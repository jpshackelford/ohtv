# Exploration: `list`, `show`, `refs`, `errors`

Once your conversations are synced and indexed, these four commands answer most "what happened?" questions.

## `ohtv list` - List Conversations

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

# Show last 3 days of conversations
ohtv list -D 3

# Show last 7 days of conversations
ohtv list -D 7

# Show this week's conversations (weeks start Sunday)
ohtv list --week

# Show conversations from a specific week
ohtv list --week 2024-03-15

# Show last 2 weeks of conversations
ohtv list -W 2

# Show last 4 weeks of conversations
ohtv list -W 4

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

# Filter by label (cloud API tags)
ohtv list --label project=SDK            # Conversations with label project=SDK
ohtv list -L status=WIP                  # Short form
ohtv list --label team=AI --repo OpenPaw # Combine with other filters

# Show idle time instead of duration (for orchestration)
ohtv list --idle                  # Default: 7 min threshold
ohtv list --idle 15               # Custom: 15 min threshold
# Red = active (< threshold), Green = quiet (>= threshold)

# Hide refs from title column
ohtv list --no-refs               # Refs shown by default
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
| `-D, --day [VALUE]` | Filter by day: `-D` (today), `-D DATE` (specific date), or `-D N` (last N days) |
| `-W, --week [VALUE]` | Filter by week: `-W` (this week), `-W DATE` (week of date), or `-W N` (last N weeks) |
| `--pr PATTERN` | Filter by PR reference (URL, `owner/repo#N`, or `repo#N`) |
| `--repo PATTERN` | Filter by repository (URL, `owner/repo`, or name) |
| `--action TYPE` | Filter by action type (e.g., `pushed`, `open-pr`, `git-commit`) |
| `-L, --label KEY=VALUE` | Filter by label (cloud API tags in `key=value` format) |
| `--idle [MINS]` | Show Idle column (time since last event). Colorized: red if < MINS (default: 7), green if >= MINS |
| `--no-refs` | Hide git refs from title (refs shown by default) |
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

**Note:** PR, repo, action, and label filters require the database to be indexed. Run `ohtv db scan && ohtv db process all` first. Labels are stored from the cloud API during `ohtv sync`.

---


## `ohtv show` - View Conversation Content

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


## `ohtv refs` - Extract Git References

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
| `-D, --day [VALUE]` | Filter by day: `-D` (today), `-D DATE` (specific date), or `-D N` (last N days) |
| `-W, --week [VALUE]` | Filter by week: `-W` (this week), `-W DATE` (week of date), or `-W N` (last N weeks) |
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


## `ohtv errors` - Show Agent/LLM Error Summary

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

