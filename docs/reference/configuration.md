# Configuration reference

Environment variables, data directories, and logging.

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENHANDS_API_KEY` | OpenHands Cloud API key (preferred, matches OpenHands CLI) | Required for `sync` |
| `OH_API_KEY` | OpenHands Cloud API key (legacy, fallback if `OPENHANDS_API_KEY` not set) | — |
| `OHTV_CLOUD_URL` | Cloud base URL | `https://app.all-hands.dev` |
| `OHTV_DIR` | ohtv data directory (database, logs, cache) | `~/.ohtv` |
| `OHTV_DB_PATH` | Direct path to database file | `~/.ohtv/index.db` |
| `OHTV_CONVERSATIONS_DIR` | Local CLI conversations directory | `~/.openhands/conversations` |
| `OHTV_CLOUD_CONVERSATIONS_DIR` | Synced cloud conversations directory | `~/.openhands/cloud/conversations` |
| `OHTV_EXTRA_CONVERSATION_PATHS` | Additional conversation directories (colon-separated paths) | None |
| `OHTV_LOG_LEVEL` | Override default log level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |
| `LLM_API_KEY` | API key for LLM provider | Required for `gen`, `search`, `ask` |
| `LLM_MODEL` | Default LLM model for `ask` | `openai/gpt-4o-mini` |
| `LLM_BASE_URL` | Custom LLM base URL | Provider default |
| `LLM_TIMEOUT` | LLM request timeout in seconds | `300` |
| `EMBEDDING_MODEL` | Model for embeddings (`db embed`, `search`) | `openai/text-embedding-3-small` |
| `GITHUB_TOKEN` | GitHub PAT (read-only is fine) or `gh auth token` output | Required for `fetch-loc` (non-dry-run) |

### Precedence

For keys with both an OpenHands-flavored and a generic alias (e.g.
`OPENHANDS_API_KEY` vs `OH_API_KEY`), the preferred name wins if both are
set. Legacy aliases are kept indefinitely for backward compatibility.

## Data directories

ohtv reads from one tree and writes to another:

- **`~/.openhands/`** — OpenHands source data (read-only for ohtv, except `sync` which writes synced cloud conversations under `cloud/conversations/`)
  - `conversations/` — Local CLI conversations
  - `cloud/conversations/` — Synced cloud conversations
- **`~/.ohtv/`** — ohtv-generated data (override with `OHTV_DIR`)
  - `index.db` — SQLite metadata index
  - `manifest.json` — Cloud sync state cache (see [concepts § Manifest](../guides/concepts.md#key-data-model-objects))
  - `logs/ohtv.log` — Application logs
  - `prompts/` — User-customized prompts (created by `ohtv prompts init`)
  - `cache/` — GitHub API and analysis caches

Both trees are safe to delete (you'll lose customizations and have to
re-sync, but no source data lives only in `~/.ohtv/`).

## Logging

ohtv writes structured logs to `~/.ohtv/logs/ohtv.log`:

- Rotates at 1 MB, keeps 3 backups
- INFO level by default
- `-v` / `--verbose` on any command also prints DEBUG to console
- `OHTV_LOG_LEVEL=DEBUG` raises the file-log level globally

The log format is `timestamp | level | logger | message` — readable with
`grep`/`awk` but not strict JSON. For machine-readable output, use
`--format json` / `--format csv` on the command itself.
