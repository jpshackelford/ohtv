"""Add context_level to analysis_skips table.

The skip cache was previously keyed only by conversation_id, which meant
that skipping a conversation at a lower context level (e.g., 'minimal')
would prevent retry at a higher context level (e.g., 'full').

This migration adds a context_level column to track the context level
at which the skip occurred. Existing entries default to 'minimal' (the
lowest context level).

With this change:
- Skip at 'minimal' allows retry at 'default' or 'full'
- Skip at 'default' allows retry at 'full'
- Skip at 'full' blocks all context levels (highest includes everything)
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add context_level column to analysis_skips."""
    conn.execute("""
        ALTER TABLE analysis_skips
        ADD COLUMN context_level TEXT NOT NULL DEFAULT 'minimal'
    """)
