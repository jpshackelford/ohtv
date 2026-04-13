"""Add processing stage tracking for incremental ingestion.

Adds columns to conversations for change detection:
- registered_at: When conversation was first discovered
- events_mtime: Unix timestamp of events directory (for fast change detection)
- event_count: Number of events (checkpoint for incremental processing)

Creates conversation_stages table to track which processing stages
have been completed for each conversation, enabling:
- Independent processing jobs (refs, objectives, summary, etc.)
- Incremental processing (only process new events)
- Async processing (register fast, process later)
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the processing stages schema."""
    
    # Add tracking columns to conversations
    conn.execute("ALTER TABLE conversations ADD COLUMN registered_at TEXT")
    conn.execute("ALTER TABLE conversations ADD COLUMN events_mtime REAL")
    conn.execute("ALTER TABLE conversations ADD COLUMN event_count INTEGER DEFAULT 0")
    
    # Processing stages table - tracks completion of each stage per conversation
    conn.execute("""
        CREATE TABLE conversation_stages (
            conversation_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            PRIMARY KEY (conversation_id, stage),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_stages_stage ON conversation_stages(stage)")
    conn.execute("CREATE INDEX idx_stages_conversation ON conversation_stages(conversation_id)")
