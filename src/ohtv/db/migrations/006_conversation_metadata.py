"""Add metadata columns to conversations table.

Stores conversation metadata (title, timestamps, repository, source) in the
database for fast querying without filesystem I/O.

This enables:
- Fast date-range filtering (no need to read event files)
- Fast title search
- Unified listing across local/cloud/extra sources

The metadata is populated during `db scan` and updated when mtime changes.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add metadata columns to conversations table."""
    
    # Title extracted from base_state.json or first user message
    conn.execute("ALTER TABLE conversations ADD COLUMN title TEXT")
    
    # Timestamps in ISO 8601 format (UTC)
    conn.execute("ALTER TABLE conversations ADD COLUMN created_at TEXT")
    conn.execute("ALTER TABLE conversations ADD COLUMN updated_at TEXT")
    
    # Repository selected for the conversation (if any)
    conn.execute("ALTER TABLE conversations ADD COLUMN selected_repository TEXT")
    
    # Source identifier: 'local', 'cloud', or custom name for extra paths
    conn.execute("ALTER TABLE conversations ADD COLUMN source TEXT")
    
    # Index on created_at for fast date filtering
    conn.execute("CREATE INDEX idx_conversations_created_at ON conversations(created_at)")
    
    # Index on source for filtering by source type
    conn.execute("CREATE INDEX idx_conversations_source ON conversations(source)")
