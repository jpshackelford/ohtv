"""Data store for the cloud-listing snapshot table (Issue #111).

The ``cloud_listing`` table (added by migration 018 in Issue #112) is the
authoritative snapshot of what the cloud says is visible — populated by a
full listing pass at the top of every ``ohtv sync``. The four-way set-diff
helpers (:meth:`missing_locally`, :meth:`stale_locally`,
:meth:`removed_from_cloud`) compare the snapshot against the local
``conversations`` table and drive the set-diff sync engine.

Snapshot lifecycle:

* :meth:`start_snapshot` allocates a fresh UUID. Rows written under that
  UUID are tentative — readers can keep using whatever the previous
  snapshot wrote.
* :meth:`upsert_row` is called per-page during the listing pass. Pages
  commit incrementally (the caller commits the connection) so an
  interrupted sync can resume mid-listing.
* :meth:`commit_snapshot` atomically swaps to the new snapshot by
  pruning every row whose ``snapshot_id`` does not match. Returns the
  number of rows pruned.
* :meth:`abandon_snapshot` is the failure-path counterpart: it deletes
  only rows for the in-flight snapshot, leaving the previous one
  untouched. This is what makes "mid-listing failure leaves prior
  snapshot intact" hold.

Set-diff queries return raw conversation-id strings (normalized,
dashless per AGENTS.md item #14). Callers join back to
:meth:`get_rows` / :meth:`get` for full payloads.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone


# Whitelisted columns we write into ``cloud_listing`` from a listing
# payload. Keeps :meth:`upsert_row` insensitive to extra keys the API
# may return now or in the future.
_LISTING_COLUMNS = (
    "title",
    "created_at",
    "updated_at",
    "selected_repository",
    "selected_branch",
    "git_provider",
    "trigger",
    "parent_conversation_id",
    "tags",
    "sub_conversation_ids",
    "pr_number",
)


# Columns whose listing-payload value may be a dict/list and must be
# JSON-encoded before binding into sqlite3.
_JSON_COLUMNS = frozenset({"tags", "sub_conversation_ids"})


def _serialize(col: str, value):
    """Coerce a listing-payload value into a sqlite-bindable scalar."""
    if value is None:
        return None
    if col in _JSON_COLUMNS:
        if isinstance(value, (dict, list)):
            return json.dumps(value)
    return value


def _normalize_id(conv_id: str) -> str:
    """Strip dashes from a conversation id (AGENTS.md item #14)."""
    return conv_id.replace("-", "")


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp for ``fetched_at`` bookkeeping."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CloudListingStore:
    """Read/write helpers for the ``cloud_listing`` snapshot table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # Snapshot lifecycle
    # ------------------------------------------------------------------
    def start_snapshot(self) -> str:
        """Allocate a new snapshot id (UUID4 hex string).

        Returns the id — callers pass it into :meth:`upsert_row` and
        either :meth:`commit_snapshot` (success) or
        :meth:`abandon_snapshot` (failure).
        """
        return uuid.uuid4().hex

    def upsert_row(
        self,
        snapshot_id: str,
        row: dict,
        *,
        fetched_at: str | None = None,
    ) -> None:
        """Insert or replace a single cloud-listing row.

        The primary key is ``conversation_id`` (normalized). Any row
        already present — under the same OR a different snapshot — is
        overwritten. This is what gives us pagination dedup for free:
        when keyset drift makes the same id appear on two pages, the
        second insert just overwrites the first.

        ``row`` MUST contain an ``id`` key (the conversation id from
        the listing payload). All other keys are best-effort: unknown
        keys are ignored, missing keys default to NULL. The fully
        permissive shape matches the cloud's eventual schema growth.
        """
        conv_id = row.get("id")
        if not conv_id:
            raise ValueError("cloud_listing row missing 'id'")
        normalized = _normalize_id(conv_id)

        values: list[object] = [normalized]
        for col in _LISTING_COLUMNS:
            values.append(_serialize(col, row.get(col)))
        values.append(fetched_at or _utc_now_iso())
        values.append(snapshot_id)

        placeholders = ", ".join(["?"] * (len(_LISTING_COLUMNS) + 3))
        columns = (
            "conversation_id, "
            + ", ".join(_LISTING_COLUMNS)
            + ", fetched_at, snapshot_id"
        )
        self.conn.execute(
            f"INSERT OR REPLACE INTO cloud_listing ({columns}) "
            f"VALUES ({placeholders})",
            values,
        )

    def commit_snapshot(self, snapshot_id: str) -> int:
        """Atomically swap to ``snapshot_id`` by pruning older rows.

        Deletes every row whose ``snapshot_id`` does NOT match. Returns
        the number of rows pruned. Safe to call repeatedly — the second
        call is a no-op because everything is already on this snapshot.
        """
        cursor = self.conn.execute(
            "DELETE FROM cloud_listing WHERE snapshot_id != ?",
            (snapshot_id,),
        )
        return cursor.rowcount or 0

    def abandon_snapshot(self, snapshot_id: str) -> int:
        """Drop in-flight rows; leave any prior committed snapshot intact.

        The failure-path counterpart to :meth:`commit_snapshot`. Returns
        the number of rows deleted.
        """
        cursor = self.conn.execute(
            "DELETE FROM cloud_listing WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        return cursor.rowcount or 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, conversation_id: str) -> sqlite3.Row | None:
        """Fetch one row by (dashed-or-undashed) conversation id."""
        normalized = _normalize_id(conversation_id)
        return self.conn.execute(
            "SELECT * FROM cloud_listing WHERE conversation_id = ?",
            (normalized,),
        ).fetchone()

    def get_rows(self, conversation_ids: Iterable[str]) -> list[sqlite3.Row]:
        """Fetch many rows in one query (preserves DB-returned order)."""
        ids = [_normalize_id(c) for c in conversation_ids]
        if not ids:
            return []
        placeholders = ", ".join(["?"] * len(ids))
        return list(
            self.conn.execute(
                f"SELECT * FROM cloud_listing WHERE conversation_id IN ({placeholders})",
                ids,
            )
        )

    def count(self) -> int:
        """Number of rows in the current cloud_listing snapshot."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cloud_listing"
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    # ------------------------------------------------------------------
    # Set-diff helpers
    # ------------------------------------------------------------------
    def missing_locally(self) -> Iterator[str]:
        """Cloud-listing ids absent from the local ``conversations`` table.

        These are the rows the engine must download. Includes both
        "never seen" rows and rows whose local row was scrubbed (e.g.
        manual delete).
        """
        cursor = self.conn.execute(
            """
            SELECT cl.conversation_id
            FROM cloud_listing cl
            LEFT JOIN conversations c ON c.id = cl.conversation_id
            WHERE c.id IS NULL
            """
        )
        for row in cursor:
            yield row["conversation_id"]

    def stale_locally(self) -> Iterator[str]:
        """Local rows whose ``cloud_updated_at`` differs from the cloud snapshot.

        Rule (Issue #111 scenario #3 — "Backdated ``updated_at`` is
        honored on next sync"):

        * ``cloud_listing.updated_at`` differs (``!=``) from
          ``conversations.cloud_updated_at`` → stale. We use ``!=``
          rather than ``>`` so a server-side rewind (e.g. clock skew
          on the cloud side, manual backfill) is reconciled rather
          than swallowed.
        * ``conversations.cloud_updated_at IS NULL`` → stale (never
          recorded; the migration-018 design note treats NULL as
          "always stale until first cursor write").
        * Same timestamp on both sides → fresh; not yielded.
        """
        cursor = self.conn.execute(
            """
            SELECT cl.conversation_id
            FROM cloud_listing cl
            JOIN conversations c ON c.id = cl.conversation_id
            WHERE cl.updated_at IS NOT NULL
              AND (
                c.cloud_updated_at IS NULL
                OR cl.updated_at != c.cloud_updated_at
              )
            """
        )
        for row in cursor:
            yield row["conversation_id"]

    def removed_from_cloud(self) -> Iterator[str]:
        """Local rows that disappeared from the cloud listing.

        #111 detects these but does NOT delete them — the repair UX
        (#113) owns the four-category report and any prune action.

        Filters to ``source = 'cloud'`` so CLI-only / LXA-only
        conversations are not falsely reported as removed.
        """
        cursor = self.conn.execute(
            """
            SELECT c.id
            FROM conversations c
            LEFT JOIN cloud_listing cl ON cl.conversation_id = c.id
            WHERE cl.conversation_id IS NULL
              AND c.source = 'cloud'
            """
        )
        for row in cursor:
            yield row["id"]
