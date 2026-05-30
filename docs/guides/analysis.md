# LLM Analysis: `ohtv gen`

Run LLM-powered analyses on individual or batched conversations. Requires `LLM_API_KEY`.

## `ohtv gen` - LLM Generation Commands

The `gen` command provides LLM-powered analysis of conversations using customizable prompts. Currently supports `objs` analysis with multiple variants and context levels.

## `ohtv gen objs` - Extract User Objectives

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

# Control how much conversation context is analyzed (5 levels; Issue #149)
ohtv gen objs abc123 -c 1              # minimal: user messages only (fastest)
ohtv gen objs abc123 -c 2              # outcome: + finish action
ohtv gen objs abc123 -c 3              # dialogue: + agent messages
ohtv gen objs abc123 -c 4              # actions: + non-finish action summaries
ohtv gen objs abc123 -c 5              # observations: + tool outputs (highest tokens)

# Context levels also accept names
ohtv gen objs abc123 -c minimal
ohtv gen objs abc123 -c outcome
ohtv gen objs abc123 -c dialogue
ohtv gen objs abc123 -c actions
ohtv gen objs abc123 -c observations

# Force re-analysis (refresh cache)
ohtv gen objs abc123 -r

# Use a specific model
ohtv gen objs abc123 -m gpt-4o

# Output as JSON
ohtv gen objs abc123 --json

# MULTI-CONVERSATION MODE (without conversation_id)

# Analyze 10 most recent conversations (default)
ohtv gen objs

# Analyze today's conversations
ohtv gen objs --day

# Analyze last 7 days of conversations
ohtv gen objs -D 7

# Analyze this week's conversations
ohtv gen objs --week

# Analyze last 4 weeks of conversations
ohtv gen objs -W 4

# Analyze with date range
ohtv gen objs --since 2024-01-01 --until 2024-01-31

# Analyze all conversations (no limit)
ohtv gen objs --all

# Force re-analysis (refresh cache)
ohtv gen objs -r

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

# Roots-only by default (since #125 / v0.17.0):
# the working set excludes agent-delegated sub-conversations.
ohtv gen objs --week

# Opt back into per-sub analysis (pre-#125 behaviour):
ohtv gen objs --week --include-sub-conversations
```

> **Roots-only default (multi-conversation mode).** Since
> [#125](https://github.com/jpshackelford/ohtv/issues/125), the batch
> form `ohtv gen objs` (no `conversation_id` argument) defaults to
> **root conversations only**: sub-conversations created by agent
> delegation are excluded from the selection. Pass
> `--include-sub-conversations` to bring them back. The
> single-conversation form `ohtv gen objs <id>` is **unaffected** — it
> always analyzes exactly the conversation you point it at, root or
> sub.

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
┏━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ID      ┃ Date         ┃ Duration    ┃ Summary                               ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ abc1234 │ 2024-03-15   │ 35 mins     │ Refactor authentication module to use │
│ cloud   │ 10:42 AM     │ 46 steps    │ OAuth2 with refresh token support.    │
│         │              │             │ → created user/repo/pull/42           │
├─────────┼──────────────┼─────────────┼───────────────────────────────────────┤
│ def5678 │ 2024-03-14   │ 1h 20m      │ Fix pagination bug in search results  │
│ local   │ 2:15 PM      │ 128 steps   │ component that caused duplicate...    │
└─────────┴──────────────┴─────────────┴───────────────────────────────────────┘
Showing 2 of 150 (2/2 cached)
```

**Column Descriptions:**
| Column | First Line | Second Line |
|--------|------------|-------------|
| ID | Short conversation ID | Source (`cloud` or `local`) |
| Date | Date (YYYY-MM-DD) | Start time (HH:MM AM/PM) |
| Duration | Duration (e.g., "35 mins", "1h 20m") | Event/step count (e.g., "46 steps") |
| Summary | Goal description | Git refs (PRs, repos modified), labels (if present) |

**JSON Output Fields (`-F json`):**
```json
[
  {
    "id": "abc12345def67890",
    "source": "cloud",
    "created_at": "2024-03-15T10:42:00+00:00",
    "start_time": "10:42",
    "duration_seconds": 2100,
    "event_count": 46,
    "goal": "Refactor authentication module...",
    "labels": {"project": "SDK", "status": "WIP"}
  }
]
```

| Field | Description |
|-------|-------------|
| `id` | Full conversation ID |
| `source` | Source location (`cloud` or `local`) |
| `created_at` | ISO 8601 timestamp |
| `start_time` | Start time in HH:MM format |
| `duration_seconds` | Duration in seconds (or `null` if unknown) |
| `event_count` | Number of events/steps in the conversation |
| `goal` | Extracted goal description |
| `labels` | Cloud-sourced labels/tags as key-value pairs (if present) |

**Markdown Output (`-F markdown`):**
```markdown
- **abc1234** (2024-03-15, 10:42 AM, 35 mins, 46 steps): Refactor authentication...
  - created user/repo/pull/42
  - pushed user/repo
  - Labels: project=SDK, status=WIP
```

**Options (Single-Conversation Mode):**
| Flag | Description |
|------|-------------|
| `-v, --variant` | Output variant (default: `brief`) |
| `-c, --context` | Context level: 1-5 or name (default: from prompt). See [Context levels](#context-levels-gen-objs--c-flag). |
| `-r, --refresh` | Force re-analysis (refresh cache) |
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
| `-D, --day [VALUE]` | Filter by day: `-D` (today), `-D DATE` (specific date), or `-D N` (last N days) |
| `-W, --week [VALUE]` | Filter by week: `-W` (this week), `-W DATE` (week of date), or `-W N` (last N weeks) |
| `--pr PATTERN` | Filter by PR reference (URL, `owner/repo#N`, or `repo#N`) |
| `--repo PATTERN` | Filter by repository (URL, `owner/repo`, or name) |
| `--action TYPE` | Filter by action type (e.g., `pushed`, `open-pr`) |
| `-L, --label KEY=VALUE` | Filter by label (cloud API tags in `key=value` format) |
| `--reverse` | Show oldest first |
| `-r, --refresh` | Force re-analysis (refresh cache) |
| `-m, --model` | LLM model to use |
| `-F, --format` | Output format: `table`, `json`, `markdown` |
| `--no-outputs` | Don't show outputs (repos, PRs, issues modified) |
| `-y, --yes` | Skip confirmation for large result sets (>20 conversations) |
| `-q, --quiet` | Generate/cache summaries without displaying output |
| `--include-sub-conversations` | Include sub-conversations created by agent delegation (default: roots only). See note above. |
| `--verbose` | Show debug output |

### Context levels (`gen objs --c` flag)

Issue #149 replaced the previous 3-level context system (`minimal`/`default`/`full`) with a 5-level additive ladder. Each level is a strict superset of the previous one:

| # | Name           | Adds                                                | Use case                              |
|---|----------------|-----------------------------------------------------|---------------------------------------|
| 1 | `minimal`      | User messages only                                  | "What did they ask for?"              |
| 2 | `outcome`      | + `finish` action                                   | "How did it end?"                     |
| 3 | `dialogue`     | + agent messages                                    | "What was the conversation flow?"     |
| 4 | `actions`      | + non-finish action summaries with full commands    | "What steps were taken and how?"      |
| 5 | `observations` | + truncated tool observations (terminal/file outputs)| "What were the results?"              |

You can specify either the numeric form (`-c 3`) or the name (`-c dialogue`). The CLI accepts either; both resolve to the same canonical name internally. Old names `default` (was level 2) and `full` (was level 3) **no longer work** — pass `outcome` or `actions` respectively.

**Per-prompt defaults** (frontmatter `context.default`):

| Variant            | Default level | Rationale                                                  |
|--------------------|---------------|------------------------------------------------------------|
| `brief`            | `minimal`     | Goal extraction needs only the user's framing              |
| `brief_assess`     | `outcome`     | Status check needs the finish message                      |
| `standard`         | `outcome`     | Outcomes derive from the finish summary                    |
| `standard_assess`  | `outcome`     | Same as above + status                                     |
| `detailed`         | `actions`     | Hierarchical objectives need agent reasoning + action list |
| `detailed_assess`  | `actions`     | Same as above + status                                     |

**Auto-promotion ladder.** When the requested context produces an empty transcript but the conversation does have agent actions (e.g. orchestrator worker conversations with no user messages), `analyze_objectives` automatically walks up the ladder **one level at a time** — `minimal → outcome → dialogue → actions → observations` — until content materialises. This replaces the previous 2-jump system (`minimal → default → full`) which over-shot in the common case where only the finish action was needed. Promotions are logged at debug level.

**Cache invalidation.** Existing cache entries keyed against the old `default`/`full` names are simply orphaned (the cache layer never re-keys them). The next `gen objs` invocation per conversation regenerates analyses at the new level names. No migration is needed; expect a one-time spend on the first `gen objs` pass after upgrading.

**Embeddings.** `embeddings.cache_key` follows the same one-time orphaning behaviour. `ohtv db status` degrades gracefully (it reports "missing embeddings" by cache_key, surfacing the orphans), and `ohtv db embed` re-embeds the new variants on the next run.

## `ohtv gen titles` - Auto-Rename Placeholder-Titled Cloud Conversations

Renames cloud conversations whose title still matches the OpenHands placeholder pattern (`^Conversation [0-9a-f]{5,32}$`) — plus empty/whitespace-only titles — by reading the best-available cached `gen objs` analysis, batching them through an LLM to produce concise Title Case titles (≤ 50 chars, optional leading emoji, no trailing punctuation), and PATCHing the new titles back to the OpenHands Cloud API in parallel.

**Prerequisites:**
- Cloud conversations must already be synced locally (`ohtv sync`).
- Each selected conversation must have a cached `gen objs` analysis. Run `ohtv gen objs <filter>` first to seed the cache; conversations with no cache are skipped before the LLM call.
- `LLM_API_KEY` (for the rename LLM call) and `OPENHANDS_API_KEY` / `OH_API_KEY` (for the PATCH back to cloud).

**Cache lookup order:** The command probes cached analyses in descending detail order — `detailed_assess > detailed > standard_assess > standard > brief_assess > brief` — and uses the first one it finds.

**Scope:**
- **Cloud only.** Local CLI conversations are silently skipped (single end-of-run note) — the PATCH endpoint is cloud-only.
- **Placeholder titles only by default.** Use `--all-titled` to retitle every selected conversation, including those already given a human-set title.

```bash
# DEFAULT: last 10 placeholder-titled cloud conversations
ohtv gen titles

# Preview only — no PATCH, no manifest/DB writeback
ohtv gen titles --dry-run -n 20

# Today's placeholder-titled cloud conversations
ohtv gen titles --day

# This week's, dry-run first
ohtv gen titles --week --dry-run

# Last 7 days, with 10 parallel PATCH workers (cap is 50)
ohtv gen titles -D 7 --workers 10

# Retitle EVERY conversation matching a label, even if already titled
ohtv gen titles --all-titled --label experiment=t1

# Skip the >5-conv confirmation prompt
ohtv gen titles -y --workers 10

# Use a cheaper / faster model for the renaming step
ohtv gen titles -m haiku

# Filter by repo or PR (uses indexed actions; run `ohtv db process all` first)
ohtv gen titles --repo OpenPaw
ohtv gen titles --pr OpenPaw#17

# Roots-only by default (since #125 / v0.17.0):
ohtv gen titles --week

# Opt back into per-sub retitling (pre-#125 behaviour):
ohtv gen titles --week --include-sub-conversations
```

> **Roots-only default.** Like `gen objs` batch mode, `ohtv gen titles`
> defaults to **root conversations only** since
> [#125](https://github.com/jpshackelford/ohtv/issues/125) —
> sub-conversations created by agent delegation are skipped. Pass
> `--include-sub-conversations` to retitle subs as well.

**How a run is structured:**

1. **Selector** reuses the `gen objs` multi-conversation filter surface (`-D/--day`, `-W/--week`, `-S/--since`, `-U/--until`, `--pr`, `--repo`, `-L/--label`, `-n/--max`, `-A/--all`, `-k/--offset`, `--reverse`) plus a placeholder-title predicate; `--all-titled` disables that predicate.
2. **Cache probe** picks the most detailed cached `gen objs` analysis available per conversation. No cache → conversation is skipped (no LLM call).
3. **LLM** batched JSON-in / JSON-out (default 25 conversations per call, override with `--batch-size`). Falls back to single-conversation retry on chunk parse failure, and re-prompts (then hard-truncates) any titles that come back > 50 chars.
4. **Parallel PATCH** through the existing cloud-client retry/`Retry-After` machinery. Default 5 workers (`--workers`, capped at 50).
5. **Local writeback** rewrites the manifest title in place (without advancing `last_sync_at`) and updates the SQLite metadata via `ConversationStore.update_metadata`. `--dry-run` skips both the PATCH and the writeback.

**Options:**

| Flag | Description |
|------|-------------|
| `-n, --max N` | Maximum conversations to consider (default: `10`) |
| `-A, --all` | Consider all conversations (no limit) |
| `-k, --offset N` | Skip first N conversations |
| `-S, --since DATE` | Only conversations from DATE onwards (`YYYY-MM-DD`) |
| `-U, --until DATE` | Only conversations up to DATE (`YYYY-MM-DD`) |
| `-D, --day [VALUE]` | Filter by day: `-D` (today), `-D DATE`, or `-D N` (last N days) |
| `-W, --week [VALUE]` | Filter by week: `-W` (this week), `-W DATE`, or `-W N` (last N weeks) |
| `--pr PATTERN` | Filter by PR (URL, `owner/repo#N`, or `repo#N`) |
| `--repo PATTERN` | Filter by repo (URL, `owner/repo`, or name) |
| `-L, --label KEY=VALUE` | Filter by cloud-API label/tag |
| `--reverse` | Process oldest first (default: newest first) |
| `--all-titled` | Override the placeholder predicate and retitle every selected conversation |
| `--dry-run` | Generate titles and print diff without PATCH or local writeback |
| `--workers N` | Parallel PATCH workers (default: `5`, capped at `50`) |
| `--batch-size N` | Conversations per LLM call (default: `25`) |
| `-m, --model MODEL` | LLM model override (e.g. `haiku`) |
| `-y, --yes` | Skip the >5-conversation confirmation prompt |
| `--lock-timeout SECONDS` | Wait up to N seconds for `$OHTV_DIR/sync.lock` instead of failing fast. Default `0` = fail-fast. See note below. |
| `--include-sub-conversations` | Include sub-conversations created by agent delegation (default: roots only). See note above. |
| `--verbose` | Show debug output |

> **Writer mutex.** `ohtv gen titles` PATCHes cloud titles and writes
> back to the local manifest + the `conversations` table, so it acquires
> the shared `$OHTV_DIR/sync.lock` writer mutex (the same one used by
> `ohtv sync` and `ohtv db scan`). Default is fail-fast — if another
> writer is running, the command exits 1 with a pointer to the lock
> file. Pass `--lock-timeout=N` to wait. See
> [reference/database.md § Column Ownership and the `sync.lock` Writer Mutex](../reference/database.md#column-ownership-and-the-synclock-writer-mutex)
> for the canonical contract.

**Customizing the prompt:**

The prompt that turns `{id, description}` into a title lives at `src/ohtv/prompts/titles/default.md`. Override it per-user by copying it to `~/.ohtv/prompts/titles/default.md`:

```bash
ohtv prompts init                # copies all default prompts (incl. titles/default)
ohtv prompts show titles/default # view the active titles prompt
ohtv prompts reset titles/default
```

## `ohtv gen run` - Run Aggregate Analysis Jobs

Runs aggregate analysis jobs that synthesize cached results from multiple conversations into a single output. Supports periodic iteration (weekly, daily, monthly reports) and non-periodic aggregation (theme discovery across all selected conversations).

```bash
# PERIODIC AGGREGATE JOBS (iterate over time periods)

# Generate weekly reports for the last 4 weeks
ohtv gen run reports.weekly --last 4

# Generate weekly reports for a specific date range
ohtv gen run reports.weekly --since 2024-01-01 --until 2024-03-31

# Generate monthly reports instead of weekly (override job's default period)
ohtv gen run reports.weekly --since 2024-01 --until 2024-06 --per month

# Generate weekly report for this week only
ohtv gen run reports.weekly --week

# NON-PERIODIC AGGREGATE JOBS (single output from all conversations)

# Discover themes across this week's conversations
ohtv gen run themes.discover --week

# Discover themes across a date range
ohtv gen run themes.discover --since 2024-01-01 --until 2024-03-31

# OUTPUT OPTIONS

# Output as JSON (for automation)
ohtv gen run reports.weekly --last 4 --format json

# Write each period's result to separate files
ohtv gen run reports.weekly --last 4 --out ./reports/

# Force re-analysis (refresh cache)
ohtv gen run reports.weekly --last 4 -r

# Skip confirmation prompts
ohtv gen run reports.weekly --last 4 -y

# Roots-only by default (since #125 / v0.17.0):
ohtv gen run reports.weekly --last 4

# Opt back into per-sub aggregation (pre-#125 behaviour):
ohtv gen run reports.weekly --last 4 --include-sub-conversations
```

> **Roots-only default.** Aggregate jobs default to **root
> conversations only** since
> [#125](https://github.com/jpshackelford/ohtv/issues/125): the
> source-conversation membership of each period excludes
> agent-delegated sub-conversations, matching the grain that
> `report velocity` and `report weekly-counts` already use. Pass
> `--include-sub-conversations` to aggregate over every row.

**How Aggregate Jobs Work:**

1. **Source Cache**: Aggregate jobs require cached results from a source job (e.g., `objs.brief`). If not cached, the source job runs automatically on uncached conversations.

2. **Period Iteration**: Jobs with `period: week|day|month` in their frontmatter iterate over time periods. Use `--last N` for the last N periods, or `--since`/`--until` for a date range.

3. **Non-Periodic Jobs**: Jobs without a `period` field aggregate all selected conversations into a single output.

4. **Minimum Items**: Jobs can specify `min_items` to skip periods with insufficient data.

**Built-in Aggregate Jobs:**

| Job ID | Type | Description |
|--------|------|-------------|
| `reports.weekly` | Periodic (week) | Generate weekly summary with themes, highlights, and stats |
| `themes.discover` | Non-periodic | Identify common themes across all selected conversations |

**Creating Custom Aggregate Jobs:**

Create a markdown file in `~/.ohtv/prompts/` with aggregate frontmatter:

```markdown
---
id: my.aggregate
description: My custom aggregate analysis

input:
  mode: aggregate
  source: objs.brief    # Source job for cached results
  period: week          # Optional: week, day, or month
  min_items: 1          # Minimum conversations required

output:
  schema:
    type: object
    properties:
      summary:
        type: string
---
Analyze the following {{ items | length }} conversations:

{% for item in items %}
- [{{ item.conversation_id[:8] }}] {{ item.result.goal }}
{% endfor %}

Respond with JSON matching the output schema.
```

**Options:**

| Option | Description |
|--------|-------------|
| `--per week\|day\|month` | Override/specify iteration granularity |
| `--last N` | Process last N periods |
| `--since`, `--until` | Date range for period iteration |
| `--week`, `--day` | Shorthand for current week/day |
| `--out DIR` | Write each period's output to separate files |
| `-F, --format` | Output format: `table`, `json`, `markdown` |
| `-r, --refresh` | Force re-analysis (refresh cache) |
| `-m, --model` | LLM model to use |
| `-y, --yes` | Skip confirmation prompts |
| `--include-sub-conversations` | Include sub-conversations created by agent delegation (default: roots only). See note above. |

---

