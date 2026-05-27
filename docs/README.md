# ohtv documentation

User-facing docs for the [ohtv CLI](../README.md).

## Guides (task-oriented)

Start here if you're using ohtv for the first time or want a walkthrough
of a specific workflow.

- [installation.md](guides/installation.md) — install, optional extras, API keys
- [getting-started.md](guides/getting-started.md) — 5-minute first sync + first analysis
- [concepts.md](guides/concepts.md) — cloud vs CLI conversations, the indexing pipeline, change_refs, sources
- [syncing.md](guides/syncing.md) — `ohtv sync`, incremental + metadata refresh + repair
- [indexing.md](guides/indexing.md) — `ohtv db scan` / `db process` / stages / migrate-cache / embeddings
- [exploration.md](guides/exploration.md) — `ohtv list`, `show`, `refs`, `errors`
- [classification.md](guides/classification.md) — `ohtv classify`
- [analysis.md](guides/analysis.md) — `ohtv gen` (objectives, summaries, aggregate jobs, titles)
- [customizing-prompts.md](guides/customizing-prompts.md) — `ohtv prompts`
- [reporting.md](guides/reporting.md) — `ohtv report velocity`, `weekly-counts`, `--chart`, `fetch-loc`
- [search-and-ask.md](guides/search-and-ask.md) — `ohtv search`, `ohtv ask` (RAG + agent mode)
- [automation.md](guides/automation.md) — cron jobs, `--quiet`, exit codes, env-var precedence

## Reference (lookup)

- [cli.md](reference/cli.md) — every command and flag, in one searchable page
- [configuration.md](reference/configuration.md) — env vars, data directories, logging
- [database.md](reference/database.md) — SQLite schema and table-by-table reference
- [glossary.md](reference/glossary.md) — terms: change_ref, partial_loc, manifest, action, sandbox, …

## Design notes (internal)

Architecture decisions, alternatives considered, and known issues. These
are for maintainers and future-self, not first-time users.

- [conversation-metrics.md](design/conversation-metrics.md)
- [conversation-metrics-issues.md](design/conversation-metrics-issues.md)
- [rag-citations.md](design/rag-citations.md)
- [temporal-pr-linking.md](design/temporal-pr-linking.md)

## Contributing

- [testing.md](contributing/testing.md) — running tests, fixtures, conventions
- [manual-qa-pr18.md](contributing/manual-qa-pr18.md) — historical QA plan, kept for reference
