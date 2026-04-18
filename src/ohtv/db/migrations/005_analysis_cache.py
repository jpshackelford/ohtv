"""Add analysis cache tracking for fast cache status checks.

Adds tables for tracking LLM analysis cache state:
- analysis_cache: Records cached analyses by conversation and parameter key
- analysis_skips: Records conversations that cannot be analyzed

This enables O(1) cache status lookup via database query instead of
O(N) file reads when checking which conversations need analysis.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the analysis cache schema."""
    
    # Analysis cache table - tracks cached analyses
    # Each unique combination of parameters gets its own row
    conn.execute("""
        CREATE TABLE analysis_cache (
            conversation_id TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            analyzed_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, cache_key),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_analysis_cache_conv ON analysis_cache(conversation_id)")
    
    # Analysis skips table - tracks conversations that can't be analyzed
    conn.execute("""
        CREATE TABLE analysis_skips (
            conversation_id TEXT NOT NULL PRIMARY KEY,
            event_count INTEGER NOT NULL,
            reason TEXT NOT NULL,
            skipped_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
