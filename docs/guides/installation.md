# Installation

## Basic install

```sh
pip install ohtv
# or
uv add ohtv
```

Python 3.12+ is required.

## Optional extras

| Extra | Provides | When to install |
|---|---|---|
| `[charts]` | matplotlib | If you want `ohtv report velocity --chart` to write PNG/SVG/PDF figures. The core install stays lightweight without it; the CLI prints a helpful error if you call `--chart` without the extra. |

```sh
pip install 'ohtv[charts]'
```

## API keys

ohtv talks to three external services. Each key is read from the
environment; none are required for all commands.

| Variable | Used by | Required for |
|---|---|---|
| `OPENHANDS_API_KEY` (or `OH_API_KEY`) | `ohtv sync`, cloud listing | Mirroring cloud conversations to disk |
| `LLM_API_KEY` | `ohtv gen *`, `ohtv ask`, embeddings | Any LLM-powered analysis or RAG |
| `GITHUB_TOKEN` | `ohtv fetch-loc` | Backfilling `lines_added` from the GitHub API. Read-only PAT is sufficient; `gh auth token` also works. |

The full configuration reference is in
[reference/configuration.md](../reference/configuration.md).

## Verify the install

```sh
ohtv --version
ohtv --help
```

## Where ohtv writes data

By default, ohtv stores its data under `~/.ohtv/`:

```
~/.ohtv/
├── conversations/    # synced conversation trajectories (JSON)
├── index.db          # SQLite metadata index
├── manifest.json     # cloud-sync manifest
├── prompts/          # user-customized prompts (optional)
├── logs/             # rotating log files
└── cache/            # GitHub API and analysis caches
```

Override the root with the `OHTV_DIR` environment variable.

## Next step

[getting-started.md](getting-started.md) walks through your first sync,
indexing, and analysis end-to-end.
