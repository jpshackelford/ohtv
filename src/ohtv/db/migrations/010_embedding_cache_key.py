"""Add cache_key column to embeddings table.

This enables tracking which analysis variant (cache_key) each embedding
corresponds to. A conversation may have multiple cached analyses with
different parameters (e.g., assess=True vs assess=False), and we want
to embed each variant separately.

Schema change:
- Add cache_key column (TEXT NOT NULL DEFAULT '')
- Rebuild table with new primary key including cache_key
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add cache_key to embeddings and rebuild with new primary key."""
    
    # SQLite doesn't support adding columns to primary key directly,
    # so we need to recreate the table
    
    # 1. Create new table with cache_key in primary key
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings_new (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            embed_type TEXT NOT NULL CHECK(embed_type IN ('analysis', 'summary', 'content')),
            chunk_index INTEGER NOT NULL DEFAULT 0,
            cache_key TEXT NOT NULL DEFAULT '',
            embedding BLOB NOT NULL,
            dimensions INTEGER NOT NULL,
            model TEXT NOT NULL,
            token_count INTEGER,
            source_text TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, embed_type, chunk_index, cache_key)
        )
    """)
    
    # 2. Copy existing data (cache_key defaults to '')
    conn.execute("""
        INSERT INTO embeddings_new (
            conversation_id, embed_type, chunk_index, cache_key,
            embedding, dimensions, model, token_count, source_text, created_at
        )
        SELECT 
            conversation_id, embed_type, chunk_index, '',
            embedding, dimensions, model, token_count, source_text, created_at
        FROM embeddings
    """)
    
    # 3. Drop old table
    conn.execute("DROP TABLE embeddings")
    
    # 4. Rename new table
    conn.execute("ALTER TABLE embeddings_new RENAME TO embeddings")
    
    # 5. Recreate indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(embed_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_cache_key ON embeddings(cache_key)")
