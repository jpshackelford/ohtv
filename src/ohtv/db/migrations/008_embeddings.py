"""Add embeddings table and FTS5 for semantic search.

Creates tables for:
- embeddings: Stores embedding vectors as BLOBs for semantic search
  - Supports multiple embedding types per conversation (analysis, summary, content)
  - Stores source_text for RAG context retrieval
- conversation_fts: FTS5 virtual table for keyword search fallback

Design decisions:
- Use BLOBs + numpy for vectors (zero platform risk, proven approach)
- Store dimensions in table for model flexibility
- FTS5 for --exact keyword search fallback
- Composite primary key (conversation_id, embed_type, chunk_index) for multi-embedding support
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the embeddings schema."""

    # Embeddings table for semantic search
    # - embedding stored as BLOB (struct-packed float32 array)
    # - dimensions stored to handle model changes gracefully
    # - embed_type: 'analysis', 'summary', 'content'
    # - chunk_index: 0 for analysis/summary, 0+ for content chunks
    # - source_text: original text that was embedded (for RAG context)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            embed_type TEXT NOT NULL CHECK(embed_type IN ('analysis', 'summary', 'content')),
            chunk_index INTEGER NOT NULL DEFAULT 0,
            embedding BLOB NOT NULL,
            dimensions INTEGER NOT NULL,
            model TEXT NOT NULL,
            token_count INTEGER,
            source_text TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, embed_type, chunk_index)
        )
    """)

    # Create indexes for efficient queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(embed_type)")

    # FTS5 virtual table for keyword search (--exact flag)
    # Uses porter stemming and unicode61 tokenizer
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
            conversation_id UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
    """)
