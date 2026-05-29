"""Migration 019: parent_conversation_id on conversations.

Issue #108. The cloud listing endpoint
``GET /api/v1/app-conversations/search`` returns a
``parent_conversation_id`` field for every conversation (NULL for
root conversations, the parent's id for sub-conversations spawned by
agent delegation / sub-agent flows). Until this migration the
``conversations`` table had no column to persist that value, so
parent/child relationships were only knowable by re-querying the
cloud.

Two additions, one migration:

1. ``conversations.parent_conversation_id TEXT NULL`` — additive
   column. NULL for every existing row (organic backfill on the next
   ``ohtv sync`` after #108 lands, by way of
   ``Syncer._update_manifest_entry`` writing through
   :meth:`ConversationStore.record_cloud_download` with the new
   field). The cloud listing already carries the value; no separate
   fetch and no migration-time write are required. Local CLI
   conversations remain NULL forever (delegation is a cloud-only
   concept today).

2. ``CREATE INDEX idx_conversations_parent ON
   conversations(parent_conversation_id)`` — supports the followup
   roll-up queries cluster (issues #122..#128) that filter or join
   on this column. Cheap on the ~thousands-of-rows catalogs we see
   in practice.

Manifest contract is unchanged: ``parent_conversation_id`` is
DB-only metadata, consistent with item #27 ("manifest as canonical
metadata source") in AGENTS.md — sync owns this column for
``source='cloud'`` rows; NULL elsewhere. Mirrors the same ownership
shape as ``cloud_updated_at`` (migration 018) and ``labels``
(migration 015).

This migration is purely additive. An older ``ohtv`` binary running
against a post-019 DB behaves identically to one without it — the
extra column and index are invisible to code paths that don't
reference them.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 019: add ``parent_conversation_id`` + index."""

    # Idempotent column add (older SQLite versions we support don't
    # honor IF NOT EXISTS on ALTER TABLE ADD COLUMN).
    cursor = conn.execute("PRAGMA table_info(conversations)")
    existing = {row[1] for row in cursor.fetchall()}
    if "parent_conversation_id" not in existing:
        conn.execute(
            "ALTER TABLE conversations "
            "ADD COLUMN parent_conversation_id TEXT"
        )

    # Partial index — only the (typically small) subset of rows whose
    # ``parent_conversation_id`` is non-NULL needs to be indexed for
    # the parent-lookup / child-enumeration queries that the followup
    # roll-up cluster will issue. Keeps the index footprint minimal on
    # accounts that don't use delegation.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_parent "
        "ON conversations(parent_conversation_id) "
        "WHERE parent_conversation_id IS NOT NULL"
    )
