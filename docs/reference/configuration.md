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
| `OHTV_LOG_LEVEL` | Default log level (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`, case-insensitive). Overridden by `--log-level`. | `INFO` |
| `OHTV_LOG_FILE` | Default log destination. Overridden by `--log-file`. Special values: `-` writes to stderr only; `/dev/null` (or `nul` on Windows) silences file logging. | `~/.ohtv/logs/ohtv.log` |
| `LLM_API_KEY` | API key for LLM provider | Required for `gen`, `search`, `ask` |
| `LLM_MODEL` | Default LLM model for `ask` | `openai/gpt-4o-mini` |
| `LLM_BASE_URL` | Custom LLM base URL | Provider default |
| `LLM_TIMEOUT` | LLM request timeout in seconds | `300` |
| `EMBEDDING_MODEL` | Model for embeddings (`db embed`, `search`) | `openai/text-embedding-3-small` |
| `EMBEDDING_API_KEY` | API key for embedding calls (overrides `LLM_API_KEY` for embeddings only) | Falls back to `LLM_API_KEY` |
| `EMBEDDING_BASE_URL` | Base URL for embedding calls (overrides `LLM_BASE_URL` for embeddings only) | Falls back to `LLM_BASE_URL` |
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

ohtv writes logs to `~/.ohtv/logs/ohtv.log` by default:

- Rotates at 1 MB, keeps 3 backups
- Default level is `INFO`
- Format: `YYYY-MM-DD HH:MM:SS LEVEL message` — `grep`/`awk` friendly,
  not strict JSON

### CLI flags

Every command accepts three logging flags (defined once in
`src/ohtv/cli_logging.py::logging_options`):

| Flag | What it does |
|------|--------------|
| `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` | Minimum level for all log handlers. Case-insensitive. |
| `--log-file PATH` | Override the file destination. Use `-` for stderr-only; `/dev/null` (or `nul` on Windows) to silence file logging entirely. |
| `--log-stderr` | Also send log output to stderr (in addition to the file). |

### Resolution order

For each knob: CLI flag → environment variable → built-in default.

```
--log-level   → $OHTV_LOG_LEVEL → INFO
--log-file    → $OHTV_LOG_FILE  → ~/.ohtv/logs/ohtv.log
```

Example — raise level via env var, override on a single command:

```bash
export OHTV_LOG_LEVEL=DEBUG          # all ohtv commands default to DEBUG
ohtv gen objs --log-level WARNING    # this run reverts to WARNING
```

The logging flags belong to each subcommand (so they come AFTER the
subcommand name), not the top-level group:

```bash
ohtv sync --log-level DEBUG --log-stderr     # ✓
ohtv --log-level DEBUG sync                  # ✗ (unknown option at top level)
```

### `--verbose` (deprecated)

The legacy `-v`/`--verbose` flag is preserved for backward compatibility
and behaves as `--log-level DEBUG --log-stderr` plus a one-shot stderr
deprecation note. Two commands keep `--verbose` for *domain* purposes
and not logging: `db init --verbose` (show migration steps) and
`report velocity --verbose` (show rendered SQL). Both also emit the
logging deprecation note when used; use the explicit `--log-level` flag
to control logging on those commands.

### What lands in the log

Batch commands (`gen objs`, `gen titles`, `gen run`, `sync` post-hooks,
`db embed`) **always** record per-item failures to the log file even
when `--quiet` is set — the file handler is independent of the console
output suppressed by `--quiet`. If `ohtv gen objs --quiet` reports
``N err`` and you need to diagnose what failed, look in
``~/.ohtv/logs/ohtv.log`` for the corresponding tracebacks (Issue #121).
