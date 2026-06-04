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

# Show engagement columns (Engaged / Periods / Eng%)
# Requires the engagement stage: `ohtv db process all` (or
# `ohtv db process engagement`). Rows without engagement data render `-`.
ohtv list --with-engagement
ohtv list --with-engagement --repo OpenPaw -A
ohtv list --with-engagement -F json    # Adds 5 keys per row
ohtv list --with-engagement -F csv     # Appends 5 columns

# Roots-only by default (since #127 / v0.18.0):
# rows represent root conversations; agent-delegated subs are hidden.
ohtv list -A

# Opt back into per-sub rendering (pre-#127 behaviour):
ohtv list -A --include-sub-conversations
```

<a id="roots-only-default"></a>

> **Roots-only default (v0.18.0).** Since
> [#127](https://github.com/jpshackelford/ohtv/issues/127), `ohtv list`
> shows **root conversations only**: sub-conversations created by agent
> delegation are hidden so each row represents a unit of human intent.
> Filters like `--pr`, `--repo`, `--label`, and `--action` resolve
> through the root grain — a PR or repo touched only by a delegated sub
> still surfaces the matching root row (not the sub). Pass
> `--include-sub-conversations` to restore the pre-#127 behavior of
> rendering every conversation as its own row. This is a **breaking
> change** that ships alongside the same flip on `ohtv refs`
> (v0.17.0 already flipped `gen objs / titles / run` — see
> [analysis guide](analysis.md)).

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
| `--with-engagement` | Include engagement columns (`Engaged`, `Periods`, `Eng%`) in the table, five fields in JSON, and five appended columns in CSV. Default off. Values come from the [`engagement` indexing stage](indexing.md#engagement-stage) — run `ohtv db process all` (or `ohtv db process engagement`) to populate them. Rows with no engagement row render dim `-` in the table and `null` / empty in JSON / CSV. Display-only: never filters rows out. See [Engagement columns](#engagement-columns--with-engagement) below. |
| `--engaged` | Filter to conversations with `engaged_seconds > 0`. Missing engagement rows are excluded. Mutually exclusive with `--no-engaged`; composes silently with `--min-engaged` / `--min-engagement-ratio`. See [Engagement filters](#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio). |
| `--no-engaged` | Filter to fire-and-forget conversations (`engaged_seconds == 0` **OR** the engagement row is missing). Only engagement flag that *includes* missing rows. Mutually exclusive with `--engaged`, `--min-engaged`, `--min-engagement-ratio`. |
| `--min-engaged DURATION` | Filter to `engaged_seconds >= DURATION`. Accepts `30s` / `5m` / `1h` / `1h30m` (case-insensitive); a bare number is interpreted as **minutes** (`5` == `5m`). Negatives / nonsense raise `BadParameter` (exit 2). Missing engagement rows are excluded. |
| `--min-engagement-ratio PCT` | Filter to `engaged_seconds / total_duration_seconds >= PCT / 100`. `PCT` is a float in `[0, 100]`. Rows with `total_duration_seconds == 0` / `NULL` / missing engagement data are excluded. |
| `--event-dates` | Interpret `--since` / `--until` / `-D` / `-W` against `conversation_engagement.first_event_ts` / `last_event_ts` instead of `conversations.created_at`. Useful for finding conversations whose **engagement happened** in the date range, regardless of when they were originally started. Conversations without an engagement row are excluded (INNER JOIN). Requires at least one date filter — using `--event-dates` alone raises a `UsageError`. Available on `list`, `search`, `ask`, `gen objs`, `gen titles`, and `gen run`. See [Filtering by event timestamps](#filtering-by-event-timestamps---event-dates) below. |
| `--include-sub-conversations` | Include sub-conversations created by agent delegation (default: roots only). See note above. |
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

<a id="engagement-columns--with-engagement"></a>

### Engagement columns (`--with-engagement`)

The `--with-engagement` flag (added in [#171](https://github.com/jpshackelford/ohtv/pull/171), tracks [#167](https://github.com/jpshackelford/ohtv/issues/167)) extends `ohtv list` with the sustained-attention metric that `ohtv show` reports per-conversation (see [Stats output: the `Engaged:` line](#stats-output-the-engaged-line) and [Issue #163](https://github.com/jpshackelford/ohtv/issues/163)) — surfaced here as a cross-conversation comparison view.

**Prerequisite:** values come from the [`engagement` indexing stage](indexing.md#engagement-stage). Run `ohtv db process all` (or `ohtv db process engagement` for just this stage) after syncing. Without it the three table columns render dim `-` and JSON / CSV emit `null` / empty values — rows are **never** filtered out.

**Table view** adds three right-aligned columns (`Engaged`, `Periods`, `Eng%`) after the existing `Events` column:

```text
$ ohtv list --repo OWNER/REPO --with-engagement -A
┃ ID       ┃ Source ┃ Started          ┃ Duration ┃ Events ┃ Engaged ┃ Periods ┃ Eng%  ┃ Title             ┃
│ a711cbbc │ cloud  │ 2026-05-30 14:02 │  2h 14m  │    312 │ 41m 0s  │      3 │ 30.6% │ Add deploy hooks  │
│ 8f2e1c4d │ cloud  │ 2026-05-30 09:18 │     50m  │     94 │ 4m 24s  │      2 │  8.8% │ Fix flaky CI      │
│ 1c0a5b3e │ local  │ 2026-05-29 22:45 │      8m  │     12 │    -   │    -   │   -   │ Quick repo poke   │
```

- **Engaged** — `engaged_seconds` formatted via the standard duration helper (`4m 24s`, `2h 14m`, `0s`).
- **Periods** — bare `attention_periods` integer. A real `0` renders as `0`, not `-`.
- **Eng%** — `engaged_seconds / total_duration_seconds * 100`, formatted as `XX.X%`. Renders dim `-` when total is `0` / `NULL` / missing.
- Conversations with no engagement row render dim `-` in all three columns.

**JSON view (`-F json`)** adds five fields per row (matching the schema [PR #165](https://github.com/jpshackelford/ohtv/pull/165) established on `ohtv show <id> -F json`, plus a computed `engagement_ratio`):

```json
{
  "engaged_seconds": 2460,
  "attention_periods": 3,
  "engagement_threshold_seconds": 720,
  "total_duration_seconds": 8040,
  "engagement_ratio": 0.306
}
```

Missing values emit JSON `null` so the schema stays stable across rows.

**CSV view (`-F csv`)** appends five columns to the existing header:

```
engaged_seconds,attention_periods,engagement_threshold_seconds,total_duration_seconds,engagement_ratio
```

Empty strings for missing values; zeros are preserved as `0`.

**Composes with other flags.** `--with-engagement` is purely a display switch — it adds columns / fields but never filters rows. It works alongside `--repo`, `--pr`, `--action`, `--label`, `--since` / `--until`, `--day` / `--week`, `--errors-only`, `--with-errors`, `--idle`, `--include-sub-conversations`, `--reverse`, `-n` / `-k`, `-A`, `--include-empty`, `--no-refs`, and any output format (`-F table|json|csv`).

> **Need to actually filter by engagement?** See the next subsection — `--engaged`, `--no-engaged`, `--min-engaged`, and `--min-engagement-ratio` were added in [#175](https://github.com/jpshackelford/ohtv/pull/175) (tracks [#170](https://github.com/jpshackelford/ohtv/issues/170)) and are orthogonal to `--with-engagement` (you can filter without displaying, or display without filtering, or both).

<a id="engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio"></a>

### Engagement filters (`--engaged` / `--no-engaged` / `--min-engaged` / `--min-engagement-ratio`)

Added in [#175](https://github.com/jpshackelford/ohtv/pull/175) (tracks [#170](https://github.com/jpshackelford/ohtv/issues/170)). The same four flags are wired into `ohtv list`, `ohtv gen objs`, `ohtv gen titles`, and `ohtv gen run` — see [analysis guide § Engagement filters](analysis.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio) for the per-`gen` examples.

**Prerequisite** (same as `--with-engagement` display): values come from the [`engagement` indexing stage](indexing.md#engagement-stage). Run `ohtv db process all` (or `ohtv db process engagement` for just this stage) after syncing — `ohtv sync` does this automatically.

| Flag | Semantics | Missing engagement row |
|------|-----------|------------------------|
| `--engaged` | `engaged_seconds > 0` | **excluded** |
| `--no-engaged` | `engaged_seconds == 0` OR row missing | **included** ← only flag that does this |
| `--min-engaged DURATION` | `engaged_seconds >= DURATION` | **excluded** |
| `--min-engagement-ratio PCT` | `engaged_seconds / total_duration_seconds >= PCT / 100` (PCT in `[0, 100]`) | **excluded** (also when `total_duration_seconds == 0` or `NULL`) |

`--min-engaged` accepts the durations parsed by `parse_duration_to_seconds`:

- `30s` / `5m` / `1h` / `1h30m` (case-insensitive, combinations welcome)
- a bare integer or float interpreted as **minutes** — so `--min-engaged 5` is the same as `--min-engaged 5m`, *not* `5s` ← this matches the issue's UX rationale ([#170](https://github.com/jpshackelford/ohtv/issues/170))
- negatives or unparseable strings raise `click.BadParameter` (exit code `2`) before any DB work

**Mutual exclusion** (raises `BadParameter`, exit `2`, before any DB query):

- `--engaged` ⊕ `--no-engaged`
- `--no-engaged` ⊕ `--min-engaged`
- `--no-engaged` ⊕ `--min-engagement-ratio`
- `--engaged` **+** `--min-engaged` / `--min-engagement-ratio` composes silently (the threshold flag implies engaged; `--engaged` is absorbed with no warning).

**Examples:**

```bash
# Productivity review: what did I actually steer this week?
ohtv list --week --engaged --with-engagement

# Automation candidates: ran unattended in OpenPaw over the last 30 days
ohtv list --repo jpshackelford/OpenPaw --no-engaged -D 30

# Deep-dive sessions: >= 30 min of real human attention, newest last
ohtv list --min-engaged 30m --reverse

# High-ratio conversations as CSV for spreadsheet analysis
ohtv list --min-engagement-ratio 50 -F csv > engaged.csv

# Filter + display: include the engagement columns alongside the filter
ohtv list --min-engaged 5m --with-engagement
```

**Output-format independence.** The filter applies *before* formatting, so `-F table`, `-F json`, and `-F csv` see the same row set. The reported `Showing X of Y conversations` counts reflect the filter — `Y` is the post-filter total, not the unfiltered count.

**Performance.** The filter uses the existing batched `_load_engagement_for_conversations` helper (single `WHERE conversation_id IN (?, ?, …)` query, chunked at 900 IDs). No per-row queries.

**Note.** `--max-engaged` and `--sort engaged` are deferred (see [Issue #170 § Out of Scope](https://github.com/jpshackelford/ohtv/issues/170)).

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

<a id="filtering-by-event-timestamps---event-dates"></a>

### Filtering by event timestamps (`--event-dates`)

Added in [#180](https://github.com/jpshackelford/ohtv/issues/180). By
default, `--since` / `--until` / `-D` / `-W` filter against
`conversations.created_at` — the moment the conversation was *first*
started. That works for "what did we start this week?" but misses the
case where a conversation was created weeks ago and then re-engaged
recently. `--event-dates` swaps the column under the predicate to
`conversation_engagement.first_event_ts` / `last_event_ts` so the
same flags now mean "what was *touched* in the window".

**Round-trip example.** A conversation created `T₀-30d` whose last
event landed at `T₀` would not appear under `--since T₀-7d`, but it
*will* appear under `--event-dates --since T₀-7d`:

```bash
# Conversations started in the last 7 days (default):
ohtv list --since 7d

# Conversations re-engaged in the last 7 days (Issue #180):
ohtv list --event-dates --since 7d
```

**Predicate semantics.** With both bounds, the flag uses interval
overlap: a conversation matches if `[first_event_ts, last_event_ts]`
overlaps `[since, until]`. With only one bound:

- `--event-dates --since X` includes rows where `last_event_ts >= X`.
- `--event-dates --until Y` includes rows where `first_event_ts <= Y`.

**Hard requirements.**

- Requires at least one of `--since` / `--until` / `-D` / `-W`. Using
  `--event-dates` on its own raises a `UsageError` (exit 2) — it has
  no defined meaning without a date filter.
- INNER JOIN semantics: conversations without an engagement row are
  silently excluded. Run `ohtv db process engagement` (or
  `ohtv sync`, which now runs all processing stages) to populate
  engagement data for indexed conversations. The empty-result hint
  surfaces this when no rows match.
- Available on `list`, `search`, `ask`, `gen objs`, `gen titles`, and
  `gen run`. **Not** available on `refs` (refs are intrinsically tied
  to action timestamps already).

**Performance.** Migration 024 adds covering indexes
(`idx_conv_engagement_last_event_ts`,
`idx_conv_engagement_first_event_ts`) so the JOIN is O(log N) per
predicate. On a 5,000-conversation DB the swap adds <10 ms to `ohtv
list` (microbenchmark vs the plain `created_at` path).

### Stats output: the `Engaged:` line

When the [`engagement` indexing stage](indexing.md#engagement-stage)
has run for a conversation, `ohtv show` (default stats view, or `--stats`) adds an **`Engaged:`** line beneath `Duration:` reporting the sustained-attention metric introduced for [Issue #163](https://github.com/jpshackelford/ohtv/issues/163) — how long a human was actively monitoring/steering, plus how many attention periods that engagement broke into.

Example `ohtv show <id>` (text format):

```text
Conversation: abc123def456
Title:    Wire up engagement metric
Status:   COMPLETED
Started:  2026-06-03 09:12:04
Ended:    2026-06-03 10:02:18
Duration: 50m 14s
Engaged:  4m 24s in 2 periods (8.8% of 50m total)   — new in #165

Event Counts:
  User messages:    7
  Agent messages:   42
  ...
```

Notes:

- The `Engaged:` line is **omitted** (not shown as `N/A`) when no engagement row exists yet — run `ohtv db process engagement` to populate it.
- The percentage is computed against the **event-derived** total duration (first event timestamp → last event timestamp), which can differ slightly from the `Duration:` line above (which uses `base_state.json`). See the [design doc](../design/conversation-metrics.md#engaged-human-minutes-sustained-attention-metric--issue-163) § "Reconciliation with the existing duration display."
- The threshold used for the stored row defaults to **12 minutes**; re-run `ohtv db process engagement --threshold N --force` (in seconds) to recompute under a different `T`.

**JSON output (`-F json`)** gains four new top-level keys when an engagement row is present:

```json
{
  "id": "abc123def456",
  "title": "Wire up engagement metric",
  "started": "2026-06-03T09:12:04+00:00",
  "ended": "2026-06-03T10:02:18+00:00",
  "duration_seconds": 3014.0,
  "counts": { "user_messages": 7, "agent_messages": 42 },
  "total_events": 71,
  "engaged_seconds": 264,
  "attention_periods": 2,
  "engagement_threshold_seconds": 720,
  "total_duration_seconds": 3015
}
```

Consumers should treat the four engagement keys as **optional** — they only appear when the `engagement` stage has run for that conversation.

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

# When abc123 is a *root* conversation (since #127 / v0.18.0):
# refs are rolled up across the entire delegation subtree (union, dedup by URL).
ohtv refs <root-id>

# When abc123 is a *sub-conversation*: behavior is unchanged — single-conv
# view always shows only that conversation's own refs.
ohtv refs <sub-id>
```

> **Subtree rollup on root ids (v0.18.0).** Since
> [#127](https://github.com/jpshackelford/ohtv/issues/127),
> `ohtv refs <root-id>` walks the delegation tree and unions the refs
> from every sub under that root (deduped by URL). Interactions
> (`created`, `pushed`, `merged`, …) merge per ref so the strongest
> link wins. Pointing `ohtv refs` at a sub-id is unchanged — the
> single-conv path always shows that conversation's own refs.
> `--include-sub-conversations` is accepted for API symmetry with the
> multi-conv path but does not change single-conv behavior (rollup on a
> root is already the "show every sub's refs" mode).

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

# Roots-only by default (since #127 / v0.18.0):
# only root conversations are scanned; each root's refs roll up its subtree.
ohtv refs -D

# Opt back into per-sub iteration (pre-#127 behaviour):
ohtv refs -D --include-sub-conversations
```

> **Roots-only default in multi-conv mode (v0.18.0).** The filter
> pipeline (`--pr`, `--repo`, `--action`, `--label`, `-D`, `-W`, etc.)
> resolves through the root grain so a PR or repo touched only by a
> delegated sub still surfaces the matching root row, not the sub.
> Each rendered root then rolls up its subtree's refs (same logic as
> single-conv on a root id). Pass `--include-sub-conversations` to opt
> back into the pre-#127 per-sub iteration where each sub is rendered
> separately with its own refs.

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
| `--include-sub-conversations` | Include sub-conversations created by agent delegation (default: roots only in multi-conv mode; no-op on single-conv form). See notes above. |
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

