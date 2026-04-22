"""Add summary column to conversations table.

Stores conversation summaries in the database for:
- Fast RAG retrieval (no need to read analysis JSON files)
- Contextual chunk enrichment in embeddings
- Display in citation output

The summary is populated during embedding generation or can be
generated separately via `ohtv db process objective`.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add summary column to conversations table."""
    # Summary text for RAG and contextual embeddings
    conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT")
