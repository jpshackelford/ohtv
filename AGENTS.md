# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories. See `README.md` for full command reference and usage documentation.

## Development

```bash
uv sync                    # Install dependencies
uv run ohtv --help         # Run CLI
```

## Code Structure

- `src/ohtv/cli.py` - Main CLI commands (list, show, refs, errors, sync, gen, db, prompts)
- `src/ohtv/config.py` - Configuration management
- `src/ohtv/sync.py` - Cloud sync logic
- `src/ohtv/sources/` - Data sources (local, cloud)
- `src/ohtv/exporter.py` - Output formatting
- `src/ohtv/errors.py` - Agent/LLM error analysis (ConversationErrorEvent, AgentErrorEvent)
- `src/ohtv/analysis/` - LLM-based analysis features (objectives extraction)
- `src/ohtv/prompts/` - Customizable LLM prompt templates (markdown files)
- `src/ohtv/db/` - SQLite-based indexing for conversation labeling

## Architecture & Design Decisions

These decisions explain WHY the code is structured as it is. See `README.md` for command usage.

1. **Unified data access**: `list` and `show` transparently search both local CLI conversations (~/.openhands/conversations/) and synced cloud conversations (~/.openhands/cloud/conversations/)

2. **Sync-first architecture**: Cloud conversations must be synced locally before viewing (no direct API queries per-request)

3. **Sync state repair**: The `ohtv sync --repair` command checks and fixes sync state consistency:
   - Compares manifest entries vs actual files on disk
   - Queries cloud API for total conversation count
   - Reports ghost entries (in manifest but not on disk) and orphaned files (on disk but not in manifest)
   - With `--dry-run`, only reports; without, repairs by updating manifest

4. **Title derivation**: Local conversations derive titles from first user message (first 60 chars, word boundary truncation)

5. **Timezone handling**: Cloud timestamps are UTC; local CLI timestamps lack timezone info. The codebase normalizes to UTC for sorting, then converts to local time for display. **Limitation:** Local timestamps are interpreted using the current machine's timezone - if data moves between machines with different timezones, times may display incorrectly.

6. **LLM analysis caching**: The `gen objs` command caches results keyed by parameter combination (context level, detail level, assess flag). Cache invalidates when event count changes (conversation grew) or when the prompt file changes (detected via prompt hash). Multi-conversation mode (batch) uses minimal context + brief detail for token efficiency.

7. **LLM timeout**: Default 300s. Override with `LLM_TIMEOUT` env var. CLI shows spinner during analysis.

8. **LLM cost tracking**: `analyze_objectives()` returns an `AnalysisResult` dataclass containing `analysis` (ObjectiveAnalysis), `cost` (float, dollars), and `from_cache` (bool). The `gen objs` command (batch mode) displays running cost in the progress bar during analysis and shows total cost after completion. Cost is obtained from `response.metrics.accumulated_cost` via the OpenHands SDK LLM class.

9. **Human-readable action details**: `-d` flag formats tool calls for readability (e.g., `$ git status` for terminal). Use `--debug-tool-call` for raw JSON.

10. **Output truncation**: `-o` truncates to 2000 chars; `-O` shows full output. Both show exit codes.

11. **SQLite indexing**: Lightweight index for conversations and relationships. See `docs/DATABASE.md`. Key points:
    - Minimal footprint: metadata only, content stays on filesystem
    - Two-phase: `db scan` (fast registration) + `db process <stage>` (incremental)
    - Change detection: mtime as fast filter, event_count as checkpoint
    - Auto-indexing: `refs <id>` indexes automatically
    - **Automatic processing**: `ohtv sync` always runs all processing stages after syncing
    - **Stage order**: refs → actions → branch_context → push_pr_links (defined in `stages/__init__.py`)
    - **Dependency caveat**: Stages don't validate dependencies - running a stage before its dependencies completes successfully but does nothing useful (marks itself complete with empty results). Always use `db process all` to ensure correct ordering.

12. **Data directory separation**:
    - `~/.openhands/`: Read-only source data (only `sync` writes here)
    - `~/.ohtv/`: All ohtv-generated data (database, logs, cache). Override with `OHTV_DIR`.

13. **Filter matching**: PR/repo/action filters require indexed database (`db scan && db process all`). PR filter uses precise matching (`#1` won't match `#10`). Action+repo combined filter uses target URLs when available.

14. **Conversation ID normalization**: Database stores IDs without dashes; LocalSource returns with dashes. The `filters` module and `_find_conversation_dir` normalize both formats (removing dashes before directory lookup).

15. **Refs command dual mode**: The `refs` command supports two modes:
    - **Single conversation mode**: `refs <id>` - Shows rich display with interaction annotations
    - **Multi-conversation mode**: `refs -D` (or other filters) - Aggregates and deduplicates refs across conversations
    - Machine-readable formats (`-1`, `--format lines|csv|json`) suppress rich output for automation

16. **Terminal confirmation prompts**: Use Rich's `Confirm.ask()` with the same console instance:
    ```python
    from rich.prompt import Confirm
    if not Confirm.ask("Are you sure?", console=console, default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    ```

17. **Branch and PR tracking**: 
    - **Branch refs**: Branches are first-class refs (like issues/PRs). The `branch_context` stage creates branch refs from GIT_PUSH actions
    - **Push-PR linking**: The `push_pr_links` stage correlates pushes with PRs via branch matching
    - **Conservative approach**: Only links when full owner/repo/branch qualification exists on both sides
    - **Current limitation**: Temporal ordering not yet implemented (pushes before PR creation don't link correctly)
    - **Design doc**: See `docs/DESIGN_TEMPORAL_PR_LINKING.md` for planned improvements

18. **Processing stage order**: `refs → actions → branch_context → push_pr_links`
    - Each stage can run independently but has dependencies
    - `all` runs all stages in correct order

19. **Error analysis**: The `errors` module (`src/ohtv/errors.py`) tracks agent/LLM errors that impact agent behavior:
    - **ConversationErrorEvent**: Terminal errors (LLM errors, budget exceeded, API failures)
    - **AgentErrorEvent**: Agent-level errors (sandbox restarts, tool validation failures)
    - Does NOT track routine terminal command failures (non-zero exit codes)
    - Errors are classified as TERMINAL (conversation stopped) or RECOVERED (agent continued)
    - Used by `ohtv errors <id>` command and `ohtv list --errors-only` filter

20. **LLM analysis performance timing**: The `analysis/objectives.py` module has timing instrumentation. Check `~/.ohtv/logs/ohtv.log` for entries like:
    ```
    TIMING load_events: 11.3ms
    TIMING import_sdk: 1962.5ms
    TIMING llm_completion: 9152.9ms
    Analysis complete and cached (cost: $0.0074, total: 11223.0ms)
    ```
    **Performance breakdown** (typical):
    - `llm_completion`: ~90% of time (8-15 seconds per request)
    - `import_sdk`: ~2 seconds on cold start (first request only)
    - Event loading/transcript building: <100ms
    - Cache operations: <10ms

21. **Parallel processing**: Multiple commands use parallel processing with 20 workers:
    - **`gen objs`** (batch mode): Parallel LLM analysis of conversations
    - **`sync`**: Parallel download of conversations from cloud
    - **`db embed`**: Parallel embedding generation
    
    All use `ThreadPoolExecutor` with thread-safe counters. **Graceful shutdown**: SIGINT/SIGTERM signals are caught - in-flight requests complete before exit, preventing data corruption. **Progress display**: Rich progress bar shows processing rate.
    
    The `ohtv.parallel` module provides shared utilities:
    - `format_rate(count, elapsed, unit)` - Format processing rate
    - `RateTracker` - Thread-safe rate tracking with smoothing
    - `run_parallel(items, process_fn, ...)` - Generic parallel execution helper

22. **Model configuration**: LLM model can be set via:
    - CLI: `--model/-m` option on `gen objs` command
    - Environment: `LLM_MODEL` env var (used by SDK's `LLM.load_from_env()`)
    - Try `haiku` for faster/cheaper analysis, `opus` for higher quality

23. **Analysis cache indexing**: The database tracks LLM analysis cache state for fast lookup. Key tables:
    - `analysis_cache`: Tracks which conversations have cached analysis (by cache_key, event_count, content_hash)
    - `analysis_skips`: Tracks conversations that cannot be analyzed (no events, no content)
    - **520x speedup**: Cache status check via DB (4ms for 700+ convs) vs loading event files (2+ seconds)
    - **Backfill**: Run `ohtv db index-cache` to populate DB from existing cache files
    - **Auto-sync**: Cache entries automatically sync to DB when `gen objs` command saves results
    - **Cache key format**: `assess=False,context_level=minimal,detail_level=brief` (sorted alphabetically)

24. **Database-first conversation listing**: The database stores full conversation metadata for fast listing:
    - Columns: `title`, `created_at`, `updated_at`, `selected_repository`, `source`
    - **45x speedup**: List with date filter via DB (15ms) vs filesystem scanning (3.8s for 1000+ convs)
    - **Auto-populated**: `db scan` extracts metadata from event files
    - **Graceful fallback**: Uses filesystem if DB unavailable or metadata not populated
    - Date filtering is pushed down to DB query when available

25. **Automatic database maintenance**: The system automatically runs migrations and maintenance tasks:
    - **No manual intervention**: Users never need to run `db scan --force` or know about migrations
    - **Maintenance tracking**: `maintenance_tasks` table tracks what's been done
    - **One-time tasks**: Metadata backfill and cache indexing run automatically after their migrations
    - **Progress display**: Long-running tasks show progress bars
    - **Implementation**: `ensure_db_ready()` in `db/maintenance.py` handles all maintenance

26. **Customizable prompts**: LLM analysis prompts are stored as markdown files for user customization:
    - **Default prompts**: `src/ohtv/prompts/*.md` - 6 prompt variants (brief, standard, detailed × assess/no-assess)
    - **User prompts**: `~/.ohtv/prompts/*.md` - Override defaults by copying and editing
    - **Load order**: User prompts checked first, then package defaults
    - **Management**: `ohtv prompts` command for init/list/show/reset operations
    - **Implementation**: `get_prompt(name)` and `get_prompt_hash(name)` in `ohtv/prompts/__init__.py`
    - **Cache invalidation**: Prompt hash (SHA256, first 16 chars) is stored with cached analysis; cache invalidates when prompt content changes

## Troubleshooting

### Terminal shows `^M^M^M` when typing input

Terminal is in corrupted state (usually after OpenHands CLI exits improperly).

**Fix:** Run `reset` or `stty sane`. The `clear` command does NOT fix this.

## Testing

```bash
# Unit tests (see docs/TESTING.md)
uv run python -m pytest tests/unit/db -v
uv run python -m pytest tests/unit/test_filters.py -v
uv run python -m pytest tests/unit/test_errors.py -v

# Manual testing - see README.md for full command reference
uv run ohtv list -A                    # All conversations (refs shown by default)
uv run ohtv list -A --idle             # Show idle time (red < 7m, green >= 7m)
uv run ohtv list -A --idle 15          # Custom idle threshold (15 min)
uv run ohtv list -A --no-refs          # Hide refs from title column
uv run ohtv show <id> -m               # Messages
uv run ohtv show <id> -s -d -o         # Actions with details + outputs
uv run ohtv refs <id>                  # Git references (rich display)
uv run ohtv refs -D --prs-only -1      # Today's PRs, one per line
uv run ohtv refs -W --format json      # This week's refs as JSON
uv run ohtv errors <id>                # Agent/LLM error summary
uv run ohtv list --errors-only         # List conversations with errors
uv run ohtv db status                  # Database statistics
uv run ohtv db embed                   # Build embeddings for semantic search
uv run ohtv db embed --estimate        # Show cost estimate for embedding
uv run ohtv search "fix auth bugs"     # Semantic search across conversations
uv run ohtv search "error 404" --exact # Keyword search (FTS5)
uv run ohtv prompts                    # List prompt status
uv run ohtv prompts init               # Copy prompts for customization
uv run ohtv prompts show brief         # Show specific prompt content
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

## Completed: Semantic Search with Embeddings + RAG

**PR**: #25 (implements issue #1)

**Features**:
1. ✅ Multi-type embeddings: analysis, summary, content (chunked)
2. ✅ RAG question answering via `ohtv ask`
3. ✅ Automatic embedding updates when `gen objs` runs
4. ✅ Refs (PRs, repos, issues) included in summary embeddings
5. ✅ File contents included in content embeddings
6. ✅ FTS5 keyword search fallback with `--exact` flag
7. ✅ Temporal filtering in RAG (issue #29)
8. ✅ 25+ tests for embedding store and search

## Completed: Temporal Filtering for RAG (Issue #29)

**Problem solved**: Questions like "What did we work on yesterday?" now filter to the appropriate time period instead of returning results based purely on semantic similarity.

**Implementation**:
- `src/ohtv/analysis/temporal.py` - Temporal query extraction module
  - `TemporalQuery` dataclass with start_date, end_date, cleaned_query, has_temporal_intent
  - `extract_temporal_filter()` - Fast regex-based extraction for common patterns (yesterday, last week, past N days)
  - Falls back to LLM extraction for complex patterns when needed
- `src/ohtv/db/stores/embedding_store.py` - Date filtering via JOIN with conversations table
  - `search()`, `search_conversations()`, `get_context_for_rag()` all accept optional `start_date` and `end_date`
- `src/ohtv/analysis/rag.py` - RAGAnswerer uses temporal extraction
  - Auto-extracts dates from question, uses cleaned query for embedding
  - Falls back to unfiltered search if temporal filter returns no results
- `src/ohtv/filters.py` - `parse_date_filter()` for CLI date parsing
  - Supports: YYYY-MM-DD, Nd (7d), Nw (2w), Nm (1m), "today", "yesterday"

**CLI options** (`ohtv ask`):
- `--since` - Explicit start date filter (YYYY-MM-DD or relative: 7d, 2w, 1m)
- `--until` - Explicit end date filter (YYYY-MM-DD)
- `--no-temporal` - Disable automatic temporal extraction from question

**Examples**:
```bash
ohtv ask "what did we work on yesterday?"          # Auto-filtered to yesterday
ohtv ask "show me last week's API changes"         # Auto-filtered to last 7 days
ohtv ask "summarize deployment work" --since 7d   # Explicit: last 7 days
ohtv ask "recent issues" --no-temporal            # Disable auto-filter
```

**Tests**: 56 new tests
- 21 tests for temporal extraction (`tests/unit/analysis/test_temporal.py`)
- 10 tests for date parsing (`tests/unit/test_date_filters.py`)
- 4 tests for date-filtered search in embedding store
- 21 existing embedding tests updated

**CLI Commands**:
```bash
# Build embeddings
ohtv db embed                    # Build embeddings for all conversations
ohtv db embed --estimate         # Show cost estimate only
ohtv db embed --force            # Rebuild all embeddings

# Search conversations
ohtv search "fix auth bugs"      # Semantic search
ohtv search "error 404" --exact  # Keyword search
ohtv search "docker" -n 20       # Limit results
ohtv search "api" --since 7d     # Filter by date

# Ask questions (RAG)
ohtv ask "how did we fix the auth bug?"     # Question answering
ohtv ask "summarize the API changes" -c 10  # More context chunks
ohtv ask "what PRs were created?" --show-context  # Show retrieved chunks
```

**Embedding Types**:
- `analysis` - Goal + outcomes from cached LLM analysis (auto-updated on `gen objs`)
- `summary` - User messages + refs (repos/PRs/issues) + file paths + commands
- `content` - File contents + terminal outputs (chunked if >1000 tokens)

**Environment Variables**:
- `EMBEDDING_MODEL` - Embedding model (default: `openai/text-embedding-3-small`)
- `LLM_MODEL` - RAG answer model (default: `openai/gpt-4o-mini`)
- `LLM_API_KEY` - Same key used for `gen objs`
- `LLM_BASE_URL` - Same base URL used for `gen objs`

**Implementation Details**:
- `src/ohtv/db/migrations/008_embeddings.py` - Initial embeddings schema
- `src/ohtv/db/migrations/009_embedding_types.py` - Multi-type schema
- `src/ohtv/db/migrations/010_embedding_cache_key.py` - Adds cache_key for analysis variant tracking
- `src/ohtv/db/stores/embedding_store.py` - Vector/FTS storage, aggregated search
- `src/ohtv/analysis/embeddings.py` - Text builders, chunking, embedding
- `src/ohtv/analysis/cache.py` - Auto-updates analysis embedding on gen objs
- Vectors stored as BLOB with struct-packed float32 arrays
- Search aggregates best match per conversation across all embedding types

**Analysis Embedding Cache Keys**: A conversation may have multiple cached LLM analyses with different parameters (e.g., `assess=True,context_level=full,detail_level=detailed` vs `assess=False,context_level=minimal,detail_level=brief`). Each analysis variant can be embedded separately:
- Primary key: `(conversation_id, embed_type, chunk_index, cache_key)`
- For `analysis` embeddings, cache_key matches the analysis_cache table key
- For `summary`/`content` embeddings, cache_key is empty string
- `ohtv db status` shows breakdown by cache_key and identifies missing embeddings

## Completed: Aggregate Analysis Jobs (Issue #22)

**Branch**: `openhands/aggregate-analysis-issue-22`

**Implemented features**:
1. **InputConfig dataclass** in `metadata.py` with mode (single/aggregate), source, period, min_items
2. **Period iteration utilities** in `analysis/periods.py`:
   - `PeriodInfo` dataclass with ISO labels, date ranges, contains() check
   - `iterate_periods()` for generating periods in date ranges
   - `get_last_n_periods()` for "last N weeks/days/months"
   - `compute_period_state_hash()` for cache invalidation

3. **Aggregate execution** in `analysis/aggregate.py`:
   - `run_aggregate_analysis()` - collect items, render Jinja2 template, call LLM
   - `ensure_source_cache_populated()` - auto-run source job on uncached conversations
   - State-hash based caching that invalidates on conversation/prompt changes

4. **CLI command** `gen run <job_id>`:
   - `--per week|day|month` - override iteration granularity
   - `--last N` - last N periods
   - `--out <dir>` - write results to separate files
   - Auto-detects aggregate vs single-trajectory jobs

5. **Example prompts**:
   - `reports/weekly.md` - periodic weekly summary with themes
   - `themes/discover.md` - one-shot theme discovery across all selected conversations

**Usage examples**:
```bash
# Weekly reports for last 4 weeks
ohtv gen run reports.weekly --last 4

# Weekly reports for Q1 2024
ohtv gen run reports.weekly --since 2024-01-01 --until 2024-03-31

# Theme discovery across this week
ohtv gen run themes.discover --week
```

**Tests**: 64 new tests for periods and input parsing (601 total tests passing)

## Bugfix: Conversation ID Normalization in analysis_cache (Migration 011)

**Problem**: The `ohtv db status` command reported false "missing embeddings" (e.g., "3060 / 5195 cached analyses need embeddings") when embeddings actually existed. Running `ohtv db embed` would skip all conversations saying they were already embedded, but the missing count never decreased.

**Root cause**: Conversation IDs were stored inconsistently:
- `embeddings` table: Always stored without dashes (normalized)
- `analysis_cache` table: Some entries stored with dashes, some without
- The JOIN query in `count_cached_missing_embeddings()` required exact match, so dashed IDs couldn't find their non-dashed embeddings

**Fix**:
1. Migration 011 (`011_normalize_cache_ids.py`): Removes duplicate dashed entries that have matching non-dashed versions, and normalizes any remaining dashed entries
2. `AnalysisCacheStore.upsert_cache()`: Now normalizes conversation IDs (removes dashes) before storing
3. `AnalysisCacheStore.upsert_skip()`: Same normalization
4. `AnalysisCacheStore.delete_for_conversation()`: Same normalization
5. `estimate_conversation_tokens()`: Now uses `load_all_analyses()` instead of `load_analysis()` to count all analysis variants for accurate embedding estimates

**Testing**: Run `ohtv db status` - the "Missing embeddings" count should now reflect only genuinely missing embeddings, not false positives from ID format mismatches.
