"""Add indexes on conversation_engagement.last_event_ts and first_event_ts.

Issue #180: enable ``--event-dates`` filtering on ``list`` / ``search`` /
``ask`` / ``gen objs`` / ``gen titles`` / ``gen run``. The new
:meth:`ConversationStore.list_by_event_date_range` method runs WHERE
clauses against ``last_event_ts`` (--since) and ``first_event_ts``
(--until); without these indexes the planner would scan the whole
``conversation_engagement`` table per query.

Migration 023 already shipped ``idx_conv_engagement_threshold`` (a
single-column index on ``threshold_seconds``); these two are sibling
indexes on the timestamp columns we now filter on.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the two timestamp indexes on ``conversation_engagement``."""

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_engagement_last_event_ts "
        "ON conversation_engagement(last_event_ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_engagement_first_event_ts "
        "ON conversation_engagement(first_event_ts)"
    )
