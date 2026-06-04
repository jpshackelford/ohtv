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
| `ohtv sync` | Mirror cloud conversations to local disk; optionally run the indexing pipeline. Takes the `$OHTV_DIR/sync.lock` writer mutex; pass `--lock-timeout=N` to wait up to N seconds for a contested lock (default `0` = fail-fast). `--status` is read-only and does **not** acquire the lock. | [guides/syncing.md](../guides/syncing.md) |
| `ohtv sync --repair [--dry-run]` | Reconcile local store against the cloud listing. Reports four cloud-vs-local buckets — **New on cloud**, **Missing locally**, **Removed from cloud**, **Modified on cloud** — alongside the legacy ghost / orphan diff. `--dry-run` is a read-only diagnostic and does **not** acquire the lock. Without `--dry-run` it downloads `Missing locally` + refetches `Modified on cloud` (and runs ghost/orphan housekeeping), and acquires the writer mutex; honors `--lock-timeout`. With `--quiet`, exits `1` whenever any bucket is non-empty. | [guides/syncing.md § Repair](../guides/syncing.md#repair-ohtv-sync---repair) |
| `ohtv sync --repair --prune` | Same as `--repair` plus deletion of local conversations whose cloud-side counterpart has disappeared (the `removed_from_cloud` bucket — deletes the DB row, on-disk directory, and manifest entry). Only operates on `source='cloud'` rows. Requires `--repair` (without `--dry-run`); `--prune` outside that combination is a Click `UsageError` (exit `2`). Takes the writer mutex; honors `--lock-timeout`. | [guides/syncing.md § Repair](../guides/syncing.md#repair-ohtv-sync---repair) |
| `ohtv sync --update-metadata` | Refresh cached cloud title/labels/`selected_repository`/`created_at` without re-downloading trajectories. Also takes the writer mutex; honors `--lock-timeout`. | [guides/syncing.md § Metadata refresh](../guides/syncing.md#metadata-refresh---update-metadata) |
| `ohtv db init` | Initialize the SQLite index (idempotent). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db scan` | Register new/changed conversations into the index. Takes the `$OHTV_DIR/sync.lock` writer mutex; pass `--lock-timeout=N` to wait (default `0` = fail-fast). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db process [stage]` | Run an indexing stage (or `all`). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db status` | Print sizes, counts, last-run timestamps. | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db reset` | Delete the index DB (prompts unless `-y`). | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db migrate-cache` | Move legacy cache files to the new location. | [guides/indexing.md](../guides/indexing.md) |
| `ohtv db embed` | Build / refresh vector embeddings for semantic search. | [guides/indexing.md](../guides/indexing.md) |

## Explore

| Command | Purpose | Detailed docs |
|---|---|---|
| `ohtv list` | List conversations with filters (date, PR, repo, action, label). Opt-in `--with-engagement` adds engagement columns (`Engaged` / `Periods` / `Eng%`) to the table and matching fields to JSON / CSV. Engagement-aware row filtering via `--engaged` / `--no-engaged` / `--min-engaged DURATION` / `--min-engagement-ratio PCT` — see [exploration § Engagement filters](../guides/exploration.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio). Both require the [`engagement` stage](../guides/indexing.md#engagement-stage). | [guides/exploration.md § list](../guides/exploration.md) |
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
| `ohtv gen objs` | Extract user objectives per conversation. Opt-in `--with-engagement` adds five engagement fields to JSON output (single-conversation and batch modes) and an `Engaged:` sub-bullet to `-F markdown` output (batch mode); no effect on `-F table`. Batch mode also accepts engagement-aware row filtering via `--engaged` / `--no-engaged` / `--min-engaged DURATION` / `--min-engagement-ratio PCT` — see [analysis § Engagement filters](../guides/analysis.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio). Both require the [`engagement` stage](../guides/indexing.md#engagement-stage). | [guides/analysis.md § gen objs](../guides/analysis.md) |
| `ohtv gen titles` | Auto-rename placeholder-titled cloud conversations from cached `gen objs` analyses. Takes the `$OHTV_DIR/sync.lock` writer mutex (it PATCHes cloud titles and writes back to the manifest + DB); pass `--lock-timeout=N` to wait (default `0` = fail-fast). Accepts the same engagement-aware row filters as `gen objs` (`--engaged` / `--no-engaged` / `--min-engaged` / `--min-engagement-ratio`) — see [analysis § Engagement filters](../guides/analysis.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio). | [guides/analysis.md § gen titles](../guides/analysis.md) |
| `ohtv gen run <job>` | Run a periodic or aggregate analysis job (weekly report, theme discovery, …). Accepts the same engagement-aware row filters as `gen objs` (`--engaged` / `--no-engaged` / `--min-engaged` / `--min-engagement-ratio`) — see [analysis § Engagement filters](../guides/analysis.md#engagement-filters--engaged---no-engaged---min-engaged---min-engagement-ratio). | [guides/analysis.md § gen run](../guides/analysis.md) |
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
