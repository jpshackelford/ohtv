"""Migration 026: conversation_synthesis table for LLM synthesis result caching.

Issue #191. LLM synthesis operations (``gen titles``, ``gen objs``, future
``report worklog``) are expensive and slow, and lack effective caching.
This migration adds a centralized cache table for synthesis results with
automatic invalidation based on conversation updates.

The new ``conversation_synthesis`` table stores:

1. Cached synthesis results per conversation (title, objective, worklog purpose)
2. Validation fields for cache invalidation (updated_at, version, model)
3. Metadata for cost tracking (tokens_used, synthesized_at)

Cache invalidation conditions:

- Conversation updated (``conversation_updated_at`` changed)
- Synthesis schema version changed (prompt updated)
- Different model requested
- User forces refresh with ``--force`` flag

Key distinction from existing ``analysis_cache`` table:

- ``analysis_cache``: Tracks multiple analysis variants (context_level,
  detail_level, assess) per conversation in file-based cache
- ``conversation_synthesis``: Stores synthesis results per conversation
  per model for fast retrieval in display/reporting, supporting
  multi-model caching where different models can cache independently

The two systems coexist:

- ``gen objs`` continues using file-based cache for analysis variants
- ``gen objs`` also populates synthesis cache with "default" objective
- ``gen titles`` uses only synthesis cache (supports multiple models)

This migration is purely additive. Older ``ohtv`` binaries running
against a post-026 DB will ignore the table gracefully.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 026: add ``conversation_synthesis`` table."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_synthesis (
            conversation_id TEXT NOT NULL,
            conversation_updated_at TEXT NOT NULL,

            -- Cached synthesis results (NULL if not synthesized)
            synthesized_title TEXT,
            synthesized_objective TEXT,
            worklog_purpose TEXT,

            -- Synthesis metadata
            synthesis_model TEXT NOT NULL,
            synthesis_version TEXT NOT NULL,
            synthesized_at TEXT NOT NULL,
            tokens_used INTEGER,

            PRIMARY KEY (conversation_id, synthesis_model),
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id)
                ON DELETE CASCADE
        )
    """)

    # Index on updated_at for cache staleness queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_synthesis_updated
        ON conversation_synthesis(conversation_updated_at)
    """)

    # Index on model for multi-model caching queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_synthesis_model
        ON conversation_synthesis(synthesis_model)
    """)
