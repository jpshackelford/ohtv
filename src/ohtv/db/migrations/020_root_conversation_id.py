"""Migration 020: root_conversation_id on conversations + roll-up view.

Issue #122 — foundation for "the root conversation is the unit of
'what the user did'; subs are agent-delegation implementation
detail."

Issue #108 / migration 019 added ``conversations.parent_conversation_id``
populated from the cloud listing payload. This migration adds the
single, indexed source of truth for **"what is the root of conversation
X"** so downstream commands can aggregate at the root grain without
recursive CTEs on every read.

Three additions, one migration:

1. ``conversations.root_conversation_id TEXT NULL`` — additive column,
   nullable so older sqlite3 versions can ALTER TABLE ADD COLUMN. New
   rows written by ``ConversationStore.upsert`` /
   ``ConversationStore.record_cloud_download`` will populate it at
   write time. Existing rows are backfilled in this migration.

2. ``CREATE INDEX idx_conversations_root ON
   conversations(root_conversation_id)`` — supports
   ``GROUP BY root_conversation_id`` and ``WHERE root_conversation_id
   = ?`` queries from ``list_roots`` and the ``conversations_by_root``
   view. Not partial — every row has a value after backfill.

3. ``CREATE VIEW conversations_by_root`` — group-by-root projection
   that rolls up display fields (``title``, ``source``,
   ``selected_repository``, ``labels``) from the root's row,
   time fields as ``MIN(created_at)`` / ``MAX(updated_at)`` across the
   subtree, ``event_count`` as ``SUM``, and adds ``conversation_count``
   / ``sub_count`` to let ``db status`` and follow-on commands show
   "(+N subs)" annotations.

Backfill is iterative in Python rather than ``WITH RECURSIVE`` for
two reasons: (a) we cap at 8 hops as a safety bound against
accidental cycles or self-referential rows, and (b) it keeps the
migration trivial to reason about on the small data volumes we see
(thousands of rows, today's depth = 1).

Orphan subs whose parent isn't in the local DB (because the parent
trajectory hasn't been synced yet, or the parent is a delegation root
on a different account) fall back to ``root_conversation_id = id`` —
they become their own root for reporting purposes. Better than
``NULL`` because every downstream query gets a value to group by;
better than crashing because partial syncs are a reality.

Per AGENTS.md item #14, all conversation IDs are stored dashless. The
backfill normalizes nothing — it reads ``id`` and
``parent_conversation_id`` verbatim (migrations 012 and 019 already
guarantee they're in canonical form).

Manifest contract is unchanged: ``root_conversation_id`` is DB-only
metadata, consistent with item #27 ("manifest as canonical metadata
source") — the manifest is the cache for cloud-side EDITABLE metadata
only. Structural relationships (parent/root) live in the DB. Mirrors
the same ownership shape as ``parent_conversation_id`` (migration
019).

This migration is purely additive. An older ``ohtv`` binary running
against a post-020 DB behaves identically to one without it — the
extra column / index / view are invisible to code paths that don't
reference them.
"""

import logging
import sqlite3

log = logging.getLogger(__name__)


# Safety bound on the iterative backfill walk. Today's data is
# 1-level (parent → sub); 8 is paranoia, not necessity. A real cycle
# (which the cloud should never produce) terminates the loop and the
# offending row gets ``root_conversation_id = id`` as the orphan
# fallback.
_MAX_HOPS = 8


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 020: column + index + view + backfill."""

    # --- 1. column add (idempotent) -----------------------------------
    cursor = conn.execute("PRAGMA table_info(conversations)")
    existing = {row[1] for row in cursor.fetchall()}
    if "root_conversation_id" not in existing:
        conn.execute(
            "ALTER TABLE conversations "
            "ADD COLUMN root_conversation_id TEXT"
        )

    # --- 2. index (idempotent) ---------------------------------------
    # Not partial — every row gets a value after backfill, and the
    # GROUP BY / equality queries downstream commands will issue all
    # benefit from a full index.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_root "
        "ON conversations(root_conversation_id)"
    )

    # --- 3. backfill --------------------------------------------------
    # Phase A: roots — every row with NULL parent IS its own root.
    # This also covers all ``source='local'`` rows (local CLI has no
    # delegation).
    conn.execute(
        "UPDATE conversations "
        "SET root_conversation_id = id "
        "WHERE parent_conversation_id IS NULL "
        "  AND root_conversation_id IS NULL"
    )

    # Phase B: iterative walk for subs. Each pass resolves rows whose
    # parent already has a ``root_conversation_id`` set, so after at
    # most ``depth`` passes the entire DAG is covered. Bounded by
    # ``_MAX_HOPS`` to bail out on accidental cycles.
    for _ in range(_MAX_HOPS):
        cursor = conn.execute(
            "UPDATE conversations "
            "SET root_conversation_id = ("
            "  SELECT p.root_conversation_id "
            "  FROM conversations p "
            "  WHERE p.id = conversations.parent_conversation_id"
            ") "
            "WHERE root_conversation_id IS NULL "
            "  AND parent_conversation_id IS NOT NULL "
            "  AND EXISTS ("
            "    SELECT 1 FROM conversations p "
            "    WHERE p.id = conversations.parent_conversation_id "
            "      AND p.root_conversation_id IS NOT NULL"
            "  )"
        )
        if cursor.rowcount == 0:
            break

    # Phase C: orphans — subs whose parent isn't in the local DB at
    # all. Treat them as their own root for reporting purposes (logged
    # so the operator notices if it happens at volume). We also catch
    # any rows that survived the hop cap (cycle pathological).
    cursor = conn.execute(
        "SELECT COUNT(*) FROM conversations "
        "WHERE root_conversation_id IS NULL "
        "  AND parent_conversation_id IS NOT NULL"
    )
    orphan_count = cursor.fetchone()[0]
    if orphan_count > 0:
        log.info(
            "migration 020: %d sub-conversation(s) have a "
            "parent_conversation_id pointing at a row absent from the "
            "local DB; treating as their own root for aggregation.",
            orphan_count,
        )
        conn.execute(
            "UPDATE conversations "
            "SET root_conversation_id = id "
            "WHERE root_conversation_id IS NULL "
            "  AND parent_conversation_id IS NOT NULL"
        )

    # Post-backfill invariant: every row has a root.
    cursor = conn.execute(
        "SELECT COUNT(*) FROM conversations "
        "WHERE root_conversation_id IS NULL"
    )
    remaining = cursor.fetchone()[0]
    assert remaining == 0, (
        f"migration 020 backfill left {remaining} rows with "
        "root_conversation_id IS NULL"
    )

    # --- 4. view ------------------------------------------------------
    # ``conversations_by_root`` rolls subtree rows up onto the root.
    # Display fields take the root's value; time fields span the
    # subtree; quantitative fields sum.
    #
    # Avoiding the SQLite 3.30+ ``FILTER`` clause for broader
    # compatibility — ``MAX(CASE WHEN id = root_conversation_id THEN
    # col END)`` is the equivalent idiom. There is at most one row per
    # tree where ``id = root_conversation_id`` (the root itself), so
    # the ``MAX`` is just "pick the root's value".
    #
    # ``conversation_count - 1 = sub_count`` lets callers display
    # "(+2 subs)" or similar without a second query.
    conn.execute("DROP VIEW IF EXISTS conversations_by_root")
    conn.execute(
        """
        CREATE VIEW conversations_by_root AS
        SELECT
            root_conversation_id AS id,
            MAX(CASE WHEN id = root_conversation_id THEN title END)
                AS title,
            MAX(CASE WHEN id = root_conversation_id THEN source END)
                AS source,
            MAX(CASE WHEN id = root_conversation_id
                     THEN selected_repository END)
                AS selected_repository,
            MAX(CASE WHEN id = root_conversation_id THEN labels END)
                AS labels,
            MAX(CASE WHEN id = root_conversation_id
                     THEN location END)
                AS location,
            MIN(created_at)              AS created_at,
            MAX(updated_at)              AS updated_at,
            COALESCE(SUM(event_count), 0) AS event_count,
            COUNT(*)                     AS conversation_count,
            COUNT(*) - 1                 AS sub_count
        FROM conversations
        WHERE root_conversation_id IS NOT NULL
        GROUP BY root_conversation_id
        """
    )
