# AGENTS.md - Repository Context for AI Assistants

## Project Overview

**ohtv (OpenHands Trajectory Viewer)** - A CLI utility for viewing and syncing OpenHands conversation histories. See [`README.md`](README.md) for the elevator pitch and [`docs/`](docs/README.md) for command guides + reference.

## Development

```bash
uv sync                    # Install dependencies
uv run ohtv --help         # Run CLI
```

## Releases & Commit Contract

Releases are automated by [python-semantic-release](https://python-semantic-release.readthedocs.io/) on every push to `main`. There is **no release PR**: the workflow parses the new conventional-commit subject(s) since the last `ohtv-vX.Y.Z` tag, bumps the version in `pyproject.toml` and `src/ohtv/__init__.py`, appends a new section to `CHANGELOG.md`, commits all three with `chore(release): ohtv X.Y.Z [skip ci]` directly to `main`, pushes the new tag, and creates the GitHub Release. End-to-end takes ~30 seconds. If no commits since the last tag warrant a bump, the workflow exits cleanly with no side effects.

The workflow reads the **subject line** of each commit on `main` and classifies it by [Conventional Commits](https://www.conventionalcommits.org/). The contract:

| Subject pattern                                            | Bumps version | Appears in CHANGELOG |
|------------------------------------------------------------|---------------|----------------------|
| `feat: …` / `feat(scope): …`                               | minor         | yes — "Features"     |
| `fix: …` / `fix(scope): …`                                 | patch         | yes — "Bug Fixes"    |
| `feat!: …` or any commit with a `BREAKING CHANGE:` footer  | **major**     | yes — "⚠ BREAKING CHANGES" |
| `chore:` / `chore(worklog):` / `docs:` / `docs(worklog):` / `refactor:` / `test:` / `build:` / `ci:` / `style:` | no | no (hidden) |
| Anything not matching conventional-commit grammar          | no            | no                   |

Concrete rules for this repo:

- **PR squash-merges** become the release-triggering commits. The PR title is the squash subject, so every PR title MUST be a conventional-commit subject. This is enforced by `.github/workflows/pr-title.yml`.
- **Direct pushes to `main` for orchestrator / worklog activity** MUST use `chore(worklog):` or `docs(worklog):` subjects so they are silently ignored by the release workflow. Never write `Update WORKLOG.md` or similar — that bypasses every safeguard by accident.
- **Concurrent merges produce separate releases.** Unlike the previous release-please setup, there is no batching: if two `feat:` PRs merge a minute apart you'll see two tags (e.g. `ohtv-v0.15.0` and `ohtv-v0.15.1`). The `concurrency` group on the workflow serialises the runs so they don't race, but each gets its own release.
- **The auto-generated `chore(release):` commit carries `[skip ci]`** so it doesn't re-trigger the workflow. Don't strip that marker.
- **PyPI publish is intentionally not configured.** If we ever want it, hang a `release-published` workflow off the GitHub Release event.

See `.github/workflows/release.yml`, the `[tool.semantic_release]` block in `pyproject.toml`, and `CHANGELOG.md`.

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

These decisions explain WHY the code is structured as it is. See [`docs/guides/`](docs/README.md) for command usage.

1. **Unified data access**: `list` and `show` transparently search both local CLI conversations (~/.openhands/conversations/) and synced cloud conversations (~/.openhands/cloud/conversations/)

2. **Sync-first architecture**: Cloud conversations must be synced locally before viewing (no direct API queries per-request)

3. **Sync state repair (Issue #113)**: The `ohtv sync --repair` command is a four-category cloud-vs-local reconciliation surface built on top of `cloud_listing` (#112) and `last_snapshot_completed_at` (#111). The legacy manifest/disk ghost+orphan diff is preserved alongside.
   - **Four buckets on `RepairResult`** (lists are `*_ids`; bare names are `int` count properties):
     - `new_on_cloud` — created on cloud after the prior snapshot cutoff; next normal `ohtv sync` will fetch. **Not** actioned by `--fix`.
     - `missing_locally` — present in cloud listing, absent from `conversations`, `created_at` predates the cutoff. The architectural gap `--fix` heals.
     - `removed_from_cloud` — `conversations` rows with `source='cloud'` absent from the latest listing. `--fix` records only; `--fix --prune` deletes.
     - `modified_on_cloud` — present on both sides but `cloud_listing.updated_at` differs from `conversations.cloud_updated_at`. `--fix` refetches.
   - **Listing refresh**: Both `--repair --dry-run` and `--repair --fix` re-run the listing pass at entry (so the report reflects current cloud truth). The lock split is purely about the destructive actions.
   - **Lock semantics** (#109 contract):
     - `--repair --dry-run` (`fix=False`): **no** `sync.lock` acquisition; safe alongside a running sync. Numbers may shift between two read-only invocations (documented caveat).
     - `--repair` / `--repair --fix --prune`: takes `sync.lock` via the CLI wrapper; honours `--lock-timeout=N`; surfaces `SyncLockTimeout` on contention.
   - **`--prune` validation**: `--prune` without `--repair --fix` is a Click `UsageError` (exit 2). Without `--prune`, `removed_from_cloud` is reported but no files/rows are deleted.
   - **Source-filter safety**: `_prune_removed_from_cloud` double-checks `conversations.source = 'cloud'` at deletion time. `source='local'` rows are never pruned, even if a future schema bug were to leak them into the bucket.
   - **Degraded listing**: HTTP failure mid-page → `_run_listing_pass` abandons the in-flight snapshot, `RepairResult.listing_degraded = True`, and `--fix` short-circuits to non-destructive only. Previous snapshot left intact (atomicity guarantee from #112).
   - **`SyncResult.removed_from_cloud`**: parallel to the RepairResult bucket — normal `sync()` also reports the count of manifest entries dropped because they vanished from the listing (#110 scenario #4).
   - **`cloud_count` derivation**: The legacy single-integer `count_conversations()` API is no longer called by `repair`; the count is derived from `cloud_listing` rows. `CloudClient.count_conversations` stays on the client for other callers.
   - **Sample output** and the full proposal live in Issue #113.

4. **Title derivation**: Local conversations derive titles from first user message (first 60 chars, word boundary truncation)

5. **Timezone handling**: Cloud timestamps are UTC; local CLI timestamps lack timezone info. The codebase normalizes to UTC for sorting, then converts to local time for display. **Limitation:** Local timestamps are interpreted using the current machine's timezone - if data moves between machines with different timezones, times may display incorrectly.

6. **LLM analysis caching**: The `gen objs` command caches results keyed by parameter combination (context level, detail level, assess flag). Cache invalidates when event count changes (conversation grew) or when the prompt file changes (detected via prompt hash). Multi-conversation mode (batch) uses minimal context + brief detail for token efficiency. **Issue #149 expanded the context ladder from 3 levels (`minimal`/`default`/`full`) to 5 (`minimal`/`outcome`/`dialogue`/`actions`/`observations`)** — see `docs/guides/analysis.md` for the table. The cache_key shape is unchanged (`assess=…,context_level=…,detail_level=…`) but the level *values* changed, so all pre-#149 cached analyses become orphaned and are re-generated lazily on the next `gen objs` invocation per conversation. No migration is written; this is the intended one-time cost of the breaking change. The auto-promotion ladder (`promote_context_level` in `analysis/objectives.py`) steps **one level at a time** through `CONTEXT_LEVEL_ORDER` until the transcript is non-empty — Issue #145 plugs into this seam next.

7. **LLM timeout**: Default 300s. Override with `LLM_TIMEOUT` env var. CLI shows spinner during analysis.

8. **LLM cost tracking**: `analyze_objectives()` returns an `AnalysisResult` dataclass containing `analysis` (ObjectiveAnalysis), `cost` (float, dollars), and `from_cache` (bool). The `gen objs` command (batch mode) displays running cost in the progress bar during analysis and shows total cost after completion. Cost is obtained from `response.metrics.accumulated_cost` via the OpenHands SDK LLM class.

9. **Human-readable action details**: `-d` flag formats tool calls for readability (e.g., `$ git status` for terminal). Use `--debug-tool-call` for raw JSON.

10. **Output truncation**: `-o` truncates to 2000 chars; `-O` shows full output. Both show exit codes.

11. **SQLite indexing**: Lightweight index for conversations and relationships. See `docs/reference/database.md`. Key points:
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
    - **Design doc**: See `docs/design/temporal-pr-linking.md` for planned improvements

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
    - **Single entry point (#116)**: Production callers MUST use `ohtv.db.get_ready_connection()` instead of the lower-level `get_connection()` + `migrate(conn)` pattern. The helper composes `get_connection()` and `ensure_db_ready()` so every command — fresh-install or otherwise — opens a DB that has the current schema **and** has had all pending maintenance tasks evaluated. The two low-level primitives (`get_connection`, `migrate`, `ensure_db_ready`) remain public for niche callers (e.g. the `db init` command, which needs the list of newly-applied migration names that `migrate(conn)` returns). The regression test `tests/unit/test_no_raw_migrate.py` enforces this with a grep-based allow-list; the allow-listed sites are `db/maintenance.py` (canonical wrapper), `db/connection.py` (docstring example), and `cli.py` (`db init` only).

26. **Customizable prompts**: LLM analysis prompts are stored as markdown files for user customization:
    - **Default prompts**: `src/ohtv/prompts/*.md` - 6 prompt variants (brief, standard, detailed × assess/no-assess)
    - **User prompts**: `~/.ohtv/prompts/*.md` - Override defaults by copying and editing
    - **Load order**: User prompts checked first, then package defaults
    - **Management**: `ohtv prompts` command for init/list/show/reset operations
    - **Implementation**: `get_prompt(name)` and `get_prompt_hash(name)` in `ohtv/prompts/__init__.py`
    - **Cache invalidation**: Prompt hash (SHA256, first 16 chars) is stored with cached analysis; cache invalidates when prompt content changes

27. **DB as canonical metadata source + `sync.lock` writer mutex (Issues #86, #87, #109, #114 Phase C)**: The DB (`conversations` table) is the authoritative cache for cloud-side editable metadata. Pre-#114 the manifest (`~/.ohtv/sync_manifest.json`) held this role — #86 covered `title` and `labels`; #87 extended this to `selected_repository`, `selected_branch`, and `created_at`; **#114 Phase C (migration 021) flipped the canonical bit to the DB** and added `conversations.selected_branch` as the new column for the one field the listing API doesn't provide. The manifest is **dual-written for one release** for downgrade safety; Phase D will retire the manifest writes entirely.

    The scanner (`db/scanner.py:extract_metadata`) now reads via a `db_overlay: Conversation | None` argument: when the cloud-source DB row carries non-NULL values for `title` / `labels` / `selected_repository` / `created_at` / `selected_branch`, those win over the manifest overlay (which becomes a cold-upgrade fallback only). For cloud convs with a fully-populated DB row, the scanner **skips `base_state.json` entirely** — the same #87 optimization, just gated on DB columns instead of manifest keys. A cold `db scan --force` over a Phase-C-populated dataset opens `base_state.json` only for local CLI convs and for cloud convs whose DB row is still mid-backfill.
    - **Refresh path**: `ohtv sync --update-metadata` lists all cloud conversations (unfiltered by `updated_at`) and rewrites `title`, `labels`, `selected_repository`, and `created_at` where they differ. `selected_branch` is **NOT** refreshed — the listing API does not return it; only `meta.json` inside a trajectory ZIP carries it. Never downloads trajectories. Does not advance `last_sync_at` or increment `sync_count`.
    - **Auto-run**: A normal `ohtv sync` automatically runs the metadata refresh after a successful sync **only when** `result.new + result.updated > 0`. Skipped on `--dry-run`, `--force`, `--repair`, `--status`.
    - **Direct DB write**: `ConversationStore.update_metadata(conv_id, *, title, labels, selected_repository, created_at)` writes only the columns passed; uses a sentinel (`_UNSET`) to distinguish "leave unchanged" from "explicitly clear" (pass `None`). Empty-dict labels normalize to NULL (matching `parse_conversation_info`). `created_at` accepts a `datetime` and raises `TypeError` on raw strings — callers parse listing payloads via `_parse_datetime` before invoking.
    - **`MetadataDiff` struct**: `sync._metadata_differs` returns a `MetadataDiff` dataclass (not a tuple) with `title_changed`/`labels_changed`/`selected_repository_changed`/`created_at_changed` booleans + the canonical new values. `selected_branch` is deliberately not a field — it cannot be refreshed via listing.
    - **Repair rebuilds from listing (#87)**: `sync --repair --fix` fetches the cloud listing once and rebuilds orphaned manifest entries with full #87 metadata. Falls back to null-filled entries when there's no API key or the listing fails. `selected_branch` for orphans comes from on-disk `base_state.json` (the one place repair still reads it).
    - **Manifest schema is additive**: pre-#87 entries lack the new keys entirely. `load_manifest_metadata` carries the new keys only when present in the underlying entry, letting `extract_metadata` distinguish "trust manifest" (key present, even with None value) from "fall back to `base_state.json`" (key absent). No migration; benefits accrue lazily on next sync.
    - **#89 follow-up**: Issue #89's `gen titles` command PATCHes the cloud API and reuses this same DB write path.
    - **#109 — column ownership + `sync.lock` writer mutex**: The full column-ownership table (every column on `conversations` mapped to its canonical writer per `source` value) lives in `docs/reference/database.md` ("Column Ownership and the `sync.lock` Writer Mutex"). The mutex serializing `ohtv sync` / `ohtv db scan` / `ohtv gen titles` is `$OHTV_DIR/sync.lock`, acquired via `fcntl.flock(LOCK_EX | LOCK_NB)` in `src/ohtv/locks.py`. Read-only commands (`list`, `show`, `refs`, `errors`, `search`, `ask`, `report *`, `db status`, `db process *`, `db embed`, `gen objs`) do NOT take the lock. Default is fail-fast (`--lock-timeout=0`); pass `--lock-timeout=N` to wait. Windows is a no-op (logged warning) — tracked for follow-up via `msvcrt.locking`. **`selected_branch` (post-#114 Phase C)**: sync is **now permitted** to write `selected_branch` via `ConversationStore.record_cloud_download` (the value is sourced from the freshly-exported `base_state.json`, not from the listing API). The scanner is the secondary writer (from `base_state.json` on cold rescans). This overturns the pre-Phase-C "scanner-only" codification — the column-ownership table in `docs/reference/database.md` has been updated to reflect the new contract. `selected_branch` is still **NOT** a parameter of `ConversationStore.update_metadata` (the metadata-refresh path) because the listing API does not carry it.
    - **#114 — manifest-retirement reference**: The structured field-by-field ownership map, manifest reader call-site surface, brittle-spot catalogue, and phased retirement plan (A → B → C → D) live in [`docs/reference/sync-state-ownership.md`](docs/reference/sync-state-ownership.md); cite that doc when editing any code that touches `sync_manifest.json` or the columns it overlays.

28. **Reports module (`ohtv.reports`, Issue #81)**: The `report` Click group hosts read-only aggregate reports built on top of `~/.ohtv/index.db`. Each report is split into a pure-Python module (no Click imports) plus a thin CLI wrapper in `cli.py`, so downstream consumers (e.g. issue #82 charting) can import the row-shaping function directly.
    - **First report**: `report velocity` joins `change_refs` × `conversation_contributions` × `conversation_human_input` and buckets by ISO week.
    - **ISO week rule**: SQLite's `strftime('%W', ...)` is GNU/POSIX, not ISO 8601. The SQL fetches per-`change_ref` rows; Python computes the bucket key with `datetime.isocalendar()` and formats `f"{year}-W{week:02d}"`. Regression-tested via `test_iso_week_boundary_2024_12_30` (2024-12-30 → `2025-W01`, not `2024-W53`).
    - **DISTINCT (change_ref, conv) sub-select**: One conversation contributing as `created` + `pushed` + `merged` to the same PR would otherwise triple-count its human words. The query collapses `conversation_contributions` to DISTINCT `(change_ref_id, conversation_id)` pairs before joining `conversation_human_input`.
    - **`initial_prompt_source` policy**: `human` and `unknown` both include the initial prompt + followups; `automation` excludes the initial prompt (and the implicit `+1` initial message). `unknown` is the optimistic default until issue #83 lands proper classification.
    - **LOC NULL handling**: All-NULL bucket → `-` (table) / empty (CSV). Mixed → sum knowns + `partial_loc=True` (surfaced by `--verbose`). Words/LOC denominator zero → `-` / empty.
    - **Reusable surface**: `ohtv.reports.velocity.aggregate_velocity(conn=..., since=..., until=..., repo=..., include_empty=...)` returns a `VelocityReport(rows, totals, metadata)` and is the entry point that issue #82 should consume.

29. **Weekly counts report (`ohtv.reports.weekly_counts`, Issue #92)**: CSV-only export of new-conversation counts bucketed by ISO 8601 week, split by source. Built on top of the #81 scaffolding (`reports/` package + `report` Click group).
    - **CLI**: `ohtv report weekly-counts` emits stdout CSV with header `week,cloud,cli,total`. Flags: `--since`/`--until`, `--source [cloud|cli|all]`, `--include-empty`, `--exclude-current-week`, `--out PATH`.
    - **`cli` (CSV) vs `local` (DB) naming**: The CSV column header is `cli` because that is what the issue title says and what reads naturally in a report. The DB stores `source='local'` for CLI conversations (see `src/ohtv/sources/base.py`). The translation happens in exactly one place: `weekly_counts.aggregate_weekly_counts` (DB→CSV) and the CLI `--source` flag mapping (`cli` → `'local'` bind value). Every other layer keeps the existing `local` vocabulary.
    - **UTC-bin caveat**: Cloud `created_at` is UTC, CLI `created_at` is often naive (see item 5 above). Naive timestamps are treated as UTC for ISO-week bucketing — best-effort consistent with the rest of the codebase. This can mis-bucket conversations created within a few hours of a Monday boundary on machines in non-UTC time zones. Documented in the module docstring and in the test `test_naive_timestamp_treated_as_utc` (T-11).
    - **Bucket-by `created_at`** (NOT `updated_at`) — "new conversations per week" is the report's semantics.
    - **No SQLite `strftime` for ISO week**: Same regression rule as #81 (test T-4: 2024-12-30 → `2025-W01`).
    - **Reusable surface**: `ohtv.reports.weekly_counts.fetch_rows(conn, ...)` + `aggregate_weekly_counts(rows, ...)` returns a `WeeklyCountsReport(rows, metadata)` and is the entry point that issue #82 should consume.

30. **Velocity chart rendering (`ohtv.reports.charts`, Issue #82)**: Static 3-panel matplotlib figure (PR counts / diverging LOC ± / Words-per-LOC line) saved to a file. Consumes the same `list[VelocityRow]` that the #81 report produces — no DB code, no data-shape changes, no new aggregation path.
    - **Optional dependency**: `matplotlib` lives in `[project.optional-dependencies] charts` and `[dependency-groups] dev`. The core install stays minimal; users install via `pip install ohtv[charts]`.
    - **Lazy import (AC-7)**: `import ohtv.reports.charts` does NOT pull in matplotlib at module load. `plot_velocity` does `import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt` inside the function body. `ImportError` here is the user signal — the CLI catches it (including from the lazy call) and re-raises a friendly `click.UsageError("Charting requires the [charts] extra. Install with: pip install ohtv[charts]")`. Verified by `test_import_charts_does_not_pull_in_matplotlib` (synthetic `sys.modules["matplotlib"] = None`).
    - **Extension drives format**: `.png`/`.svg`/`.pdf` are inferred from the output path. No `--format` flag — the original issue body had one and the technical-approach comment explicitly removed it as redundant. Unsupported extension → `ValueError`.
    - **No pixel-diff snapshots**: Tests patch `Axes.bar` / `Axes.plot` / `Axes.axvline` / `Figure.savefig` and assert on the data passed in, plus file-magic-bytes checks for `.png`/`.svg`/`.pdf`. Pixel diffs are flaky across matplotlib/font versions and were rejected during issue planning.
    - **No `plt.show()`**: Headless-only by design (no X11 / display dep). `bbox_inches="tight"`, DPI=300 for raster only.
    - **Words/LOC gap handling**: `words_per_loc=None` rows are dropped from the line-plot data (gap in the line) rather than passing `None` to matplotlib, which would otherwise raise `TypeError`.
    - **NULL LOC bar handling (#103)**: `partial_loc=True` rows are drawn as hatched (`///`) bars in the diverging LOC panel; fully-NULL rows render as zero-height hatched bars. Fully-known rows are solid. A `Patch`-based legend entry ("Partial LOC (NULL)") is appended to Panel 2's legend. The table format (`ohtv report velocity` without `--chart`) remains the authoritative renderer for NULL-vs-zero — see item #28 (#81).
    - **`mark_date`**: Converted to its ISO-week label and matched against the row index. Off-week dates fall to the midpoint between adjacent bucket indices; out-of-range dates clamp to the endpoints. `axvline` is drawn on all three panels.
    - **CLI wiring**: `ohtv report velocity --chart PATH [--mark-date YYYY-MM-DD] [--title STR]`. All #81 filters (`--since`/`--until`/`--repo`/`--include-empty`) work identically. Empty-result paths print the same hint as the table path and exit 0 WITHOUT writing a file.
    - **Secondary surface**: `scripts/chart_velocity.py` reads CSV (stdin or positional path) → `VelocityRow.from_csv_dict` (added on `VelocityRow` for this issue) → `plot_velocity`. ~50 LOC including argparse; deliberately thin.

31. **Sub-conversations included in sync by default (Issue #108)**: `CloudClient.search_conversations` / `search_all_conversations` / `count_conversations` now forward `include_sub_conversations=true` to `GET /api/v1/app-conversations/search` (and `/count`). The cloud API silently defaults this to `false`, so pre-#108 builds were undercounting and underdownloading whenever an account used agent delegation. `ohtv sync` is now the complete mirror of what the cloud UI and `/count` report — the recurring multi-thousand-row gap surfaced by `ohtv sync --repair --check-cloud` closes on the first post-upgrade run. No CLI flag; this is a default-on engine change.
    - **DB column**: Migration 019 adds `conversations.parent_conversation_id TEXT NULL` plus the partial index `idx_conversations_parent ... WHERE parent_conversation_id IS NOT NULL`. Local CLI rows stay NULL forever (delegation is a cloud-only concept today).
    - **Two writeback paths, one COALESCE**: `Syncer._record_cloud_download_in_db` writes the parent id at download time via `ConversationStore.record_cloud_download(..., parent_conversation_id=...)`; the scanner's `extract_metadata` reads from the `cloud_listing` snapshot (Issue #112) via `load_cloud_listing_parents` and supplies the value through its normal upsert. The conversations table's upsert uses `parent_conversation_id = COALESCE(excluded.parent_conversation_id, conversations.parent_conversation_id)` so a scanner pass that runs after a partial sync (no listing snapshot for this id) does NOT clobber a value sync just wrote. Ids are normalized (dashless) on write per item #14.
    - **Manifest stays parent-agnostic**: `~/.ohtv/sync_manifest.json` is the canonical cache for cloud-side *editable* metadata only (title, labels, selected_repository, created_at — item #27). `parent_conversation_id` is a structural relationship, not editable cloud-side metadata, so it lives in the DB only. This matches the ownership shape of `cloud_updated_at` (migration 018) and `labels` (migration 015). Repair / `--update-metadata` do NOT touch the column.
    - **Listing-shape resilience**: `_listing_row_to_conv_dict` reads `parent_conversation_id` verbatim from the cloud_listing row, and the sync queue defaults the value to `None` when absent. A cloud payload that drops the field entirely is treated as "unknown / root" rather than crashing — guarded by the regression test `test_sync_handles_missing_parent_field_in_listing`.

32. **Root-conversation aggregation grain (Issue #122)**: Migration 020 adds `conversations.root_conversation_id TEXT` plus the index `idx_conversations_root` and the SQL view `conversations_by_root`. The policy is: **the root conversation is the unit of "what the user did"; subs are agent-delegation implementation detail.** Per-conversation events / embeddings / refs / contributions stay at the conversation grain (so we don't lose information), but aggregation and display roll up to the root by default.
    - **Single owner**: `ConversationStore` owns `root_conversation_id`. Callers DO NOT pass it — they pass `parent_conversation_id` (per item #31) and the store resolves the root at write time via `_resolve_root_conversation_id`. This keeps every write path consistent: `upsert` (scanner), `record_cloud_download` (sync), and the migration backfill all walk the same tree the same way. The Conversation dataclass field is read-only output.
    - **Write-time resolution rule**: if the effective post-COALESCE parent is None → root = own id (a fresh root); else look up parent's `root_conversation_id` and propagate; else (parent absent from local DB) fall back to own id (orphan policy — the sub becomes its own root for reporting purposes). Matches the migration's backfill semantics so re-scans are idempotent.
    - **COALESCE on the column itself**: `root_conversation_id = COALESCE(excluded.root_conversation_id, conversations.root_conversation_id)` mirrors the parent column. A future caller passing `None` cannot clobber a value the store already resolved.
    - **Default grain helper**: `ConversationStore.list_roots(since, until, source, selected_repository)` is THE per-PR-cluster entry point — its signature mirrors `list_by_date_range` (NOT a non-existent `list_with_filters`) plus a fourth filter for repository. Returns `RootConversation` (a sibling of `Conversation` with `event_count = SUM` over the subtree, plus `conversation_count` and `sub_count`). Display fields come from the root's row, time fields span the subtree (MIN/MAX). Filters apply at the root grain — a sub with a different repo does NOT make the tree match.
    - **`db status` reports the split**: `Conversations: N (R roots + S subs across T trees)` when subs exist, or `Conversations: N (R roots)` when not.
    - **Foundation issue, not a per-command rewrite**: Issues #123 (`report weekly-counts`), #124 (`report velocity`), #125 (`gen objs/titles/run`), #126 (`classify`), #127 (`list`/`refs`), and #128 (RAG `ask`/`search`) consume `list_roots` and the view; they are separate PRs. This item documents the shape; the per-command issues document the per-caller behavior changes.
    - **Cross-references**: ID normalization rule per item #14; parent-column ownership per item #31; column-ownership table in `docs/reference/database.md`.

33. **`ohtv ask` dual investigation modes (Issue #161)**: `ohtv ask` runs *side-by-side* investigators so we can A/B test prompt-cookbook vs custom-tool agents before deleting either. The user-facing flag `--agent` now means "prompt-cookbook agent" (cli mode); the old behavior moved to `--agent-tools` (tools mode). The two flags are mutually exclusive (Click `UsageError`), and `--max-steps 0` short-circuits to single-turn RAG under both modes.
    - **`InvestigationResult.mode: Literal["tools", "cli"]`** (default `"tools"` for back-compat with existing test fixtures that construct the dataclass directly). `InvestigationAgent.investigate()` sets `mode="tools"`; `InvestigationAgentCli.investigate()` sets `mode="cli"`. Issue #162 telemetry will stamp every session with this field.
    - **`src/ohtv/analysis/ohtv_runner.py`** — `run_ohtv(argv, *, timeout_s=30, cli_obj=None)` invokes `ohtv` in-process via Click 8.3's `CliRunner`. `mix_stderr=False` is **NOT** passed (the kwarg was removed in 8.2/8.3); stdout/stderr are split by default and read off `result.stdout` / `result.stderr`. The allow-list is `("show",)`, `("refs",)`, `("search",)`, `("list",)`, `("errors",)`, `("gen", "objs")`. The runner auto-injects `--cache-only` whenever `argv[0:2] == ["gen", "objs"]` so the agent can never trigger fresh LLM analyses through `gen objs` — the flag is idempotent if the agent already supplied it. Block-list (`sync`, `db scan/process/embed/migrate-cache/reset`, `fetch-loc`, `gen titles`, `gen run`, `classify`, `config`) is surfaced verbatim in rejection observations so the agent can self-correct in one turn. The disjoint-set invariant between allow-list and block-list is unit-tested.
    - **`gen objs --cache-only`** is a first-class CLI flag (`src/ohtv/cli.py`), not a runner-only convenience. Plumbed through `_run_objectives_analysis` (single-conv) and `_run_batch_objectives_analysis` (multi-conv) into `analyze_objectives(cache_only=True)`. On cache miss the function returns an `AnalysisResult` whose `analysis` is a `_build_empty_objective_analysis(...)` stub (`goal=None`, empty lists, `model_used=""`, `content_hash=""`); `cost=0.0`, `from_cache=False`. **The LLM is never called.** Power users + scripted reports benefit too: `ohtv gen objs --cache-only -F json` dumps cached objectives without firing tokens.
    - **`InvestigationAgentCli`** lives in `src/ohtv/analysis/investigator_cli.py` alongside the cookbook prompt (module-level `COOKBOOK_PROMPT` constant, accessed via `get_investigation_cli_system_prompt()`). Snapshot-tested in `tests/unit/analysis/test_cookbook_prompt.py` — the test asserts the cookbook mentions every allow-listed prefix so the runner's allow-list and the prompt's instructions can't drift. `RunOhtvTool` is the **only** investigation tool (plus `finish`/`think` from the SDK). `command_count_cap` defaults to `max_iterations * 3`; the cap-reached path returns a structured observation instructing the agent to call `finish`.
    - **`conversations_examined` population**: the legacy tools mode tracks IDs through tool-observation hooks; the CLI mode parses 8/32/36-char hex IDs out of argv via `extract_conversation_ids_from_argv` and normalises to 32-char dashless (matches item #14). Both modes therefore have the same field shape, which is the contract #162 telemetry consumes.
    - **CLI dispatch** lives in the `ask` handler (`src/ohtv/cli.py` ~line 3635-3946). The mode banner (`[dim]Investigation mode: cli|tools[/dim]`) is printed exactly once per invocation, immediately before the existing "Preliminary Search Results" rule.
    - **Click reentrancy note**: Rich's `Console` reads `sys.stdout` lazily at write-time (no file handle is captured at module load), so the runner's CliRunner invocations correctly capture all Rich output via the redirected stdout. No `cli.console` rebinding needed.
    - **Documentation**: `docs/guides/search-and-ask.md` §"Investigation Mode" carries the user-facing table + allow-list + browse-vs-search guidance.

34. **`ohtv ask` session telemetry (Issue #162)**: Every `ohtv ask` invocation writes a self-contained JSON blob under `~/.ohtv/telemetry/sessions/{ISO8601-Z-with-hyphens}_{8-hex-uuid-prefix}.json` plus a one-line summary appended to `~/.ohtv/telemetry/sessions.jsonl`. Schema version 1; full field reference in `docs/reference/telemetry.md`.
    - **Storage root**: `get_telemetry_dir()` in `src/ohtv/config.py` returns `$OHTV_TELEMETRY_DIR` if set, else `$OHTV_DIR/telemetry/` (consistent with item #12).
    - **Opt-out**: `OHTV_TELEMETRY_ENABLED=0` short-circuits recorder construction in the `ask` handler — no files written.
    - **`agent: null` (not key omission)**: plain `ohtv ask` invocations (no `--agent` / `--agent-tools` flag) land with `agent` explicitly `null` so JSON consumers see a stable key set.
    - **`flags.agent_mode` mirrors `InvestigationResult.mode`** (#161 contract): `"cli"` for `--agent` (prompt-cookbook), `"tools"` for `--agent-tools` (legacy custom-tools), `null` for plain RAG.
    - **Filename grammar**: hyphens replace the conventional colons in the timestamp because `:` is reserved on Windows and some cloud sync clients (Dropbox, OneDrive) misbehave. Lockdown is `tests/unit/analysis/test_telemetry.py::test_filename_grammar`.
    - **Atomic blob writes**: `tempfile.NamedTemporaryFile(dir=sessions_dir)` + `os.replace()` (POSIX-atomic, Windows-safe). A `^C` mid-write leaves a `.tmp` file behind but never a half-written `.json`.
    - **`sessions.jsonl` concurrency**: single `write()` per session, line is ~200 bytes (well under `PIPE_BUF=4096`), so concurrent writers from two processes interleave at line boundaries only under POSIX `O_APPEND`. No file locking. Verified by `multiprocessing.Process(2)` regression.
    - **Graceful degradation**: `SessionRecorder.finalize()` may raise on I/O errors; the CLI handler swallows it with a `log.warning` so `ohtv ask` still exits 0 with its answer (AC).
    - **Per-step `cost` and `tokens.{prompt,completion}` are deltas**, not cumulative reads. `StepRecorder.__enter__` snapshots the recorder's running totals; `__exit__` computes deltas and propagates the new totals. Summed deltas across all steps reconcile to `agent.total_cost` within float epsilon.
    - **Truncation**: `chunk_text` capped at 2 KB, `observation_truncated_text` at 8 KB. Each carries a paired `_truncated` flag + `_size_bytes` counter.
    - **No PII redaction**: ohtv has no remote storage path; telemetry stays local. If/when remote upload appears, that's a different issue.
    - **Files**: new `src/ohtv/analysis/telemetry.py` (`SessionRecorder`, `StepRecorder`, `build_*_record` helpers); `get_telemetry_dir` in `src/ohtv/config.py`; recorder hook into `InvestigationAgent.investigate(..., recorder=None)` / `InvestigationAgentCli.investigate(..., recorder=None)`; `ask` handler builds + finalises the recorder with a `try/finally`. The agent-loop bodies use `from ohtv.analysis.telemetry import maybe_step` to keep the loop body single-branch.

35. **Engagement v2 — separate `T_a` cap (Issue #184)**: `src/ohtv/db/stages/engagement.py` carries **two** conceptually distinct timing constants now. `T` (`DEFAULT_THRESHOLD_SECONDS`, 12 min) is the original *silence tolerance* — "how long can the human be silent during agent activity and still be present at this instant" — empirically tuned in #163. `T_a` (`DEFAULT_SUSTAINED_ATTENTION_SECONDS`, 1 h, **PROVISIONAL**) is the new *sustained-attention window* — "how long can the human plausibly stay continuously engaged in one block" — caps how far an attended block extends back from `Uᵢ` to `Uᵢ₋₁`. The v1 algorithm reused `T` for both jobs and silently credited 14+ hours of "engagement" to set-and-forget overnight conversations where the agent kept the silence gate satisfied; the v2 algorithm uses both constants independently. `compute_engagement` now takes `sustained_attention_seconds` as a separate kwarg; `process_engagement` writes both values plus `algorithm_version` (`COMPUTE_ENGAGEMENT_VERSION = 2`) onto every row.
    - **Two constants, two semantics — DO NOT collapse**: the previous expansion comment on #184 proposed reusing `T` for both gates; the user explicitly rejected that as conceptually wrong (different empirical phenomena). The 1 h default for `T_a` was chosen as a *defensible placeholder*, not an empirically tuned value — it is several multiples of `T` so the two cannot accidentally collapse, and clips the 14–20 h outliers while preserving the 30–60 min reference rows. The empirical tuning is deferred to a separate workspace (proposal: bucket user-to-user gaps by intervening agent-activity length and observe where presence prediction fails). The lockdown test is `test_default_sustained_attention_window_is_one_hour`; updating the default REQUIRES updating that test in the same commit.
    - **Auto-invalidation on upgrade**: migration 025 adds the two new columns AND `DELETE FROM conversation_stages WHERE stage = 'engagement'`. The next `ohtv db process engagement` (or `db process all`, or `sync`-driven processing) recomputes every conversation under v2 — users do **not** need to remember `--force`. Existing engagement data rows are preserved (clearly labelled `algorithm_version = 1`) until overwritten by the recompute, so downstream queries keep working through the upgrade window.
    - **v1 behavior recoverable**: pass `--sustained-attention 999999999` (or `sustained_attention_seconds=10**9` in code) to disable the cap. Used by `test_back_from_lunch_v1_behavior_recoverable_with_huge_t_a`. The threshold sweep script (`scripts/engagement_threshold_sweep.py`) is unaffected — it sweeps `T` only and consumes the v2 default `T_a`, which is the right thing for `T`-tuning. A future `T_a`-tuning sweep can reuse the same script with a fixed `T` and varying `--sustained-attention`.
    - **CLI flag**: `ohtv db process engagement --sustained-attention SECONDS` mirrors `--threshold SECONDS`. Both are accepted on `db process all` (silently ignored by non-engagement stages, like the existing `--threshold` behavior).

36. **`--event-dates` column-swap filter (Issue #180)**: A boolean flag wired through `list`, `search`, `ask`, `gen objs`, `gen titles`, and `gen run` that swaps the date predicate from `conversations.created_at` to `conversation_engagement.first_event_ts` / `last_event_ts`. Default-off; back-compat preserved. The flag is **not** added to `refs` (refs are intrinsically tied to action timestamps).
    - **Single owner of the SQL**: `ConversationStore.list_by_event_date_range(*, since, until, source, include_subs)` is the only place the engagement-overlap WHERE clause lives. `_get_conversations_from_db` dispatches to it when `event_dates=True`, otherwise falls through to the existing `list_by_date_range` (the canonical `created_at` path). Predicate shape:
      - `since` only → `last_event_ts >= since`
      - `until` only → `first_event_ts <= until`
      - both → interval overlap (`first <= until AND last >= since`)
    - **INNER JOIN semantics**: conversations without a `conversation_engagement` row are *excluded* under `--event-dates`. This is the deliberate counterpart to `--engaged`'s exclude-on-missing rule (item #14 conventions). The empty-result hint in the `list` CLI surfaces the most common cause ("run `ohtv db process engagement`").
    - **Cross-flag validation** lives in `_validate_event_dates_args(*, event_dates, since, until)` in `cli.py`. Called from the validation seam in `_apply_conversation_filters` AND from `gen titles` / `gen run` BEFORE their default 30-day / last-4-periods windows kick in — without the early gate `gen run --event-dates` would silently get the engagement-event interpretation of the default window. `search` and `ask` raise their own UsageError inline (search has no `--day` / `--week`; ask additionally must not let auto-extracted temporal filters from the question text satisfy the gate).
    - **Filesystem fallback removed when `event_dates=True`**: `_get_conversations_from_db` raises if the DB is unavailable under `--event-dates`. Engagement timestamps are a DB-only concept; pretending otherwise would silently turn `--event-dates --since` into a no-op on fresh installs. Plain `--since` keeps the FS fallback for back-compat.
    - **Migration 024** (`024_engagement_event_ts_indexes.py`) adds `idx_conv_engagement_last_event_ts` and `idx_conv_engagement_first_event_ts`. These are covering indexes on a column that's already in many existing JOINs; the schema bloat is trivial and the JOIN cost drops to O(log N) per predicate.
    - **Search FTS path**: `--exact --event-dates` cannot push the date filter into FTS5 (no native date integration), so the search body runs an inline `SELECT conversation_id FROM conversation_engagement WHERE last_event_ts >= ?` post-filter — chunked at 900 ids to stay under SQLite's default `SQLITE_MAX_VARIABLE_NUMBER=999`. The semantic path pushes the filter into the `EmbeddingStore.search_conversations(..., event_dates=True)` SQL, which JOINs against `conversation_engagement` directly.
    - **Ask telemetry**: `flags.event_dates` is captured in the `ohtv ask` session-record blob (Issue #162) so future analytical work can correlate retrieval quality with the date-predicate mode.
    - **Issue #181 builds on this**: the engagement-grouping rollup proposed in #181 sits on top of the same engagement-table JOIN — keeping a single owner (`list_by_event_date_range`) for the predicate makes #181 a thin extension rather than a parallel SQL implementation.



## Troubleshooting

### Terminal shows `^M^M^M` when typing input

Terminal is in corrupted state (usually after OpenHands CLI exits improperly).

**Fix:** Run `reset` or `stty sane`. The `clear` command does NOT fix this.

## Testing

**Cloud-sync behavioral harness (`tests/unit/sync/`, Issue #110)**: shared test scaffolding consumed by #111/#112/#113. `fakes.py` (`FakeCloudClient` + `RecordingCloudClient` subclass), `builders.py` (`make_trajectory_zip`, `ConvFactory`), `strategies.py` (Hypothesis), and `conftest.py` (fixtures: `fake_cloud`, `conv_factory`, `sync_manager_factory`, `seeded_local_state`). Pending-behavior scenarios in `test_behavioral.py` use `pytest.mark.xfail(strict=True, reason="#11x")` so a behavior accidentally landing before its issue fails CI. When the corresponding issue ships, drop the marker — do not change the assertion.

```bash
# Unit tests (see docs/contributing/testing.md)
uv run python -m pytest tests/unit/db -v
uv run python -m pytest tests/unit/test_filters.py -v
uv run python -m pytest tests/unit/test_errors.py -v
uv run python -m pytest tests/unit/sync -v   # cloud-sync behavioral harness (#110)

# Manual testing - see docs/reference/cli.md for command index
uv run ohtv list -A                    # All conversations (refs shown by default)
uv run ohtv list -A --idle             # Show idle time (red < 7m, green >= 7m)
uv run ohtv list -A --idle 15          # Custom idle threshold (15 min)
uv run ohtv list -A --no-refs          # Hide refs from title column
uv run ohtv show <id> -m               # Messages
uv run ohtv show <id> -s -d -o         # Actions with details + outputs
uv run ohtv refs <id>                  # Git references (rich display)
uv run ohtv refs -D --prs-only -1      # Today's PRs, one per line
uv run ohtv refs -W --format json      # This week's refs as JSON
uv run ohtv messages -W                # User messages from this week
uv run ohtv messages -D 7 -1           # Last 7 days, one tab-sep line per msg (pipe)
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

- `README.md` - Pitch + quick start
- `docs/` - User guides, reference, design notes (see `docs/README.md`)
- `docs/reference/database.md` - SQLite indexing system
- `docs/contributing/testing.md` - Test infrastructure
- `docs/design/temporal-pr-linking.md` - Design for temporal push-PR linking (next phase)
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

## Bugfix: Duplicate Conversations from Dashed IDs (Migration 012)

**Problem**: Database showed ~2450 conversations when only ~1280 existed on disk. The `db status` showed nearly double the expected conversation count.

**Root cause**: Two code paths created conversation records with different ID formats:
1. Scanner uses directory name (no dashes): e.g., `005915fd6ca64291b7a8b3adb446392a`
2. `_get_conversation_info()` read `id` from `base_state.json` which sometimes has dashes: `005915fd-6ca6-4291-b7a8-b3adb446392a`

This happened with LXA (OpenHands desktop) conversations where `base_state.json` contains dashed IDs but directories are named without dashes. When `_ensure_refs_indexed` was called, it created a second (ghost) entry with the dashed ID.

**Fix**:
1. `_get_conversation_info()`: Now normalizes IDs (removes dashes) from both directory name and `base_state.json`
2. Migration 012 (`012_normalize_conversation_ids.py`):
   - Temporarily disables FK constraints
   - For each dashed conversation ID that has a normalized counterpart:
     - Deletes all child records referencing the dashed ID
     - Deletes the dashed conversation entry
   - For dashed IDs without counterparts: updates them and their child records to normalized format
   - Re-enables FK constraints

**Child tables affected**: `conversation_repos`, `conversation_refs`, `actions`, `conversation_stages`, `analysis_cache`, `analysis_skips`, `embeddings`

**Testing**: Run `ohtv db status` - conversation count should match actual conversations on disk.

## Bugfix: Orphaned analysis_cache Entries and Detailed Analysis Format (Migration 013)

**Problem**: `ohtv sync` reported ~1100 conversations "skipped (no content)" during embedding generation when most of them actually had content.

**Root causes** (two separate issues):

1. **Orphaned analysis_cache entries**: The `analysis_cache` table contained entries for cache files that no longer exist on disk. This caused `list_cached_missing_embeddings()` to return false positives - conversations that "needed" analysis embeddings but had no actual cache files to embed.

2. **Detailed analysis format not handled**: The "detailed" analysis format (from `gen objs --detail detailed`) stores objectives in `primary_objectives` (a nested structure with `description` and `subordinates` fields) instead of `goal`/`primary_outcomes`. The `build_analysis_text()` function didn't extract text from this format, so detailed analyses produced empty text and were skipped.

**Fix**:

1. **Migration 013** (`013_cleanup_orphaned_cache.py`): Removes entries from `analysis_cache` and `analysis_skips` where the corresponding cache file doesn't exist in `~/.ohtv/cache/analysis/`

2. **`build_analysis_text()` in `text_builders.py`**: Added `_extract_objective_descriptions()` to recursively extract text from nested objectives (max depth 2 to avoid over-embedding). The function now handles both formats:
   - Standard/brief: `goal`, `primary_outcomes`, `secondary_outcomes`
   - Detailed: `primary_objectives` (nested structure)

**Testing**: Run `ohtv sync` - the "skipped (no content)" count should be much smaller, representing only conversations that genuinely have no embeddable content (very short conversations with 0-4 events).

## Completed: gen titles — Auto-rename Placeholder-titled Cloud Conversations (Issue #89)

**PR**: feat/gen-titles-89 (PR #TBD)

**Command**: `ohtv gen titles` retitles cloud conversations whose title matches `^Conversation [0-9a-f]{5,32}$` (or `--all-titled` for everything) using the best-available cached `gen objs` analysis. Reuses the full `gen objs` filter surface (`--day/--week/--since/--until/--pr/--repo/--label/-n/--all/--offset/--reverse`) plus title-specific flags `--all-titled`, `--dry-run`, `--workers`, `--batch-size`, `--model`.

**Pipeline**:
1. Filter → `_apply_conversation_filters` + cloud-only filter + placeholder predicate
2. Cache probe: detailed_assess > detailed > standard_assess > standard > brief_assess > brief
3. LLM: batched JSON-in / JSON-out (default 25/chunk). Chunk parse failure → single-conv retry. Overlong title → re-prompt then hard truncate at 50 chars.
4. Cloud PATCH: `CloudClient.update_conversation(id, *, title=...)` (added in this PR) → `PATCH /api/v1/app-conversations/{id}` via `_request_with_retry` (honors Retry-After).
5. Local writeback: manifest title rewrite (no `last_sync_at` advance) + `ConversationStore.update_metadata(id, title=...)` (from PR #94 / Issue #86).

**Key files**:
- `src/ohtv/prompts/titles/default.md` — LLM system prompt (Title Case, ≤50 chars, optional leading emoji, imperative)
- `src/ohtv/analysis/titles.py` — `is_placeholder_title`, `description_from_analysis`, `parse_titles_response`, `generate_titles_batch`, `_load_titles_prompt`
- `src/ohtv/sources/cloud.py` — `CloudClient.update_conversation(conv_id, *, title=None, tags=None)`
- `src/ohtv/cli.py` — `gen titles` command + `_run_gen_titles` + `_apply_local_title_writeback` helpers

**Hard guarantees**:
- Progress bars go through `make_progress(...)` only (PR #95 helper) — guarded by `tests/unit/test_progress_lint.py`.
- Local CLI conversations silently skipped (single end-of-run note).
- Cache miss conversations skipped (no LLM call wasted).
- `--dry-run` issues zero PATCHes and zero DB writes.
- `ConversationStore.update_metadata` column set NOT widened — that's Issue #87's job.

**Tests**: 62 new tests across `tests/unit/analysis/test_titles.py`, `tests/unit/test_cli_gen_titles.py`, `tests/unit/test_cloud_update_conversation.py`.
