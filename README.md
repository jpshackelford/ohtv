# ohtv — OpenHands Trajectory Viewer

A CLI for syncing, indexing, analyzing, and reporting on
[OpenHands](https://github.com/All-Hands-AI/OpenHands) conversation
trajectories — from both the cloud product and local CLI sessions.

- 🔄 **Sync** cloud conversations to disk (incremental, with metadata refresh; includes
  delegated sub-conversations by default since [#108](https://github.com/jpshackelford/ohtv/pull/134))
- 📚 **Index** them into a local SQLite database (refs, actions, contributions, human input)
- 🤖 **Analyze** with LLMs (objectives, summaries, weekly reports, auto-titles)
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
| **Search & ask** | `search`, `ask` | [search-and-ask](docs/guides/search-and-ask.md) |

A flag-by-flag command index is at [docs/reference/cli.md](docs/reference/cli.md).
For terminology (change_ref, partial_loc, manifest, sandbox, …) see
[docs/reference/glossary.md](docs/reference/glossary.md).

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
