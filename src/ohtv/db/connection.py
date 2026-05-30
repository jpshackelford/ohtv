"""Database connection management."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from ohtv.config import get_ohtv_dir

__all__ = ["get_db_path", "get_connection", "get_ready_connection"]


def get_db_path() -> Path:
    """Get the path to the SQLite database file.
    
    Default location: ~/.ohtv/index.db
    Can be overridden with OHTV_DB_PATH environment variable.
    """
    env_path = os.environ.get("OHTV_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return get_ohtv_dir() / "index.db"


@contextmanager
def get_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with proper settings.
    
    Args:
        db_path: Optional path to database. Uses default if not provided.
        
    Yields:
        sqlite3.Connection configured for our use case.
    """
    if db_path is None:
        db_path = get_db_path()
    
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Enable WAL mode for better concurrent access (allows parallel readers/writers)
    conn.execute("PRAGMA journal_mode = WAL")
    
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_ready_connection(
    db_path: Path | None = None,
    *,
    show_progress: bool = False,
) -> Generator[sqlite3.Connection, None, None]:
    """Open a connection with migrations + maintenance already applied.

    This is the canonical entry point for production code that touches the
    SQLite index. It composes :func:`get_connection` and
    :func:`ohtv.db.maintenance.ensure_db_ready` so callers cannot forget the
    migration step and the AGENTS.md item #25 "automatic maintenance" promise
    holds for every command.

    Use this instead of the lower-level pattern::

        with get_connection() as conn:
            migrate(conn)
            ...

    The low-level primitives (:func:`get_connection`,
    :func:`ohtv.db.migrations.migrate`, and
    :func:`ohtv.db.maintenance.ensure_db_ready`) remain public for tests and
    for the rare callers that need direct control (e.g. ``ohtv db init``,
    which displays the list of newly-applied migration names).

    Args:
        db_path: Optional DB path override (for tests / ``OHTV_DB_PATH``).
        show_progress: If True, surfaces maintenance progress to the user's
            terminal. Set by interactive CLI commands; defaults to False so
            library and batch callers don't print spurious progress bars.

    Yields:
        sqlite3.Connection with all pending migrations and maintenance
        tasks applied.
    """
    # Import lazily to avoid a hard circular import between connection and
    # maintenance (maintenance imports migrate from ohtv.db, which imports
    # this module).
    from ohtv.db.maintenance import ensure_db_ready

    with get_connection(db_path) as conn:
        ensure_db_ready(conn, show_progress=show_progress)
        yield conn
