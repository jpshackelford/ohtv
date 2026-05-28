"""Migration 018: Schema additions for set-diff sync.

Issue #112. Schema-only. No code path in ``src/ohtv/`` outside this file
reads or writes any of the new objects in this PR; that work belongs to
#111 (the set-diff sync engine, which populates ``cloud_listing`` and
the snapshot-state keys in ``sync_kv``) and #114 (which drains the
remaining manifest scalars into ``sync_kv`` and retires
``sync_manifest.json``). #113 will consume the set-diff query helpers
once #111 lands. An older ``ohtv`` binary against a post-018 DB
behaves identically to one without it — every addition here is purely
additive.

Three additions, one migration:

1. ``cloud_listing`` — snapshot table for the most-recently-completed
   cloud listing. Columns map to the
   ``/api/v1/app-conversations/search`` ``items[]`` payload documented
   in ``REFERENCE_CLOUD_API.md``. ``conversation_id`` is the
   normalized (dashless) form per AGENTS.md item #14. No FK to
   ``conversations.id`` because the entire point of the table is to
   surface cloud-only rows (the gap that motivated this work). The
   set-diff queries are ``cloud_listing LEFT JOIN conversations``
   (missing-locally) and the inverse (removed-from-cloud / stale).
   ``snapshot_id`` allows incremental page-by-page commits during a
   listing run; #111 swaps snapshots atomically by deleting rows whose
   ``snapshot_id`` does not match the freshly-committed listing.

2. ``conversations.cloud_updated_at`` — records the cloud's
   ``updated_at`` at the time of last download. Distinct from
   ``conversations.updated_at`` (event-derived, per migration 006).
   The set-diff "stale locally" check is
   ``cloud_listing.updated_at > conversations.cloud_updated_at``.
   Backfilled in this migration from
   ``~/.ohtv/sync_manifest.json``'s
   ``conversations[id]["updated_at"]`` where both sides resolve to the
   same normalized id. Backfill is read-only with respect to the
   manifest, and is tolerant of a missing, empty, or malformed
   manifest (any such case leaves the column NULL, which the set-diff
   correctly treats as "always stale" — forcing a re-fetch on next
   sync).

3. ``sync_kv`` — key/value table for the sync-state scalars currently
   scattered across ``sync_manifest.json``'s top-level fields. #114
   will populate this from the manifest and retire the JSON file;
   #111 will write the new snapshot bookkeeping keys
   (``last_snapshot_id``, ``last_snapshot_completed_at``,
   ``last_snapshot_count``). #112 just creates the empty table — no
   migration-time writes against it. The schema is intentionally
   minimal: callers JSON-encode values, so the set of accepted keys
   stays open without further migrations.
"""

import json
import logging
import sqlite3

log = logging.getLogger("ohtv")


def _normalize_conversation_id(conv_id: str) -> str:
    """Strip dashes from a conversation id per AGENTS.md item #14.

    The conversations table stores dashless IDs; the sync manifest
    historically wrote both shapes depending on which code path
    produced the entry. Normalizing on read keeps the backfill match
    correct.
    """
    return conv_id.replace("-", "")


def _backfill_cloud_updated_at(conn: sqlite3.Connection) -> None:
    """Backfill ``conversations.cloud_updated_at`` from the sync manifest.

    Read-only with respect to the manifest. Tolerant of:

    * Missing manifest file (most users on a fresh install).
    * Malformed JSON (logged, treated as empty).
    * Missing ``conversations`` key in the JSON.
    * Per-conversation entries lacking ``updated_at``.
    * Manifest IDs that are dashed while the DB stores them dashless
      (the normalization step makes the match symmetric).

    Any conversation whose manifest entry has no usable
    ``updated_at`` is left with ``cloud_updated_at = NULL``, which the
    set-diff correctly interprets as "always stale" — the next sync
    will re-fetch it and write the cursor at that point.
    """

    # Local import to avoid pulling ohtv.config into the migration
    # loader's eager-import tree (matches the pattern used in
    # migration 013).
    try:
        from ohtv.config import get_manifest_path
    except Exception:  # pragma: no cover - defensive
        log.warning("Migration 018: cannot import ohtv.config; skipping backfill")
        return

    try:
        manifest_path = get_manifest_path()
    except Exception:  # pragma: no cover - defensive
        log.warning("Migration 018: cannot resolve manifest path; skipping backfill")
        return

    if not manifest_path.exists():
        log.info(
            "Migration 018: no sync_manifest.json at %s; "
            "cloud_updated_at left NULL for all rows",
            manifest_path,
        )
        return

    try:
        manifest_data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "Migration 018: could not read/parse %s (%s); "
            "cloud_updated_at left NULL",
            manifest_path,
            exc,
        )
        return

    if not isinstance(manifest_data, dict):
        log.warning(
            "Migration 018: %s is not a JSON object; skipping backfill",
            manifest_path,
        )
        return

    conversations = manifest_data.get("conversations")
    if not isinstance(conversations, dict):
        log.info(
            "Migration 018: manifest has no 'conversations' mapping; "
            "nothing to backfill"
        )
        return

    updates: list[tuple[str, str]] = []
    for raw_id, entry in conversations.items():
        if not isinstance(entry, dict):
            continue
        updated_at = entry.get("updated_at")
        if not updated_at or not isinstance(updated_at, str):
            continue
        norm_id = _normalize_conversation_id(raw_id)
        if not norm_id:
            continue
        updates.append((updated_at, norm_id))

    if not updates:
        log.info(
            "Migration 018: manifest had no usable updated_at entries; "
            "cloud_updated_at left NULL"
        )
        return

    # The UPDATE matches only conversations already present in the DB.
    # Manifest entries with no corresponding row are silently skipped —
    # #111 will write a cloud_listing row for them on the next sync.
    conn.executemany(
        "UPDATE conversations SET cloud_updated_at = ? WHERE id = ?",
        updates,
    )
    log.info(
        "Migration 018: backfilled cloud_updated_at for up to %d "
        "manifest entries (DB rows updated where ids match)",
        len(updates),
    )


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 018: set-diff sync schema."""

    # 1. cloud_listing table -------------------------------------------------
    #
    # NB: no FOREIGN KEY to conversations(id). Cloud-only rows must be
    # representable — they are the entire reason this table exists.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_listing (
            conversation_id          TEXT PRIMARY KEY,

            -- Cloud-listing payload fields (subset of items[] that the
            -- set-diff loop + repair UX need). Timestamps are ISO 8601
            -- UTC strings, matching conversations.created_at /
            -- updated_at convention.
            title                    TEXT,
            created_at               TEXT,
            updated_at               TEXT,
            selected_repository      TEXT,
            selected_branch          TEXT,
            git_provider             TEXT,
            trigger                  TEXT,
            parent_conversation_id   TEXT,
            tags                     TEXT,
            sub_conversation_ids     TEXT,
            pr_number                TEXT,

            -- Bookkeeping
            fetched_at               TEXT NOT NULL,
            snapshot_id              TEXT NOT NULL
        )
        """
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cloud_listing_updated_at "
        "ON cloud_listing(updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cloud_listing_snapshot "
        "ON cloud_listing(snapshot_id)"
    )

    # 2. conversations.cloud_updated_at -------------------------------------
    #
    # Add the column idempotently (PRAGMA-driven check; ALTER TABLE
    # ADD COLUMN does not support IF NOT EXISTS in older SQLite
    # versions we still support).
    cursor = conn.execute("PRAGMA table_info(conversations)")
    existing = {row[1] for row in cursor.fetchall()}
    if "cloud_updated_at" not in existing:
        conn.execute("ALTER TABLE conversations ADD COLUMN cloud_updated_at TEXT")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_cloud_updated_at "
        "ON conversations(cloud_updated_at)"
    )

    # 3. sync_kv table ------------------------------------------------------
    #
    # Empty at create time. #114 fills it from the manifest; #111
    # writes the snapshot-state keys. Documented (non-exhaustive) keys
    # the schema is expected to accept:
    #
    #   last_sync_at                  (UX field; #114)
    #   sync_count                    (running counter; #114)
    #   failed_ids                    (JSON array; #114)
    #   last_snapshot_id              (UUID; #111)
    #   last_snapshot_completed_at    (ISO 8601 UTC; #111)
    #   last_snapshot_count           (int; #111)
    #
    # The schema does NOT enforce a key allow-list so future scalars
    # land without another migration.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_kv (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT NOT NULL
        )
        """
    )

    # 4. Backfill cloud_updated_at from the manifest -----------------------
    #
    # Idempotent because the UPDATE only touches rows whose id is
    # present in the manifest, and re-running it would write the same
    # values.
    _backfill_cloud_updated_at(conn)
