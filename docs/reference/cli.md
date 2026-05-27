# CLI reference (index)

One-line summary for every `ohtv` command, with deep links into the
relevant guide. Run `ohtv <command> --help` for the authoritative,
auto-generated flag list at any version.

> This page is hand-curated. If you spot drift between this index and
> `--help` output, prefer `--help`.

## Top-level

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv --version` | Print version | — |
| `ohtv --help` | Top-level help | — |

## Sync & index

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv sync` | Mirror cloud conversations to local disk; optionally run the indexing pipeline. | [guides/syncing.md](../guides/syncing.md) |
| `ohtv sync --update-metadata` | Refresh cached cloud title/labels/`selected_repository`/`created_at` without re-downloading trajectories. | [guides/syncing.md § Metadata refresh](../guides/syncing.md#metadata-refresh---update-metadata) |
| `ohtv db init` | Initialize the SQLite index (idempotent). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db scan` | Register new/changed conversations into the index. | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db process [stage]` | Run an indexing stage (or `all`). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db status` | Print sizes, counts, last-run timestamps. | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db reset` | Delete the index DB (prompts unless `-y`). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db migrate-cache` | Move legacy cache files to the new location. | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db embed` | Build / refresh vector embeddings for semantic search. | [guides/indexing.md](../guides/indexing.md) |

## Explore

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv list` | List conversations with filters (date, PR, repo, action, label). | [guides/exploration.md § list](../guides/exploration.md) |
| `ohtv show <id>` | Show a single conversation's events, stats, or full transcript. | [guides/exploration.md § show](../guides/exploration.md) |
| `ohtv refs [<id>]` | Extract repos / issues / PRs referenced by one or more conversations. | [guides/exploration.md § refs](../guides/exploration.md) |
| `ohtv errors [<id>]` | Summarize agent/LLM errors in a conversation. | [guides/exploration.md § errors](../guides/exploration.md) |

## Classify

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv classify` | Inspect or override `initial_prompt_source` (cloud/cli) for conversations. | [guides/classification.md](../guides/classification.md) |

## Analyze (LLM)

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv gen objs` | Extract user objectives per conversation. | [guides/analysis.md § gen objs](../guides/analysis.md) |
| `ohtv gen titles` | Auto-rename placeholder-titled cloud conversations from cached `gen objs` analyses. | [guides/analysis.md § gen titles](../guides/analysis.md) |
| `ohtv gen run <job>` | Run a periodic or aggregate analysis job (weekly report, theme discovery, …). | [guides/analysis.md § gen run](../guides/analysis.md) |
| `ohtv prompts list` | List shipped + customized prompts. | [guides/customizing-prompts.md](../guides/customizing-prompts.md) |
| `ohtv prompts show <name>` | Print a prompt's body. | [guides/customizing-prompts.md](../guides/customizing-prompts.md) |
| `ohtv prompts init` | Copy default prompts to `~/.ohtv/prompts/` for customization. | [guides/customizing-prompts.md](../guides/customizing-prompts.md) |
| `ohtv prompts reset [<name>]` | Reset one or all customized prompts to defaults. | [guides/customizing-prompts.md](../guides/customizing-prompts.md) |

## Report

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv report velocity` | Merged-PRs × LOC × human-input by ISO week (table / CSV / chart). | [guides/reporting.md § velocity](../guides/reporting.md#ohtv-report-velocity---weekly-velocity-report) |
| `ohtv report weekly-counts` | New-conversation counts by ISO week (cloud / cli / total CSV). | [guides/reporting.md § weekly-counts](../guides/reporting.md#ohtv-report-weekly-counts---new-conversation-counts-by-week) |
| `ohtv fetch-loc` | Backfill `lines_added` / `lines_removed` from the GitHub REST API into pending `change_refs`. | [guides/reporting.md § fetch-loc](../guides/reporting.md#ohtv-fetch-loc---backfill-prpush-loc-from-github) |

## Search & Q&A

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv search <query>` | Semantic or FTS5 keyword search across conversations. | [guides/search-and-ask.md § search](../guides/search-and-ask.md) |
| `ohtv ask <question>` | RAG-powered question-answerer with optional multi-step agent mode. | [guides/search-and-ask.md § ask](../guides/search-and-ask.md) |
| `ohtv config-embed` | Inspect / change the embedding model used by `db embed` + `search` + `ask`. | [guides/indexing.md](../guides/indexing.md) |

## Config

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv config` | View and manage ohtv configuration. | [reference/configuration.md](configuration.md) |
