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
    - Cache files exist on disk
    """
    if is_task_completed(conn, "cache_index_backfill_005"):
        return False
    
    # Check if analysis_cache table is empty
    cursor = conn.execute("SELECT COUNT(*) FROM analysis_cache")
    cache_count = cursor.fetchone()[0]
    if cache_count > 0:
        # Already has data, mark as done
        return False
    
    # Check if cache files exist
    from ohtv.config import get_ohtv_dir
    cache_dir = get_ohtv_dir() / "cache" / "analysis"
    if not cache_dir.exists():
        return False
    
    # Check if there are any cache files
    cache_files = list(cache_dir.glob("*.json"))
    return len(cache_files) > 0


def _execute_cache_index_backfill(
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Index existing cache files into the database.
    
    This reads all JSON cache files and creates corresponding entries
    in the analysis_cache and analysis_skips tables.
    """
    import json as json_module
    from ohtv.config import get_ohtv_dir
    from ohtv.db.stores import AnalysisCacheStore
    from ohtv.db.stores.analysis_cache_store import AnalysisCacheEntry, AnalysisSkipEntry
    from ohtv.analysis.cache import make_cache_key
    
    cache_dir = get_ohtv_dir() / "cache" / "analysis"
    if not cache_dir.exists():
        return {"cached": 0, "skipped": 0}
    
    store = AnalysisCacheStore(conn)
    cache_files = list(cache_dir.glob("*.json"))
    
    total = len(cache_files)
    cached_count = 0
    skipped_count = 0
    
    for i, cache_file in enumerate(cache_files):
        if on_progress:
            on_progress(i, total)
        
        try:
            data = json_module.loads(cache_file.read_text())
            conv_id = cache_file.stem  # Filename without .json
            
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
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        
        console = Console()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            transient=True,
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
