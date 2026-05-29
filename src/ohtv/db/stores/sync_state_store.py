"""Data store for the ``sync_kv`` key/value table (Issue #111 / #114).

Migration 018 added a minimal K/V table to host the small handful of
sync-state scalars previously scattered across
``~/.ohtv/sync_manifest.json``. The schema is intentionally untyped
(callers JSON-encode values) so new scalars land without further
migrations.

#111 is the first writer; it persists the three ``last_snapshot_*``
keys at the end of every successful listing pass. #114 will later
drain the remaining manifest scalars (``last_sync_at``, ``sync_count``,
``failed_ids``) into the same table and retire the JSON file.

Documented (non-exhaustive) keys:

* ``last_snapshot_id`` (str, UUID-hex) — id of the most-recently-committed
  cloud listing snapshot. Written by #111 at the end of a successful
  listing pass; consumed by ``--status`` UX, ``--repair`` (#113), and a
  future freshness gate.
* ``last_snapshot_completed_at`` (str, ISO 8601 UTC) — wall-clock time
  the snapshot finished. Same writers/readers as above.
* ``last_snapshot_count`` (int) — number of cloud_listing rows in the
  committed snapshot. Same writers/readers.
* ``last_sync_at`` (str, ISO 8601 UTC) — dual-written alongside the
  manifest field of the same name. Pure UX field; never consumed by
  the sync engine as a gate. #111 began the dual-write; #114 Phase B
  completes the read-side flip.
* ``sync_count`` (int) — running counter of successful sync runs.
  Dual-written with the manifest by #114 Phase B.
* ``failed_ids`` (JSON array of str) — conversation ids that failed
  the most recent sync. Dual-written with the manifest by #114 Phase B.
  Stored as a single JSON-encoded array (one row) rather than a row
  per id — the set is small (typically empty or a handful) and the
  read-side wants the whole list at once.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

# Canonical key names for the sync-state scalars drained from the
# manifest by #114 Phase B. Imported by ``ohtv.sync`` so the dual-write
# and overlay paths agree on the spelling.
KEY_LAST_SYNC_AT = "last_sync_at"
KEY_SYNC_COUNT = "sync_count"
KEY_FAILED_IDS = "failed_ids"


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp for ``updated_at`` bookkeeping."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyncStateStore:
    """Get/set wrapper around ``sync_kv`` (JSON-encoded scalars)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, key: str, default: Any = None) -> Any:
        """Return the JSON-decoded value for ``key`` or ``default``.

        A row with a NULL ``value`` decodes back to ``None``.
        """
        row = self.conn.execute(
            "SELECT value FROM sync_kv WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        raw = row["value"]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Tolerate hand-written non-JSON values (e.g. plain strings
            # written by older tooling). Return verbatim.
            return raw

    def set(self, key: str, value: Any) -> None:
        """JSON-encode ``value`` and upsert under ``key``.

        ``None`` is stored as a literal SQL NULL rather than the JSON
        string ``"null"``; this keeps ``SELECT ... WHERE value IS NULL``
        queries from getting confused.
        """
        encoded: str | None
        if value is None:
            encoded = None
        else:
            encoded = json.dumps(value)
        self.conn.execute(
            """
            INSERT INTO sync_kv (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, encoded, _utc_now_iso()),
        )

    def delete(self, key: str) -> bool:
        """Remove ``key`` from ``sync_kv``. Returns True if a row existed."""
        cursor = self.conn.execute("DELETE FROM sync_kv WHERE key = ?", (key,))
        return (cursor.rowcount or 0) > 0
