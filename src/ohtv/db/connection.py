"""Database connection management."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from ohtv.config import get_ohtv_dir


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
