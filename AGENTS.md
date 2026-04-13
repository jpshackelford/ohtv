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

12. **Conversation ID normalization**: Database stores IDs without dashes; LocalSource returns with dashes. The `filters` module and `_find_conversation_dir` normalize both formats (removing dashes before directory lookup).

13. **Refs command dual mode**: The `refs` command supports two modes:
    - **Single conversation mode**: `refs <id>` - Shows rich display with interaction annotations
    - **Multi-conversation mode**: `refs -D` (or other filters) - Aggregates and deduplicates refs across conversations
    - Machine-readable formats (`-1`, `--format lines|csv|json`) suppress rich output for automation

14. **Terminal confirmation prompts**: Use Rich's `Confirm.ask()` with the same console instance:
    ```python
    from rich.prompt import Confirm
    if not Confirm.ask("Are you sure?", console=console, default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    ```

15. **Branch and PR tracking**: 
    - **Branch refs**: Branches are first-class refs (like issues/PRs). The `branch_context` stage creates branch refs from GIT_PUSH actions
    - **Push-PR linking**: The `push_pr_links` stage correlates pushes with PRs via branch matching
    - **Conservative approach**: Only links when full owner/repo/branch qualification exists on both sides
    - **Current limitation**: Temporal ordering not yet implemented (pushes before PR creation don't link correctly)
    - **Design doc**: See `docs/DESIGN_TEMPORAL_PR_LINKING.md` for planned improvements

16. **Processing stage order**: `refs → actions → branch_context → push_pr_links`
    - Each stage can run independently but has dependencies
    - `all` runs all stages in correct order

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
uv run ohtv refs <id>                  # Git references (rich display)
uv run ohtv refs -D --prs-only -1      # Today's PRs, one per line
uv run ohtv refs -W --format json      # This week's refs as JSON
uv run ohtv db status                  # Database statistics
```

## Reference Documentation

- `README.md` - Full command reference and usage
- `docs/DATABASE.md` - SQLite indexing system
- `docs/TESTING.md` - Test infrastructure
- `docs/DESIGN_TEMPORAL_PR_LINKING.md` - Design for temporal push-PR linking (next phase)
- `REFERENCE_CLOUD_API.md` - OpenHands Cloud V1 API endpoints
- `REFERENCE_TRAJECTORY_FORMAT_COMPARISON.md` - Local vs cloud trajectory formats

## Completed: Temporal PR Linking

**Branch**: `feature/sqlite-indexing`

**Implemented features**:
1. ✅ Temporal forward linking: Pushes after PR creation link to active PR per branch
2. ✅ Backward pass: Pushes before PR creation link to first subsequent PR on same branch
3. ✅ Tested with real conversation `a711cbbc61f0` (all 6 PRs have WRITE links)
4. ✅ 216 tests passing

**Key implementation details**:
- `push_pr_links.py` processes events in temporal order (by action ID)
- Tracks "active PR" per branch key (`owner/repo:branch`)
- Orphan pushes (before any PR) are collected and linked in backward pass
- Requires actions stage to be reprocessed if data has ANSI escape codes in branch names

**Test fixtures**: `tests/unit/db/stages/fixtures/push_pr_scenarios.py` contains sanitized scenarios documenting expected behavior.

**Known issue**: The `refs` command display shows `[created]` but not `[pushed]` annotation because the display code uses event parsing instead of database links. The WRITE links are correctly stored in the database.

## Completed: Git Checkout Branch Tracking

**Branch**: `feature/sqlite-indexing`

**Problem solved**: When `git push` doesn't have branch info in command or output (e.g., "Everything up-to-date"), we now infer the branch from prior `git checkout` or `git switch` commands.

**Implementation**:
- `extract_working_directory()` - Extracts path from `cd /path && git...` patterns
- `extract_checkout_branch()` - Extracts branch from checkout/switch command + output
- `is_checkout_command()` - Detects git checkout/switch commands
- `find_checkout_branch_for_path()` - Searches backward through events for last checkout
- Push recognition now uses checkout inference when no branch in output

**Tests**: 244 total tests passing (28 new for checkout tracking)
- `TestExtractWorkingDirectory` - 6 tests
- `TestExtractCheckoutBranch` - 8 tests
- `TestIsCheckoutCommand` - 7 tests
- `TestFindCheckoutBranchForPath` - 5 tests
- `TestCheckoutInferenceInPush` - 2 integration tests

**Fixture data**: `tests/unit/db/stages/fixtures/checkout_scenarios.py` - 8 scenarios

**Key features**:
- Tracks branch state per repo path independently
- Handles detached HEAD state (returns None)
- Supports both `git checkout` and `git switch` variants
- Prefers push output over checkout inference when available
- Marks inferred branches with `branch_inferred: true` in metadata
