# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories. See `README.md` for full usage documentation.

## Development

```bash
uv sync                    # Install dependencies
uv run ohtv --help         # Run CLI
```

## Code Structure

- `src/ohtv/cli.py` - Main CLI commands (list, show, refs, sync)
- `src/ohtv/config.py` - Configuration management
- `src/ohtv/sync.py` - Cloud sync logic
- `src/ohtv/sources/` - Data sources (local, cloud)
- `src/ohtv/exporter.py` - Output formatting

## Key Design Decisions

1. **Unified data access**: `list` and `show` transparently search both local CLI conversations (~/.openhands/conversations/) and synced cloud conversations (~/.openhands/cloud/conversations/)

2. **Sync-first architecture**: Cloud conversations must be synced locally before viewing (no direct API queries per-request)

3. **Title derivation**: Local conversations derive titles from first user message (first 60 chars, word boundary truncation)

4. **Timezone handling**: Cloud timestamps are UTC; local CLI timestamps lack timezone info. The codebase normalizes to UTC for sorting, then converts to local time for display. **Limitation:** Local timestamps are interpreted using the current machine's timezone—if data moves between machines with different timezones, times may display incorrectly.

## Testing

No automated tests. Manual testing with real conversation data:
```bash
uv run ohtv list -A                    # All conversations
uv run ohtv show <id> -m               # Messages
uv run ohtv show <id> -s -O            # Actions with outputs
uv run ohtv refs <id>                  # Git references
```

## Reference Documentation

- `REFERENCE_CLOUD_API.md` - OpenHands Cloud V1 API endpoints used by sync
- `REFERENCE_TRAJECTORY_FORMAT_COMPARISON.md` - Local vs cloud trajectory formats
