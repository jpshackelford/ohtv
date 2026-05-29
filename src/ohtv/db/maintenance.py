"""Automatic database maintenance system.

This module handles one-time maintenance tasks that should run automatically
after migrations or feature additions. Users never need to manually run
maintenance commands - the system tracks what's been done and runs required
tasks transparently.

Tasks are tracked in the maintenance_tasks table to avoid repeating work.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger("ohtv")


@dataclass
class MaintenanceTask:
    """Definition of a maintenance task."""
    name: str
    description: str
    triggered_by: str  # Migration or feature that requires this
    check_needed: Callable[[sqlite3.Connection], bool]
    execute: Callable[[sqlite3.Connection, Callable[[int, int], None] | None], dict]


def is_task_completed(conn: sqlite3.Connection, task_name: str) -> bool:
    """Check if a maintenance task has been completed."""
    cursor = conn.execute(
        "SELECT 1 FROM maintenance_tasks WHERE task_name = ?",
        (task_name,)
    )
    return cursor.fetchone() is not None


def mark_task_completed(
    conn: sqlite3.Connection,
    task_name: str,
    triggered_by: str,
    details: dict | None = None,
) -> None:
    """Mark a maintenance task as completed."""
    conn.execute(
        """
        INSERT OR REPLACE INTO maintenance_tasks (task_name, completed_at, triggered_by, details)
        VALUES (?, ?, ?, ?)
        """,
        (
            task_name,
            datetime.now(timezone.utc).isoformat(),
            triggered_by,
            json.dumps(details) if details else None,
        )
    )


# =============================================================================
# Task: Metadata Backfill (after migration 006)
# =============================================================================

def _check_metadata_backfill_needed(conn: sqlite3.Connection) -> bool:
    """Check if metadata backfill is needed.
    
    Returns True if:
    - Task hasn't been completed AND
    - There are conversations without metadata (created_at IS NULL)
    """
    if is_task_completed(conn, "metadata_backfill_006"):
        return False
    
    # Check if there are conversations missing metadata
    cursor = conn.execute("""
        SELECT COUNT(*) FROM conversations 
        WHERE created_at IS NULL AND event_count > 0
    """)
    missing_count = cursor.fetchone()[0]
    return missing_count > 0


def _execute_metadata_backfill(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Backfill metadata for all conversations missing it.
    
    This is equivalent to running `db scan --force` but only for
    conversations that are missing metadata.
    """
    from ohtv.db.scanner import extract_metadata
    from ohtv.db.stores import ConversationStore
    
    store = ConversationStore(conn)
    
    # Find conversations missing metadata
    cursor = conn.execute("""
        SELECT id, location, source FROM conversations 
        WHERE created_at IS NULL
    """)
    rows = cursor.fetchall()
    
    total = len(rows)
    updated = 0
    
    for i, row in enumerate(rows):
        if on_progress:
            on_progress(i, total)
        
        conv_id = row["id"]
        location = Path(row["location"])
        source = row["source"] or "local"
        
        if not location.exists():
            continue
        
        # Extract and update metadata
        metadata = extract_metadata(location, source)
        
        conn.execute(
            """
            UPDATE conversations 
            SET title = ?, created_at = ?, updated_at = ?, selected_repository = ?, source = ?
            WHERE id = ?
            """,
            (
                metadata["title"],
                metadata["created_at"].isoformat() if metadata["created_at"] else None,
                metadata["updated_at"].isoformat() if metadata["updated_at"] else None,
                metadata["selected_repository"],
                source,
                conv_id,
            )
        )
        updated += 1
    
    if on_progress:
        on_progress(total, total)
    
    return {"total": total, "updated": updated}


# =============================================================================
# Task: Cache Index Backfill (after migration 005)
# =============================================================================

def _check_cache_index_needed(conn: sqlite3.Connection) -> bool:
    """Check if cache index backfill is needed.
    
    Returns True if:
    - Task hasn't been completed AND
    - analysis_cache table is empty AND
    - Cache files exist on disk (in new <conv_id>/objective_analysis.json format)
    """
    if is_task_completed(conn, "cache_index_backfill_005"):
        return False
    
    # Check if analysis_cache table is empty
    cursor = conn.execute("SELECT COUNT(*) FROM analysis_cache")
    cache_count = cursor.fetchone()[0]
    if cache_count > 0:
        # Already has data, mark as done
        return False
    
    # Check if cache files exist (new structure: <conv_id>/objective_analysis.json)
    from ohtv.config import get_analysis_cache_dir
    cache_dir = get_analysis_cache_dir()
    if not cache_dir.exists():
        return False
    
    # Check for subdirectories containing objective_analysis.json
    cache_files = list(cache_dir.glob("*/objective_analysis.json"))
    return len(cache_files) > 0


def _execute_cache_index_backfill(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Index existing cache files into the database.
    
    This reads all JSON cache files from the new structure
    (<conv_id>/objective_analysis.json) and creates corresponding entries
    in the analysis_cache and analysis_skips tables.
    """
    import json as json_module
    from ohtv.config import get_analysis_cache_dir
    from ohtv.db.stores import AnalysisCacheStore
    from ohtv.db.stores.analysis_cache_store import AnalysisCacheEntry, AnalysisSkipEntry
    from ohtv.analysis.cache import make_cache_key
    
    cache_dir = get_analysis_cache_dir()
    if not cache_dir.exists():
        return {"cached": 0, "skipped": 0}
    
    store = AnalysisCacheStore(conn)
    # New structure: <conv_id>/objective_analysis.json
    cache_files = list(cache_dir.glob("*/objective_analysis.json"))
    
    total = len(cache_files)
    cached_count = 0
    skipped_count = 0
    
    for i, cache_file in enumerate(cache_files):
        if on_progress:
            on_progress(i, total)
        
        try:
            data = json_module.loads(cache_file.read_text())
            # New structure: parent directory name is the conversation ID
            conv_id = cache_file.parent.name
            
            # Check if this is a skip marker
            if data.get("skipped"):
                entry = AnalysisSkipEntry(
                    conversation_id=conv_id,
                    event_count=data.get("event_count", 0),
                    reason=data.get("reason", "unknown"),
                    skipped_at=datetime.now(timezone.utc),
                )
                store.upsert_skip(entry)
                skipped_count += 1
            else:
                # It's a cached analysis - extract parameters to build cache key
                params = data.get("parameters", {})
                cache_key = make_cache_key(
                    context_level=params.get("context_level", "minimal"),
                    detail_level=params.get("detail_level", "brief"),
                    assess=params.get("assess", False),
                )
                
                entry = AnalysisCacheEntry(
                    conversation_id=conv_id,
                    cache_key=cache_key,
                    event_count=data.get("event_count", 0),
                    content_hash=data.get("content_hash"),
                    analyzed_at=datetime.now(timezone.utc),
                )
                store.upsert_cache(entry)
                cached_count += 1
                
        except (json_module.JSONDecodeError, OSError, KeyError) as e:
            log.debug("Failed to index cache file %s: %s", cache_file, e)
            continue
    
    if on_progress:
        on_progress(total, total)
    
    return {"cached": cached_count, "skipped": skipped_count}


# =============================================================================
# Task: Prompt Hash Backfill (for cache invalidation feature)
# =============================================================================

def _get_conversation_base_dirs() -> list[Path]:
    """Get all base directories that contain conversations."""
    from ohtv.config import Config
    config = Config.from_env()
    return [config.local_conversations_dir, config.synced_conversations_dir]


def _check_prompt_hash_backfill_needed(conn: sqlite3.Connection) -> bool:
    """Check if prompt hash backfill is needed.
    
    Returns True if:
    - Task hasn't been completed AND
    - There are cache files that might need prompt hashes
    """
    if is_task_completed(conn, "prompt_hash_backfill"):
        return False
    
    # Check if there are any conversation directories with cache files
    for base_dir in _get_conversation_base_dirs():
        if not base_dir.exists():
            continue
        for conv_dir in base_dir.iterdir():
            if conv_dir.is_dir():
                cache_file = conv_dir / "objective_analysis.json"
                if cache_file.exists():
                    return True
    
    return False


def _execute_prompt_hash_backfill(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Backfill prompt hashes for existing cached analyses.
    
    Since prompt customization hasn't been released yet, all existing
    cached analyses used the default prompts. We can safely compute
    the hash from the current default prompts.
    """
    import json as json_module
    from ohtv.prompts import get_prompt_hash
    
    # Collect all cache files
    cache_files = []
    for base_dir in _get_conversation_base_dirs():
        if not base_dir.exists():
            continue
        for conv_dir in base_dir.iterdir():
            if conv_dir.is_dir():
                cache_file = conv_dir / "objective_analysis.json"
                if cache_file.exists():
                    cache_files.append(cache_file)
    
    total = len(cache_files)
    updated_files = 0
    updated_entries = 0
    
    for i, cache_file in enumerate(cache_files):
        if on_progress:
            on_progress(i, total)
        
        try:
            data = json_module.loads(cache_file.read_text())
            
            # Skip if not valid format
            if "analyses" not in data:
                continue
            
            modified = False
            analyses = data["analyses"]
            
            for cache_key, analysis in analyses.items():
                # Skip if already has prompt_hash
                if analysis.get("prompt_hash"):
                    continue
                
                # Extract detail_level and assess from the analysis
                detail_level = analysis.get("detail_level", "brief")
                assess = analysis.get("assess", False)
                
                # Determine prompt name
                if assess:
                    prompt_name = f"{detail_level}_assess"
                else:
                    prompt_name = detail_level
                
                # Get hash for this prompt
                try:
                    prompt_hash = get_prompt_hash(prompt_name)
                    analysis["prompt_hash"] = prompt_hash
                    modified = True
                    updated_entries += 1
                except (ValueError, FileNotFoundError):
                    # Unknown prompt, skip
                    log.debug("Unknown prompt %s in cache %s", prompt_name, cache_file)
                    continue
            
            # Save if modified
            if modified:
                cache_file.write_text(json_module.dumps(data, indent=2, default=str))
                updated_files += 1
                
        except (json_module.JSONDecodeError, OSError) as e:
            log.debug("Failed to process cache file %s: %s", cache_file, e)
            continue
    
    if on_progress:
        on_progress(total, total)
    
    return {
        "files_scanned": total,
        "files_updated": updated_files,
        "entries_updated": updated_entries,
    }


# =============================================================================
# Task: Orphaned Embedding Cleanup (after migration 010)
# =============================================================================

def _check_orphaned_embeddings_cleanup_needed(conn: sqlite3.Connection) -> bool:
    """Check if orphaned embedding cleanup is needed.
    
    Returns True if:
    - Task hasn't been completed AND
    - There are orphaned analysis embeddings (legacy NULL cache_key or
      cache_key not in analysis_cache)
    """
    if is_task_completed(conn, "orphaned_embeddings_cleanup_010"):
        return False
    
    from ohtv.db.stores import EmbeddingStore
    embed_store = EmbeddingStore(conn)
    orphaned_count = embed_store.count_orphaned_analysis_embeddings()
    return orphaned_count > 0


def _execute_orphaned_embeddings_cleanup(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Delete orphaned analysis embeddings.
    
    Removes analysis embeddings that have NULL cache_key (legacy) or
    have a cache_key that doesn't exist in analysis_cache.
    """
    from ohtv.db.stores import EmbeddingStore
    
    embed_store = EmbeddingStore(conn)
    
    # Get count for progress reporting
    orphaned_count = embed_store.count_orphaned_analysis_embeddings()
    
    if on_progress:
        on_progress(0, orphaned_count)
    
    # Delete orphaned embeddings
    deleted = embed_store.delete_orphaned_analysis_embeddings()
    
    if on_progress:
        on_progress(deleted, deleted)
    
    return {"orphaned_found": orphaned_count, "deleted": deleted}


# =============================================================================
# Task: Sync-state scalar backfill (Issue #114 Phase B, migration 018)
# =============================================================================
#
# Migration 018 created the empty ``sync_kv`` table; Phase B of #114
# (this codebase) makes sync write the three top-level manifest scalars
# (``last_sync_at`` / ``sync_count`` / ``failed_ids``) there as the
# canonical store. The reader (``SyncManager.__init__``) prefers the
# DB and falls back to the manifest for the cold-upgrade window — but
# every command that opens the DB through ``ensure_db_ready`` also
# runs this one-time backfill so the fallback path stays cold after
# the first invocation. The backfill is idempotent: re-running it
# against an already-mirrored DB is a no-op.

def _check_sync_state_backfill_needed(conn: sqlite3.Connection) -> bool:
    """Return True if any of the three Phase B scalars is missing.

    Returns True iff:

    * The maintenance task has not been recorded as complete AND
    * The manifest exists with at least one non-default value AND
    * At least one of the three Phase B keys is absent from
      ``sync_kv`` (i.e. the cold-upgrade gap is observably open).

    Tolerates a missing manifest (nothing to copy → mark complete
    immediately so future calls short-circuit) and any sqlite/JSON
    error (treated as "nothing to do this run").
    """
    if is_task_completed(conn, "sync_state_backfill_114"):
        return False

    # Avoid importing ohtv.sync (heavyweight; pulls httpx etc.). Read
    # the manifest directly through the same path resolver sync uses.
    try:
        from ohtv.config import get_manifest_path
    except Exception:  # pragma: no cover - defensive
        return False
    try:
        manifest_path = get_manifest_path()
    except Exception:  # pragma: no cover - defensive
        return False

    if not manifest_path.exists():
        # Nothing to backfill — record the task as complete so we
        # don't reopen this path on every command. Caller (which runs
        # us via ``run_maintenance``) handles the actual write.
        return False

    try:
        manifest_data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(manifest_data, dict):
        return False

    # "Worth backfilling" means the manifest carries at least one
    # observable scalar. A bare-empty manifest contributes nothing.
    has_value = (
        bool(manifest_data.get("last_sync_at"))
        or int(manifest_data.get("sync_count") or 0) > 0
        or bool(manifest_data.get("failed_ids"))
    )
    if not has_value:
        return False

    # Now check the DB side. The keys live in ``sync_kv``; missing
    # rows mean the cold-upgrade gap is open and we should backfill.
    try:
        from ohtv.db.stores.sync_state_store import (
            KEY_FAILED_IDS,
            KEY_LAST_SYNC_AT,
            KEY_SYNC_COUNT,
            SyncStateStore,
        )
    except Exception:  # pragma: no cover - defensive
        return False

    try:
        state = SyncStateStore(conn)
        # The "is missing" predicate uses a sentinel so we can
        # distinguish "row absent" from "row stored explicit NULL"
        # (which Phase B treats as canonical → no backfill needed).
        _sentinel = object()
        for key in (KEY_LAST_SYNC_AT, KEY_SYNC_COUNT, KEY_FAILED_IDS):
            if state.get(key, _sentinel) is _sentinel:
                return True
    except sqlite3.Error:
        return False

    return False


def _execute_sync_state_backfill(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Copy manifest scalars into ``sync_kv`` for any missing key.

    Idempotent. Touches only keys that are not already present in
    ``sync_kv`` — Phase B's dual-write contract treats the DB as
    canonical once populated, so we must not clobber a DB value with
    a stale manifest value during backfill.
    """
    try:
        from ohtv.config import get_manifest_path
    except Exception:  # pragma: no cover - defensive
        return {"backfilled": 0}
    try:
        from ohtv.db.stores.sync_state_store import (
            KEY_FAILED_IDS,
            KEY_LAST_SYNC_AT,
            KEY_SYNC_COUNT,
            SyncStateStore,
        )
    except Exception:  # pragma: no cover - defensive
        return {"backfilled": 0}

    try:
        manifest_path = get_manifest_path()
    except Exception:  # pragma: no cover - defensive
        return {"backfilled": 0}

    if not manifest_path.exists():
        return {"backfilled": 0}

    try:
        manifest_data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"backfilled": 0}
    if not isinstance(manifest_data, dict):
        return {"backfilled": 0}

    state = SyncStateStore(conn)
    _sentinel = object()

    candidates: list[tuple[str, object]] = []
    if state.get(KEY_LAST_SYNC_AT, _sentinel) is _sentinel:
        ls = manifest_data.get("last_sync_at")
        if isinstance(ls, str) and ls:
            candidates.append((KEY_LAST_SYNC_AT, ls))
    if state.get(KEY_SYNC_COUNT, _sentinel) is _sentinel:
        sc = manifest_data.get("sync_count")
        # Coerce truthy ints; leave bool out of the int branch
        if isinstance(sc, int) and not isinstance(sc, bool):
            candidates.append((KEY_SYNC_COUNT, sc))
    if state.get(KEY_FAILED_IDS, _sentinel) is _sentinel:
        fi = manifest_data.get("failed_ids")
        if isinstance(fi, list):
            candidates.append((KEY_FAILED_IDS, [str(x) for x in fi]))

    total = len(candidates)
    backfilled = 0
    for i, (key, value) in enumerate(candidates):
        if on_progress:
            on_progress(i, total)
        state.set(key, value)
        backfilled += 1
    if on_progress:
        on_progress(total, total)

    return {"backfilled": backfilled, "manifest_path": str(manifest_path)}


# =============================================================================
# Task Registry
# =============================================================================

MAINTENANCE_TASKS: list[MaintenanceTask] = [
    MaintenanceTask(
        name="metadata_backfill_006",
        description="Indexing conversation metadata",
        triggered_by="migration_006",
        check_needed=_check_metadata_backfill_needed,
        execute=_execute_metadata_backfill,
    ),
    MaintenanceTask(
        name="cache_index_backfill_005",
        description="Indexing analysis cache",
        triggered_by="migration_005",
        check_needed=_check_cache_index_needed,
        execute=_execute_cache_index_backfill,
    ),
    MaintenanceTask(
        name="prompt_hash_backfill",
        description="Backfilling prompt hashes for cache invalidation",
        triggered_by="feature_prompt_customization",
        check_needed=_check_prompt_hash_backfill_needed,
        execute=_execute_prompt_hash_backfill,
    ),
    MaintenanceTask(
        name="orphaned_embeddings_cleanup_010",
        description="Cleaning up orphaned analysis embeddings",
        triggered_by="migration_010",
        check_needed=_check_orphaned_embeddings_cleanup_needed,
        execute=_execute_orphaned_embeddings_cleanup,
    ),
    MaintenanceTask(
        name="sync_state_backfill_114",
        description="Copying sync-state scalars from manifest to sync_kv",
        triggered_by="migration_018",
        check_needed=_check_sync_state_backfill_needed,
        execute=_execute_sync_state_backfill,
    ),
]


def get_pending_tasks(conn: sqlite3.Connection) -> list[MaintenanceTask]:
    """Get list of maintenance tasks that need to run."""
    pending = []
    for task in MAINTENANCE_TASKS:
        try:
            if task.check_needed(conn):
                pending.append(task)
        except Exception as e:
            log.debug("Error checking task %s: %s", task.name, e)
    return pending


def run_maintenance(
    conn: sqlite3.Connection,
    on_task_start: Callable[[MaintenanceTask], None] | None = None,
    on_task_progress: Callable[[MaintenanceTask, int, int], None] | None = None,
    on_task_complete: Callable[[MaintenanceTask, dict], None] | None = None,
) -> dict[str, dict]:
    """Run all pending maintenance tasks.
    
    Args:
        conn: Database connection
        on_task_start: Called when a task starts
        on_task_progress: Called with progress (current, total) during task
        on_task_complete: Called when a task completes with results
    
    Returns:
        Dict mapping task_name to results dict
    """
    results = {}
    
    for task in get_pending_tasks(conn):
        if on_task_start:
            on_task_start(task)
        
        # Create progress callback for this task
        progress_cb = None
        if on_task_progress:
            def progress_cb(current: int, total: int, t=task):
                on_task_progress(t, current, total)
        
        try:
            task_results = task.execute(conn, progress_cb)
            mark_task_completed(conn, task.name, task.triggered_by, task_results)
            results[task.name] = task_results
            
            if on_task_complete:
                on_task_complete(task, task_results)
                
        except Exception as e:
            log.error("Maintenance task %s failed: %s", task.name, e)
            results[task.name] = {"error": str(e)}
    
    return results


def ensure_db_ready(
    conn: sqlite3.Connection,
    show_progress: bool = True,
) -> None:
    """Ensure database is fully ready for use.
    
    This runs migrations and any pending maintenance tasks.
    Call this before using the database in CLI commands.
    
    Args:
        conn: Database connection
        show_progress: If True, show progress for long-running tasks
    """
    from ohtv.db import migrate
    
    # Run any pending migrations
    migrate(conn)
    
    # Check for pending maintenance
    pending = get_pending_tasks(conn)
    if not pending:
        return
    
    # Run maintenance with optional progress display
    if show_progress:
        from rich.console import Console

        from ohtv.progress import make_progress

        console = Console()

        with make_progress(
            console=console,
            show_rate=False,
            show_remaining=False,
            show_eta=False,
        ) as progress:
            current_task_id = None
            
            def on_start(task: MaintenanceTask):
                nonlocal current_task_id
                current_task_id = progress.add_task(task.description, total=100)
            
            def on_progress(task: MaintenanceTask, current: int, total: int):
                if current_task_id is not None and total > 0:
                    progress.update(current_task_id, completed=current * 100 // total)
            
            def on_complete(task: MaintenanceTask, results: dict):
                if current_task_id is not None:
                    progress.update(current_task_id, completed=100)
            
            run_maintenance(conn, on_start, on_progress, on_complete)
    else:
        run_maintenance(conn)
    
    conn.commit()
