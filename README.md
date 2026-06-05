# ohtv — OpenHands Trajectory Viewer

A CLI for syncing, indexing, analyzing, and reporting on
[OpenHands](https://github.com/All-Hands-AI/OpenHands) conversation
trajectories — from both the cloud product and local CLI sessions.

- 🔄 **Sync** cloud conversations to disk (incremental, with metadata refresh).
  Delegated sub-conversations are synced by default since
  [#108](https://github.com/jpshackelford/ohtv/pull/134); `list`, `refs`,
  `gen objs / titles / run`, and the report commands then roll up to root
  conversations by default. Pass `--include-sub-conversations` on any of them
  to opt back into per-sub rendering. *(`list` and `refs` flipped in v0.18.0
  — see the [exploration guide](docs/guides/exploration.md#roots-only-default)
  for the migration note.)*
- 📚 **Index** them into a local SQLite database (refs, actions, contributions, human input, engagement)
- 🤖 **Analyze** with LLMs (objectives, summaries, weekly reports, auto-titles)
- 🎯 **Filter** by engagement (`--engaged` / `--no-engaged` / `--min-engaged 5m` / `--min-engagement-ratio 25`) on `list` and every `gen` subcommand
- 📈 **Report** velocity (merged-PRs × LOC × human-words) as tables, CSV, or 3-panel charts
- 🔍 **Search & ask** semantically via embeddings + RAG (with optional multi-step agent mode)
- 🐙 **Backfill LOC** for every PR/push contribution via the GitHub API

## Installation

```bash
pip install ohtv
# Optional: pip install 'ohtv[charts]'  for --chart PNG/SVG/PDF output
```

Python 3.12+. See [docs/guides/installation.md](docs/guides/installation.md)
for the full setup, including API keys.

## Quick start

```bash
# 1. Sync from cloud + run the indexing pipeline
export OPENHANDS_API_KEY=...
ohtv sync --process

# 2. Browse what landed
ohtv list
ohtv show <conversation_id>
ohtv refs <conversation_id>

# 3. Run an LLM analysis (optional)
export LLM_API_KEY=...
ohtv gen objs

# 4. Backfill LOC and run a weekly velocity report
export GITHUB_TOKEN=$(gh auth token)
ohtv fetch-loc
ohtv report velocity
ohtv report velocity --chart velocity.png --since 12w
```

A 5-minute end-to-end walkthrough lives at
[docs/guides/getting-started.md](docs/guides/getting-started.md).

## Commands

| Group | Commands | Detailed docs |
|---|---|---|
| **Sync & index** | `sync`, `db scan/process/embed/migrate-cache/status` | [syncing](docs/guides/syncing.md), [indexing](docs/guides/indexing.md) |
| **Explore** | `list`, `show`, `refs`, `errors` | [exploration](docs/guides/exploration.md) |
| **Classify** | `classify` | [classification](docs/guides/classification.md) |
| **Analyze (LLM)** | `gen objs / titles / run`, `prompts` | [analysis](docs/guides/analysis.md), [customizing-prompts](docs/guides/customizing-prompts.md) |
| **Report** | `report velocity / weekly-counts`, `fetch-loc` | [reporting](docs/guides/reporting.md) |
| **Search & ask** | `search`, `ask`, `messages` | [search-and-ask](docs/guides/search-and-ask.md) |

A flag-by-flag command index is at [docs/reference/cli.md](docs/reference/cli.md).
For terminology (change_ref, partial_loc, manifest, sandbox, …) see
[docs/reference/glossary.md](docs/reference/glossary.md).

## Engagement filtering

`ohtv list`, `ohtv gen objs`, `ohtv gen titles`, and `ohtv gen run` all accept
the same four filter flags for selecting conversations by sustained-attention
("engaged human minutes") metrics. The flags are layered on top of every
existing filter (`--repo`, `--pr`, `--label`, `--since` / `--until`, …) and
work identically across `-F table`, `-F json`, and `-F csv` output.

| Flag | Semantics |
|------|-----------|
| `--engaged` | Only conversations with `engaged_seconds > 0`. Missing engagement rows are excluded. |
| `--no-engaged` | Fire-and-forget: keeps rows where `engaged_seconds == 0` **OR** the engagement row is missing entirely. This is the **only** flag that includes missing rows — a never-processed conversation is conservatively treated as un-engaged. |
| `--min-engaged DURATION` | Threshold on `engaged_seconds`. Accepts `30s` / `5m` / `1h` / `1h30m` (case-insensitive) or a bare number interpreted as **minutes** (so `5` ≡ `5m`, **not** `5s`). |
| `--min-engagement-ratio PCT` | Threshold on `engaged_seconds / total_duration_seconds`, expressed as a percentage `[0, 100]`. Rows with `total_duration_seconds == 0` / `NULL` / no engagement row are excluded. |

**Mutual exclusion** (exits with code 2):

- `--engaged` ⊕ `--no-engaged`
- `--no-engaged` ⊕ `--min-engaged` / `--min-engagement-ratio`
- `--engaged` **+** `--min-engaged` / `--min-engagement-ratio` composes silently
  (the threshold implies engaged).

**Examples:**

```bash
# Productivity review: what did I actually steer?
ohtv list --engaged --with-engagement

# Deep-dive sessions from the last week
ohtv list --min-engaged 5m --week

# Re-run objective analysis only for conversations where I was engaged
# at least 25% of the wall-clock — composes with every other filter.
ohtv gen objs --min-engagement-ratio 25 --label status=active

# Auto-title only conversations the agent ran unattended
ohtv gen titles --no-engaged --week
```

**Prerequisite** (same as `--with-engagement` display): engagement data lives in
the `conversation_engagement` table populated by the `engagement` indexing
stage from [#163](https://github.com/jpshackelford/ohtv/issues/163) / [PR
#165](https://github.com/jpshackelford/ohtv/pull/165). Run `ohtv db process
all` (or `ohtv db process engagement` for just this stage) after syncing —
`ohtv sync` does this automatically. Conversations without an engagement row
are excluded by `--engaged`, `--min-engaged`, and `--min-engagement-ratio`,
and **included** by `--no-engaged`.

Full details and per-command flag tables:
[exploration](docs/guides/exploration.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio)
· [analysis](docs/guides/analysis.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio).

## Event-date filtering

By default, `--since` / `--until` / `-D` / `-W` filter against
`conversations.created_at` — when a conversation was *started*. That misses the
conversation you re-opened yesterday but kicked off three weeks ago. The
`--event-dates` flag ([#180](https://github.com/jpshackelford/ohtv/issues/180))
swaps the column under the predicate to `conversation_engagement.first_event_ts`
/ `last_event_ts`, so the same date flags now mean "what was *touched* in the
window."

Available on `list`, `search`, `ask`, `gen objs`, `gen titles`, and `gen run`
(not `refs` — refs are intrinsically action-timestamped).

| Flag | Semantics |
|------|-----------|
| `--event-dates` | Re-interpret existing `--since` / `--until` / `-D` / `-W` against engagement timestamps. With both bounds: interval overlap (`first_event_ts <= until AND last_event_ts >= since`). With one bound: `last_event_ts >= since` or `first_event_ts <= until`. Conversations without an engagement row are **excluded** (INNER JOIN). |

**Round-trip example.** A conversation created `T₀-30d` whose last event landed
at `T₀`:

| Filter | Plain | `--event-dates` |
|---|---|---|
| `--since T₀-7d` | ❌ excluded (created out of range) | ✅ included (last_event_ts in range) |

**Examples:**

```bash
# Conversations re-engaged this week (regardless of when started)
ohtv list --event-dates --week

# Semantic search restricted to recently-touched conversations
ohtv search "auth bug" --event-dates --since 7d

# Regenerate objectives for anything I actually touched in the last month
ohtv gen objs --event-dates --since 1m
```

**Gotchas:**

- `--event-dates` on its own (no date filter) raises `UsageError` (exit 2) — it
  has no defined meaning without `--since` / `--until` / `-D` / `-W`.
- **Prerequisite:** populated `conversation_engagement` rows from the
  `engagement` indexing stage (same as `--engaged` family above). Run `ohtv db
  process engagement` (or `ohtv sync`, which runs all stages). Conversations
  without an engagement row are silently dropped by the INNER JOIN.

Full per-command flag table:
[exploration](docs/guides/exploration.md#filtering-by-event-timestamps---event-dates).

## Listing user messages

`ohtv messages` ([#181](https://github.com/jpshackelford/ohtv/issues/181))
is the third way to find a conversation by what *you* said — the time-shaped
sibling of `ohtv ask` (semantic RAG over embeddings) and `ohtv search` (FTS5
keyword). When you only remember roughly *when* you typed something, this
command lists every user message in a date range, grouped by conversation,
ordered by most-recent activity first. Pagination is **by conversation**:
within a displayed conversation, every matching user message renders.

Date filtering uses **engagement event timestamps**, not
`conversations.created_at` — a conversation started months ago that received a
user message yesterday surfaces under `-D` or `-D 7`. This is the same
column-swap mechanism [`--event-dates`](#event-date-filtering) introduces for
`list` / `search` / `ask`, but for `messages` it is the only mode (no
`--event-dates` flag, no opt-out — per issue scope). The same engagement-row
prerequisite applies (run `ohtv db process engagement` or `ohtv sync`).

```bash
# Default: 10 most recently engaged conversations (no date cap),
# 500-char truncation per message in text mode.
ohtv messages

# Time windows — same shortcuts as `ohtv list` and `ohtv refs`
ohtv messages -D                       # Today
ohtv messages -D 7                     # Last 7 days
ohtv messages -W                       # This week
ohtv messages -W 2                     # Last 2 weeks
ohtv messages --since 2026-05-01 --until 2026-05-31

# Pagination is by conversation; within a shown conversation
# ALL in-range user messages render.
ohtv messages -D 30 -n 25              # First 25 conversations
ohtv messages -D 30 -n 25 -k 25        # Next page (offset 25)
ohtv messages -D 30 -A                 # No cap

# Output formats
ohtv messages -W -F json               # Machine-readable
ohtv messages -D 7 -1                  # `--format raw` shortcut: one
                                       # tab-separated <conv>\t<ts>\t<msg>
                                       # line per message, pipe-friendly
ohtv messages -D 7 -1 | grep -i auth   # Find auth mentions this week
ohtv messages -W --full                # Disable the 500-char truncation

# Conversation-level filters compose
ohtv messages -W --source cloud
ohtv messages -W --repo jpshackelford/ohtv
ohtv messages -W -L status=active
ohtv messages -W --include-sub-conversations  # opt in to delegated subs
```

**Default text output** — one rule line + header per conversation, indented
`[timestamp] message` rows under each, then a pagination footer:

```text
─────────────────────────────────────────────────────────────────
Conversation: a1b2c3d4 — "Implement Authentication Flow"
Created: 2026-05-22 10:15 UTC | Events: 47

[2026-05-22 10:15:03] Can you help me implement OAuth2 authentication...

─────────────────────────────────────────────────────────────────
Showing 2 of 15 candidate conversations (6 messages) | Next: --offset 2
```

`-F json` emits a single object: `{total_conversations, total_messages,
offset, limit, conversations: [{id, title, created_at, source, event_count,
messages: [{timestamp, text}, …]}]}`. JSON and raw modes always carry the
full message text — the 500-char truncation only applies to `text` mode.

**Gotchas:**

- Like `--event-dates` and the `--engaged` family, the date filter runs against
  `conversation_engagement.first_event_ts` / `last_event_ts`. Conversations
  without an engagement row are silently excluded (INNER JOIN). When the
  candidate pool is empty the command prints a hint pointing at
  `ohtv db process engagement` (or `ohtv sync`); when candidates exist but
  the current page is empty (e.g. paged past the message-bearing pool with
  `--offset`) it prints an offset-aware hint instead.
- The footer's `total_messages` counts only the *displayed* conversations —
  pagination is by conversation, so the full-history message count across all
  candidates is intentionally not computed (would defeat the per-invocation
  cost ceiling).

## Configuration

The most common variables:

| Variable | Purpose |
|---|---|
| `OPENHANDS_API_KEY` | Cloud sync (or legacy `OH_API_KEY`) |
| `LLM_API_KEY` | LLM-powered analyses, embeddings, RAG |
| `GITHUB_TOKEN` | `fetch-loc` GitHub API backfill |
| `OHTV_DIR` | Override the `~/.ohtv/` data directory |

Full list, defaults, and precedence rules:
[docs/reference/configuration.md](docs/reference/configuration.md).

### Logs

ohtv writes a rotating log file to `~/.ohtv/logs/ohtv.log` (1 MB, 3
backups). Every command accepts `--log-level {DEBUG,INFO,WARNING,
ERROR,CRITICAL}` (default `INFO`) and `--log-file PATH` (use `-` for
stderr-only). Equivalent env vars: `OHTV_LOG_LEVEL`, `OHTV_LOG_FILE`.
Batch failures from `gen objs`, `db embed`, etc. land in the file log
even under `--quiet`. The legacy `--verbose` flag still works and is
equivalent to `--log-level DEBUG --log-stderr` (with a one-shot
deprecation note). See
[docs/reference/configuration.md#logging](docs/reference/configuration.md#logging).

## Automation

ohtv plays nicely with cron / systemd timers — every long-running command
supports `--quiet`, exits non-zero on errors, and respects environment-only
configuration. Recipes for nightly sync, weekly CSV drops, and
metadata-refresh polling are in
[docs/guides/automation.md](docs/guides/automation.md).

## Documentation

The full docs live in [`docs/`](docs/README.md):

- **Guides** (task-oriented):
  [installation](docs/guides/installation.md) ·
  [getting-started](docs/guides/getting-started.md) ·
  [concepts](docs/guides/concepts.md) ·
  [syncing](docs/guides/syncing.md) ·
  [indexing](docs/guides/indexing.md) ·
  [exploration](docs/guides/exploration.md) ·
  [classification](docs/guides/classification.md) ·
  [analysis](docs/guides/analysis.md) ·
  [reporting](docs/guides/reporting.md) ·
  [search-and-ask](docs/guides/search-and-ask.md) ·
  [customizing-prompts](docs/guides/customizing-prompts.md) ·
  [automation](docs/guides/automation.md)
- **Reference** (lookup):
  [cli](docs/reference/cli.md) ·
  [configuration](docs/reference/configuration.md) ·
  [database](docs/reference/database.md) ·
  [glossary](docs/reference/glossary.md)
- **Design notes** (internal):
  [conversation-metrics](docs/design/conversation-metrics.md) ·
  [rag-citations](docs/design/rag-citations.md) ·
  [temporal-pr-linking](docs/design/temporal-pr-linking.md)
- **Contributing**:
  [testing](docs/contributing/testing.md)

## Project status

Active development, pre-1.0. Surface area is still churning. Issues and PRs
welcome at [github.com/jpshackelford/ohtv](https://github.com/jpshackelford/ohtv/issues).

## License

MIT
