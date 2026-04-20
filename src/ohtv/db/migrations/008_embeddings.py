"""Add embeddings table and FTS5 for semantic search.

Creates tables for:
- embeddings: Stores embedding vectors as BLOBs for semantic search
- conversation_fts: FTS5 virtual table for keyword search fallback

Design decisions:
- Use BLOBs + numpy for vectors (zero platform risk, proven approach)
- Store dimensions in table for model flexibility
- FTS5 for --exact keyword search fallback
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the embeddings schema."""

    # Embeddings table for semantic search
    # - embedding stored as BLOB (struct-packed float32 array)
    # - dimensions stored to handle model changes gracefully
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            dimensions INTEGER NOT NULL,
            model TEXT NOT NULL,
            token_count INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    # FTS5 virtual table for keyword search (--exact flag)
    # Uses porter stemming and unicode61 tokenizer
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
            conversation_id UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
    """)
