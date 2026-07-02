"""Migration 026: conversation_synthesis table for LLM synthesis result caching.

Issue #191. LLM synthesis operations (``gen titles``, ``gen objs``, future
``report worklog``) are expensive and slow, and lack effective caching.
This migration adds a centralized cache table for synthesis results with
automatic invalidation based on conversation updates.

The new ``conversation_synthesis`` table stores:

1. Cached synthesis results per conversation (title, objective, worklog purpose)
2. Validation fields for cache invalidation (updated_at, version, model)
3. Metadata for cost tracking (tokens_used, synthesized_at)

Cache behavior (most-recent synthesis per conversation):

The table stores **one** synthesis result per conversation (most recent).
When you generate a title/objective with a different model, the previous
result is **overwritten**. This is intentional - the cache tracks "what was
most recently synthesized" rather than maintaining separate results per model.

Cache invalidation conditions:

- Conversation updated (``conversation_updated_at`` changed)
- Synthesis schema version changed (prompt updated)
- Different model requested (triggers cache miss, then overwrites on store)
- User forces refresh with ``--force`` flag

Key distinction from existing ``analysis_cache`` table:

- ``analysis_cache``: Tracks multiple analysis variants (context_level,
  detail_level, assess) per conversation in file-based cache
- ``conversation_synthesis``: Stores single "most recent" synthesis result
  per conversation for fast retrieval in display/reporting

The two systems coexist:

- ``gen objs`` continues using file-based cache for analysis variants
- ``gen objs`` also populates synthesis cache with "default" objective
- ``gen titles`` uses only synthesis cache (no multiple variants)

This migration is purely additive. Older ``ohtv`` binaries running
against a post-026 DB will ignore the table gracefully.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 026: add ``conversation_synthesis`` table."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_synthesis (
            conversation_id TEXT PRIMARY KEY,
            conversation_updated_at TEXT NOT NULL,

            -- Cached synthesis results (NULL if not synthesized)
            synthesized_title TEXT,
            synthesized_objective TEXT,
            worklog_purpose TEXT,

            -- Synthesis metadata
            synthesis_model TEXT,
            synthesis_version TEXT NOT NULL,
            synthesized_at TEXT NOT NULL,
            tokens_used INTEGER,

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

    # Index on model for filtering by which model was most recently used
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_synthesis_model
        ON conversation_synthesis(synthesis_model)
    """)
