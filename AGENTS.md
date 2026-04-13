# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories. See `README.md` for full command reference and usage documentation.

## Development

```bash
uv sync                    # Install dependencies
uv run ohtv --help         # Run CLI
```

## Code Structure

- `src/ohtv/cli.py` - Main CLI commands (list, show, refs, sync, objectives, summary, db)
- `src/ohtv/config.py` - Configuration management
- `src/ohtv/sync.py` - Cloud sync logic
- `src/ohtv/sources/` - Data sources (local, cloud)
- `src/ohtv/exporter.py` - Output formatting
- `src/ohtv/analysis/` - LLM-based analysis features (objectives extraction, summary)
- `src/ohtv/db/` - SQLite-based indexing for conversation labeling

## Architecture & Design Decisions

These decisions explain WHY the code is structured as it is. See `README.md` for command usage.

1. **Unified data access**: `list` and `show` transparently search both local CLI conversations (~/.openhands/conversations/) and synced cloud conversations (~/.openhands/cloud/conversations/)

2. **Sync-first architecture**: Cloud conversations must be synced locally before viewing (no direct API queries per-request)

3. **Title derivation**: Local conversations derive titles from first user message (first 60 chars, word boundary truncation)

4. **Timezone handling**: Cloud timestamps are UTC; local CLI timestamps lack timezone info. The codebase normalizes to UTC for sorting, then converts to local time for display. **Limitation:** Local timestamps are interpreted using the current machine's timezone - if data moves between machines with different timezones, times may display incorrectly.

5. **LLM analysis caching**: The `objectives` and `summary` commands cache results keyed by parameter combination (context level, detail level, assess flag). Cache invalidates when event count changes (conversation grew). The `summary` command uses minimal context + brief detail for token efficiency.

6. **LLM timeout**: Default 300s. Override with `LLM_TIMEOUT` env var. CLI shows spinner during analysis.

7. **Human-readable action details**: `-d` flag formats tool calls for readability (e.g., `$ git status` for terminal). Use `--debug-tool-call` for raw JSON.

8. **Output truncation**: `-o` truncates to 2000 chars; `-O` shows full output. Both show exit codes.

9. **SQLite indexing**: Lightweight index for conversations and relationships. See `docs/DATABASE.md`. Key points:
   - Minimal footprint: metadata only, content stays on filesystem
   - Two-phase: `db scan` (fast registration) + `db process <stage>` (incremental)
   - Change detection: mtime as fast filter, event_count as checkpoint
   - Auto-indexing: `refs <id>` indexes automatically

10. **Data directory separation**:
    - `~/.openhands/`: Read-only source data (only `sync` writes here)
    - `~/.ohtv/`: All ohtv-generated data (database, logs, cache). Override with `OHTV_DIR`.

11. **Filter matching**: PR/repo/action filters require indexed database (`db scan && db process all`). PR filter uses precise matching (`#1` won't match `#10`). Action+repo combined filter uses target URLs when available.

12. **Conversation ID normalization**: Database stores IDs without dashes; LocalSource returns with dashes. The `filters` module normalizes both formats.

13. **Terminal confirmation prompts**: Use Rich's `Confirm.ask()` with the same console instance:
    ```python
    from rich.prompt import Confirm
    if not Confirm.ask("Are you sure?", console=console, default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    ```

## Troubleshooting

### Terminal shows `^M^M^M` when typing input

Terminal is in corrupted state (usually after OpenHands CLI exits improperly).

**Fix:** Run `reset` or `stty sane`. The `clear` command does NOT fix this.

## Testing

```bash
# Unit tests (see docs/TESTING.md)
uv run pytest tests/unit/db -v
uv run pytest tests/unit/test_filters.py -v

# Manual testing - see README.md for full command reference
uv run ohtv list -A                    # All conversations
uv run ohtv show <id> -m               # Messages
uv run ohtv show <id> -s -d -o         # Actions with details + outputs
uv run ohtv refs <id>                  # Git references
uv run ohtv db status                  # Database statistics
```

## Reference Documentation

- `README.md` - Full command reference and usage
- `docs/DATABASE.md` - SQLite indexing system
- `docs/TESTING.md` - Test infrastructure
- `REFERENCE_CLOUD_API.md` - OpenHands Cloud V1 API endpoints
- `REFERENCE_TRAJECTORY_FORMAT_COMPARISON.md` - Local vs cloud trajectory formats
