"""Engagement (sustained-attention) metric per conversation.

Adds ``conversation_engagement``: one row per conversation, holding the
engaged-human-minutes metric computed by the ``engagement`` processing
stage (Issue #163).

``threshold_seconds`` is stored on every row so values computed under
different thresholds remain distinguishable during the empirical
T-tuning sweep. ``first_event_ts`` / ``last_event_ts`` /
``total_duration_seconds`` are normalized on ``last - first`` event
timestamps (not ``updated_at - created_at``) so the three reported
numbers (engaged, periods, total) are self-consistent.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the conversation_engagement table + threshold index."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_engagement (
            conversation_id TEXT PRIMARY KEY,

            -- Inputs to the calculation (so we can re-derive / re-tune).
            threshold_seconds INTEGER NOT NULL,
            first_event_ts TEXT,
            last_event_ts TEXT,
            total_duration_seconds INTEGER,

            -- The metric.
            engaged_seconds INTEGER NOT NULL DEFAULT 0,
            attention_periods INTEGER NOT NULL DEFAULT 0,

            -- Supporting counts (sanity checks + ratio queries).
            follow_up_user_message_count INTEGER NOT NULL DEFAULT 0,
            attended_user_message_count INTEGER NOT NULL DEFAULT 0,

            -- Processing metadata.
            processed_at TEXT NOT NULL,
            event_count INTEGER NOT NULL,

            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_engagement_threshold "
        "ON conversation_engagement(threshold_seconds)"
    )
