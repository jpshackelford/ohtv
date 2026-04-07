# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories.

## Quick Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run ohtv --help
uv run ohtv list
uv run ohtv show <conversation_id>
uv run ohtv refs <conversation_id>
uv run ohtv sync
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

4. **Timezone handling**: Cloud conversation timestamps are stored in UTC, while local CLI timestamps are in local time. The codebase normalizes all timestamps to UTC internally for correct chronological sorting, then converts to local time for display.

## Specifications in Progress

- `SPEC_REFS_INTERACTION_TYPES.md` - Enhancement to detect whether we pushed/created/commented on PRs and issues

## Testing

Currently no automated tests. Use manual testing with real conversation data:
```bash
uv run ohtv list
uv run ohtv show <id>                  # Stats only
uv run ohtv show <id> --messages       # User + agent messages + finish
uv run ohtv show <id> -s -O            # Actions with outputs
uv run ohtv show <id> -A               # Everything
uv run ohtv show <id> -F json          # JSON output
uv run ohtv refs <id>
```

## Show Command Details

The `show` command supports extensive filtering:

**Content flags:**
- `-u` user messages, `-a` agent messages, `-f` finish
- `-s` action summaries, `-d` action details, `-O` outputs
- `-t` thinking blocks, `-T` timestamps
- `-m` shorthand for `-u -a -f`, `-A` everything

**Display options:**
- `-r` reverse order, `-n` limit, `-k` offset
- `-F markdown|json|text`, `-o` output file

## Environment Variables

- `OH_API_KEY` - Required for cloud sync
- `OHTV_CONVERSATIONS_DIR` - Override local conversations path
- `OHTV_CLOUD_CONVERSATIONS_DIR` - Override cloud conversations path
