# Getting started — 5-minute walkthrough

This walkthrough takes you from a fresh install to a first velocity report.
It assumes you've already [installed ohtv](installation.md).

## 1. Sync cloud conversations

```sh
export OPENHANDS_API_KEY=...   # from app.all-hands.dev settings
ohtv sync --process
```

`--process` runs the indexing pipeline immediately after the download so
you're ready to query. The first run pulls everything; subsequent runs are
incremental.

If you only use the local OpenHands CLI (no cloud), skip this — ohtv will
discover CLI conversations automatically on the first `db scan`. See
[syncing.md](syncing.md) and [concepts.md](concepts.md#cloud-vs-cli-conversations).

## 2. See what landed

```sh
ohtv list                # 10 most recent
ohtv list --since today
ohtv list --pr 106       # conversations that touched a specific PR
```

`ohtv show <id>` opens any conversation in detail; `ohtv refs <id>` lists
the GitHub repos / issues / PRs it touched. See
[exploration.md](exploration.md) for the full set.

## 3. Backfill LOC from GitHub (optional, but powerful)

```sh
export GITHUB_TOKEN=$(gh auth token)
ohtv fetch-loc
```

This pulls `lines_added` / `lines_removed` / `merged_at` from the GitHub
REST API for every PR/push your conversations contributed. Cached and
idempotent — safe to re-run.

## 4. Run an LLM analysis

```sh
export LLM_API_KEY=...   # OpenAI / Anthropic / via LiteLLM
ohtv gen objs            # extract user objectives from recent conversations
```

For aggregate jobs (weekly themes, summaries) see
[analysis.md](analysis.md#ohtv-gen-run---run-aggregate-analysis-jobs).

## 5. See velocity by week

```sh
ohtv report velocity                      # table
ohtv report velocity --format csv > v.csv
ohtv report velocity --chart velocity.png \
    --since 12w --mark-date 2026-04-15
```

[reporting.md](reporting.md) covers the chart layout, the NULL-vs-zero
LOC convention, and the `weekly-counts` companion command.

## 6. Search & ask questions (optional)

After running `ohtv db embed` once to build the vector index:

```sh
ohtv search "matplotlib lazy import"
ohtv ask "why did we choose SQLite over DuckDB?"
ohtv ask "what blocked PR #106 today?" --agent
```

See [search-and-ask.md](search-and-ask.md).

## Where to go next

- [concepts.md](concepts.md) — terminology, pipeline overview, the data model
- [reference/cli.md](../reference/cli.md) — every command + flag in one page
- [automation.md](automation.md) — running ohtv as a cron job
- [customizing-prompts.md](customizing-prompts.md) — make the LLM analyses match your team's voice
