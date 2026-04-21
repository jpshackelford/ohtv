"""Add support for multiple embedding types per conversation.

Changes the embeddings table to support:
- Multiple embeddings per conversation (analysis, summary, content chunks)
- embed_type column to distinguish between types
- chunk_index for content chunks (0 for non-chunked types)
- source_text to store the original text that was embedded (for RAG context)

Also adds embedding_chunks table for efficient chunk retrieval in RAG.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Migrate to multi-embedding schema."""
    
    # Check if we need to migrate (does embed_type column exist?)
    cursor = conn.execute("PRAGMA table_info(embeddings)")
    columns = {row[1] for row in cursor.fetchall()}
    
    if "embed_type" in columns:
        # Already migrated
        return
    
    # Rename old table
    conn.execute("ALTER TABLE embeddings RENAME TO embeddings_old")
    
    # Create new embeddings table with composite primary key
    # embed_type: 'analysis', 'summary', 'content'
    # chunk_index: 0 for analysis/summary, 0+ for content chunks
    conn.execute("""
        CREATE TABLE embeddings (
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
    conn.execute("CREATE INDEX idx_embeddings_conv ON embeddings(conversation_id)")
    conn.execute("CREATE INDEX idx_embeddings_type ON embeddings(embed_type)")
    
    # Migrate existing embeddings as 'summary' type (they were lean transcripts)
    conn.execute("""
        INSERT INTO embeddings (
            conversation_id, embed_type, chunk_index, embedding, 
            dimensions, model, token_count, created_at
        )
        SELECT 
            conversation_id, 'summary', 0, embedding,
            dimensions, model, token_count, created_at
        FROM embeddings_old
    """)
    
    # Drop old table
    conn.execute("DROP TABLE embeddings_old")
