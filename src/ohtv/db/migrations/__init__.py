"""Database migration system.

Simple, file-based migrations for SQLite. Each migration is a Python file
in this directory named with a numeric prefix (e.g., 001_initial.py).

Migrations are applied in order and tracked in a _migrations table.
"""

import importlib.util
import sqlite3
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parent


def get_applied_migrations(conn: sqlite3.Connection) -> set[str]:
    """Get set of migration names that have been applied."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor = conn.execute("SELECT name FROM _migrations")
    return {row[0] for row in cursor.fetchall()}


def get_pending_migrations() -> list[Path]:
    """Get list of migration files in order."""
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.py")):
        migrations.append(path)
    return migrations


def apply_migration(conn: sqlite3.Connection, migration_path: Path) -> None:
    """Apply a single migration file."""
    spec = importlib.util.spec_from_file_location(migration_path.stem, migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration: {migration_path}")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if not hasattr(module, "upgrade"):
        raise RuntimeError(f"Migration {migration_path.name} missing upgrade() function")
    
    module.upgrade(conn)
    conn.execute("INSERT INTO _migrations (name) VALUES (?)", (migration_path.name,))


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply all pending migrations.
    
    Args:
        conn: Database connection
        
    Returns:
        List of migration names that were applied
    """
    applied = get_applied_migrations(conn)
    pending = get_pending_migrations()
    
    newly_applied = []
    for migration_path in pending:
        if migration_path.name not in applied:
            apply_migration(conn, migration_path)
            newly_applied.append(migration_path.name)
    
    conn.commit()
    return newly_applied
