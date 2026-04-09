# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories. See `README.md` for full usage documentation.

## Development

```bash
uv sync                    # Install dependencies
uv run ohtv --help         # Run CLI
```

## Code Structure

- `src/ohtv/cli.py` - Main CLI commands (list, show, refs, sync, objectives, summary)
- `src/ohtv/config.py` - Configuration management
- `src/ohtv/sync.py` - Cloud sync logic
- `src/ohtv/sources/` - Data sources (local, cloud)
- `src/ohtv/exporter.py` - Output formatting
- `src/ohtv/analysis/` - LLM-based analysis features (objectives extraction, summary)

## Key Design Decisions

1. **Unified data access**: `list` and `show` transparently search both local CLI conversations (~/.openhands/conversations/) and synced cloud conversations (~/.openhands/cloud/conversations/)

2. **Sync-first architecture**: Cloud conversations must be synced locally before viewing (no direct API queries per-request)

3. **Title derivation**: Local conversations derive titles from first user message (first 60 chars, word boundary truncation)

4. **Timezone handling**: Cloud timestamps are UTC; local CLI timestamps lack timezone info. The codebase normalizes to UTC for sorting, then converts to local time for display. **Limitation:** Local timestamps are interpreted using the current machine's timezone—if data moves between machines with different timezones, times may display incorrectly.

5. **LLM analysis caching**: The `objectives` and `summary` commands use LLM to analyze conversations but cache results to avoid repeated API calls. Multiple analyses with different parameters (context level, detail level, assess flag) are stored in the same cache file, keyed by their parameter combination. This allows running `objectives` with various options without overwriting previous results. Cache is invalidated when event count changes (conversation grew). The `summary` command uses the most token-efficient settings (minimal context, brief detail) for batch processing.

6. **LLM timeout configuration**: The SDK uses a 300-second (5 minute) default timeout. For very long conversations or slow models, users can increase it via `LLM_TIMEOUT` environment variable (e.g., `export LLM_TIMEOUT=600` for 10 minutes). The CLI shows a spinner during analysis for user feedback.

7. **Human-readable action details**: The `--action-details` (`-d`) flag shows tool actions in human-readable format rather than raw JSON:
   - **terminal**: `$ <command>` (shows the actual shell command)
   - **file_editor**: `view /path/to/file` or `edit /path (str_replace)`
   - **Other tools**: Key parameters in `key=value` format
   
   Use `--debug-tool-call` for raw `tool_call` JSON when debugging LLM outputs.

8. **Output truncation control**: Tool outputs (ObservationEvents) can be shown with:
   - `-o/--trunc-output`: Truncated to 2000 chars (default for quick review)
   - `-O/--full-output`: Full output without truncation (for detailed debugging)
   
   Both options always show exit codes for terminal commands and working directory in debug mode.

## Testing

No automated tests. Manual testing with real conversation data:
```bash
uv run ohtv list -A                    # All conversations
uv run ohtv show <id> -m               # Messages
uv run ohtv show <id> -s -d -o         # Actions with human-readable details and truncated outputs
uv run ohtv show <id> -s -d -O         # Actions with full outputs
uv run ohtv show <id> -s --debug-tool-call  # Debug mode with raw tool_call JSON
uv run ohtv refs <id>                  # Git references
uv run ohtv objectives <id>            # Objective analysis (requires LLM_API_KEY)
uv run ohtv summary -D                 # Today's conversation summaries (requires LLM_API_KEY)
uv run ohtv summary -W                 # This week's summaries
```

## Reference Documentation

- `REFERENCE_CLOUD_API.md` - OpenHands Cloud V1 API endpoints used by sync
- `REFERENCE_TRAJECTORY_FORMAT_COMPARISON.md` - Local vs cloud trajectory formats
