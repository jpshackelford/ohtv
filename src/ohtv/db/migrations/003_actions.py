"""Add actions table for tracking conversation activities.

Creates an `actions` table to store recognized actions from conversations.
Actions include file edits, git operations, PR/issue activities, etc.

The table supports:
- Multiple actions per conversation
- Flexible metadata via JSON column
- Linking back to source events
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the actions table."""
    
    # Actions table: tracks recognized actions in conversations
    conn.execute("""
        CREATE TABLE actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            target TEXT,
            metadata TEXT,
            event_id TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    
    # Index for querying by conversation
    conn.execute("CREATE INDEX idx_actions_conversation ON actions(conversation_id)")
    
    # Index for querying by action type (e.g., find all PRs opened)
    conn.execute("CREATE INDEX idx_actions_type ON actions(action_type)")
    
    # Composite index for finding specific actions in a conversation
    conn.execute("CREATE INDEX idx_actions_conv_type ON actions(conversation_id, action_type)")
