"""Add maintenance_tasks table for tracking one-time operations.

This table tracks maintenance tasks that should only run once, such as:
- Backfilling metadata after a migration adds new columns
- Indexing cache files after a migration adds cache tables

Each task is identified by name and includes the version/migration that
triggered it, allowing the system to automatically run required maintenance
without user intervention.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create maintenance_tasks table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_tasks (
            task_name TEXT PRIMARY KEY,
            completed_at TEXT NOT NULL,
            triggered_by TEXT,  -- Migration or feature that triggered this task
            details TEXT        -- JSON with task-specific details (rows affected, etc.)
        )
    """)
