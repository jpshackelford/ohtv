"""Add labels column for storing cloud-sourced conversation labels.

Labels are stored as a JSON string (dict[str, str]) from the Cloud API's tags field.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add labels column to conversations table."""
    # Add labels column (JSON format: {"key1": "value1", "key2": "value2"})
    conn.execute("""
        ALTER TABLE conversations
        ADD COLUMN labels TEXT DEFAULT NULL
    """)
    
    # Partial index for label presence filtering (labels IS NOT NULL checks).
    # NOTE: This index does NOT accelerate json_extract() queries because SQLite
    # cannot use a column index for JSON path extraction. It only helps queries
    # that filter on labels being non-NULL (e.g., list_with_labels, count_with_labels).
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_labels
        ON conversations(labels)
        WHERE labels IS NOT NULL
    """)
