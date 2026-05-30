"""Data store for conversations."""

import json
import sqlite3
from datetime import datetime, timezone

from ohtv.db.models import Conversation, RootConversation


class ConversationStore:
    """Data access for conversations."""
    
    # All columns for SELECT queries
    _ALL_COLUMNS = """
        id, location, registered_at, events_mtime, event_count,
        title, created_at, updated_at, selected_repository, source, summary, labels,
        parent_conversation_id, root_conversation_id,
        selected_branch, cloud_updated_at
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        """Convert a database row to a Conversation object."""
        registered_at = None
        if row["registered_at"]:
            registered_at = datetime.fromisoformat(row["registered_at"])
        
        created_at = None
        if row["created_at"]:
            created_at = datetime.fromisoformat(row["created_at"])
        
        updated_at = None
        if row["updated_at"]:
            updated_at = datetime.fromisoformat(row["updated_at"])
        
        # Handle summary column gracefully - may not exist in older databases
        summary = None
        try:
            summary = row["summary"]
        except (IndexError, KeyError):
            pass
        
        # Handle labels column gracefully - may not exist in older databases
        labels = None
        try:
            labels_json = row["labels"]
            if labels_json:
                labels = json.loads(labels_json)
        except (IndexError, KeyError, json.JSONDecodeError):
            pass
        
        return Conversation(
            id=row["id"],
            location=row["location"],
            registered_at=registered_at,
            events_mtime=row["events_mtime"],
            event_count=row["event_count"] or 0,
            title=row["title"],
            created_at=created_at,
            updated_at=updated_at,
            selected_repository=row["selected_repository"],
            source=row["source"],
            summary=summary,
            labels=labels,
            parent_conversation_id=self._safe_get(row, "parent_conversation_id"),
            root_conversation_id=self._safe_get(row, "root_conversation_id"),
            # Issue #114 Phase C: ``selected_branch`` is a new column
            # (migration 021); ``cloud_updated_at`` predates Phase C
            # (migration 018 / Issue #112) but its reader path flips
            # here. Both go through ``_safe_get`` so a pre-021 row
            # decoder still works.
            selected_branch=self._safe_get(row, "selected_branch"),
            cloud_updated_at=self._safe_get(row, "cloud_updated_at"),
        )

    def _resolve_root_conversation_id(
        self,
        *,
        conv_id: str,
        incoming_parent_id: str | None,
    ) -> str:
        """Compute the ``root_conversation_id`` to write for ``conv_id``.

        Issue #122. The store owns this column: callers don't pass
        the value, they pass ``parent_conversation_id`` (or None) and
        the store walks the tree.

        The "effective parent" is what the row will look like after the
        ``COALESCE`` merge in :meth:`upsert` /
        :meth:`record_cloud_download`:

        * If ``incoming_parent_id`` is non-None, it wins.
        * Otherwise we read any parent already on the existing row
          (sync may have written it before the scanner re-passes
          without parent context).

        From the effective parent we look up the parent's
        ``root_conversation_id`` and propagate. When the parent isn't
        in the local DB yet (orphan sub — parent trajectory not
        synced, or parent is on a different account), we fall back to
        ``conv_id`` so the sub becomes its own root. That matches the
        migration-time orphan policy and keeps every row groupable.

        Args:
            conv_id: This conversation's id (normalized / dashless).
            incoming_parent_id: Parent id from the incoming upsert
                payload (normalized / dashless). ``None`` means "no
                parent info on this write".

        Returns:
            The ``root_conversation_id`` to write. Always non-None.
        """
        effective_parent_id = incoming_parent_id
        if effective_parent_id is None:
            # The COALESCE on parent_conversation_id will preserve
            # whatever is on the existing row; mirror that here so we
            # resolve from the *effective* post-merge parent.
            cursor = self.conn.execute(
                "SELECT parent_conversation_id "
                "FROM conversations WHERE id = ?",
                (conv_id,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                effective_parent_id = existing["parent_conversation_id"]

        if effective_parent_id is None:
            # Root: own id.
            return conv_id

        # Sub: inherit the parent's root.
        cursor = self.conn.execute(
            "SELECT root_conversation_id "
            "FROM conversations WHERE id = ?",
            (effective_parent_id,),
        )
        parent_row = cursor.fetchone()
        if parent_row is not None and parent_row["root_conversation_id"]:
            return parent_row["root_conversation_id"]

        # Orphan: parent absent from local DB (or its root not yet
        # backfilled — defensive). Treat as own root; matches the
        # migration-time orphan policy in 020.
        return conv_id

    @staticmethod
    def _safe_get(row: sqlite3.Row, column: str):
        """Read ``column`` from ``row``, returning ``None`` if absent.

        Older databases that predate a column-add migration may not
        have the column in their SELECT result set; sqlite3.Row raises
        ``IndexError`` in that case.
        """
        try:
            return row[column]
        except (IndexError, KeyError):
            return None
    
    def upsert(self, conversation: Conversation) -> None:
        """Insert or update a conversation.
        
        On insert, sets registered_at to current time if not provided.
        On update, preserves original registered_at.
        """
        registered_at = conversation.registered_at or datetime.now(timezone.utc)
        registered_at_str = registered_at.isoformat() if registered_at else None
        created_at_str = conversation.created_at.isoformat() if conversation.created_at else None
        updated_at_str = conversation.updated_at.isoformat() if conversation.updated_at else None
        labels_json = json.dumps(conversation.labels) if conversation.labels else None
        
        # Normalize parent id (Issue #108) to the dashless form per
        # AGENTS.md item #14. ``None`` flows through unchanged so we
        # can distinguish "I don't know" from "explicitly root".
        parent_conversation_id = conversation.parent_conversation_id
        if parent_conversation_id:
            parent_conversation_id = parent_conversation_id.replace("-", "")

        # Issue #122: compute ``root_conversation_id`` from the
        # effective parent. The store is the single owner of this
        # column — callers don't pass it. The "effective parent" is
        # what the row will look like after the COALESCE merge:
        # incoming parent if non-None, else any parent already on the
        # existing row. This keeps scanner re-passes that have no
        # parent context idempotent with sync's earlier writeback.
        normalized_id = conversation.id.replace("-", "") if conversation.id else conversation.id
        root_conversation_id = self._resolve_root_conversation_id(
            conv_id=normalized_id,
            incoming_parent_id=parent_conversation_id,
        )

        self.conn.execute(
            """
            INSERT INTO conversations (
                id, location, registered_at, events_mtime, event_count,
                title, created_at, updated_at, selected_repository, source, summary, labels,
                parent_conversation_id, root_conversation_id,
                selected_branch
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location = excluded.location,
                events_mtime = excluded.events_mtime,
                event_count = excluded.event_count,
                title = excluded.title,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                selected_repository = excluded.selected_repository,
                source = excluded.source,
                summary = COALESCE(excluded.summary, conversations.summary),
                labels = excluded.labels,
                -- Preserve a parent id already written by
                -- ``record_cloud_download`` when the scanner does not
                -- carry one (Issue #108). This makes the scanner's
                -- upsert idempotent with respect to sync's earlier
                -- writeback.
                parent_conversation_id = COALESCE(
                    excluded.parent_conversation_id,
                    conversations.parent_conversation_id
                ),
                -- Issue #122: same COALESCE pattern for root. We
                -- resolved a fresh value above based on the
                -- *effective* parent (post-COALESCE), so excluded
                -- usually wins; the COALESCE is the belt-and-braces
                -- guard against a future caller passing ``None`` via
                -- ``conversation.root_conversation_id`` directly.
                root_conversation_id = COALESCE(
                    excluded.root_conversation_id,
                    conversations.root_conversation_id
                ),
                -- Issue #114 Phase C: ``selected_branch`` is owned by
                -- sync (read from the trajectory ZIP's ``meta.json``
                -- at download time). The scanner does not have a
                -- reliable source for it, so we COALESCE-preserve
                -- whatever sync / the migration-021 backfill already
                -- wrote. A scanner pass that does carry a value (e.g.
                -- a future read from ``base_state.json``) wins.
                selected_branch = COALESCE(
                    excluded.selected_branch,
                    conversations.selected_branch
                )
            """,
            (
                conversation.id,
                conversation.location,
                registered_at_str,
                conversation.events_mtime,
                conversation.event_count,
                conversation.title,
                created_at_str,
                updated_at_str,
                conversation.selected_repository,
                conversation.source,
                conversation.summary,
                labels_json,
                parent_conversation_id,
                root_conversation_id,
                conversation.selected_branch,
            ),
        )
    
    def get(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        cursor = self.conn.execute(
            f"SELECT {self._ALL_COLUMNS} FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_conversation(row)
        return None
    
    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return cursor.rowcount > 0
    
    def list_all(self) -> list[Conversation]:
        """List all registered conversations."""
        cursor = self.conn.execute(
            f"SELECT {self._ALL_COLUMNS} FROM conversations"
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]
    
    def list_by_date_range(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        source: str | None = None,
        include_subs: bool = False,
    ) -> list[Conversation]:
        """List conversations within a date range.

        Args:
            since: Include conversations created on or after this time
            until: Include conversations created before this time
            source: Filter by source (e.g., 'local', 'cloud')
            include_subs: When False (default, Issue #125), exclude
                agent-delegated sub-conversations — only rows where
                ``id = root_conversation_id`` are returned. When True,
                subs are included alongside their roots.

        Returns:
            List of matching conversations, ordered by created_at descending

        Raises:
            RuntimeError: when ``include_subs=False`` and migration 020
                (which adds ``root_conversation_id``) has not been
                applied. Callers that genuinely want every row should
                pass ``include_subs=True`` — that path is unaffected
                by the guard.
        """
        conditions = []
        params = []

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if until:
            conditions.append("created_at < ?")
            params.append(until.isoformat())

        if source:
            conditions.append("source = ?")
            params.append(source)

        if not include_subs:
            # Issue #125: roots-only is the default for `gen objs / titles
            # / run` multi-conv mode. The same predicate
            # ``id = root_conversation_id`` matches what ``count_roots``
            # uses. Migration 020 guarantees every row has a non-NULL
            # ``root_conversation_id`` (orphans get their own id), so
            # the predicate covers the whole table without an
            # ``IS NOT NULL`` clause.
            self._assert_root_column_present_for_list("gen")
            conditions.append("id = root_conversation_id")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = self.conn.execute(
            f"""
            SELECT {self._ALL_COLUMNS}
            FROM conversations
            WHERE {where_clause}
            ORDER BY created_at DESC
            """,
            params,
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]

    def _assert_root_column_present_for_list(self, command: str) -> None:
        """Guard for the Issue #125 roots-only predicate on ``list_by_date_range``.

        Mirrors the guards landed in :mod:`ohtv.reports.weekly_counts`
        (#123) and :mod:`ohtv.reports.velocity` (#124). Silently falling
        back to the legacy SQL would reintroduce the duplication-by-sub
        bug this PR fixes, so we fail loudly instead.

        The ``command`` argument is the user-facing command name (e.g.
        ``"gen"``) so the message points at the right CLI surface.
        """
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(conversations)")}
        if "root_conversation_id" not in cols:
            raise RuntimeError(
                f"{command} requires migration 020; "
                f"run 'ohtv db scan' to apply pending migrations"
            )
    
    def list_by_source(self, source: str) -> list[Conversation]:
        """List conversations from a specific source."""
        cursor = self.conn.execute(
            f"SELECT {self._ALL_COLUMNS} FROM conversations WHERE source = ?",
            (source,),
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]

    def list_roots(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        source: str | None = None,
        selected_repository: str | None = None,
    ) -> list[RootConversation]:
        """List root conversations with subtree rolled up. Issue #122.

        Mirrors :meth:`list_by_date_range` (since/until/source) and adds
        ``selected_repository`` — the four filters that downstream
        commands #123–#128 actually need.

        Filter semantics: filters apply at the root grain. A
        ``selected_repository`` set only on a sub does NOT make the
        tree match — the user thinks of the tree as belonging to the
        root. ``source`` likewise compares against the root's row.
        Date filters apply to the rolled-up ``created_at`` (the MIN
        across the subtree), matching "tree's earliest activity".

        Args:
            since: Include trees whose rolled-up ``created_at`` is on
                or after this time.
            until: Include trees whose rolled-up ``created_at`` is
                before this time.
            source: Filter by root's source (e.g., 'local', 'cloud').
            selected_repository: Filter by root's selected_repository.

        Returns:
            List of :class:`RootConversation`, ordered by
            ``created_at`` descending. Each row is a distinct tree
            (one row per root); subs are rolled up onto their root.
        """
        conditions: list[str] = []
        params: list[object] = []

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if until:
            conditions.append("created_at < ?")
            params.append(until.isoformat())

        if source:
            conditions.append("source = ?")
            params.append(source)

        if selected_repository:
            conditions.append("selected_repository = ?")
            params.append(selected_repository)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = self.conn.execute(
            f"""
            SELECT
                id, title, source, selected_repository, labels, location,
                created_at, updated_at, event_count,
                conversation_count, sub_count
            FROM conversations_by_root
            WHERE {where_clause}
            ORDER BY created_at DESC
            """,
            params,
        )
        return [self._row_to_root_conversation(row) for row in cursor.fetchall()]

    def _row_to_root_conversation(self, row: sqlite3.Row) -> RootConversation:
        """Convert a ``conversations_by_root`` view row to a
        :class:`RootConversation`."""
        created_at = None
        if row["created_at"]:
            created_at = datetime.fromisoformat(row["created_at"])

        updated_at = None
        if row["updated_at"]:
            updated_at = datetime.fromisoformat(row["updated_at"])

        labels: dict[str, str] | None = None
        try:
            labels_json = row["labels"]
            if labels_json:
                labels = json.loads(labels_json)
        except (IndexError, KeyError, json.JSONDecodeError):
            pass

        return RootConversation(
            id=row["id"],
            title=self._safe_get(row, "title"),
            source=self._safe_get(row, "source"),
            selected_repository=self._safe_get(row, "selected_repository"),
            labels=labels,
            location=self._safe_get(row, "location"),
            created_at=created_at,
            updated_at=updated_at,
            event_count=row["event_count"] or 0,
            conversation_count=row["conversation_count"] or 1,
            sub_count=row["sub_count"] or 0,
        )

    def count_roots(self) -> int:
        """Return count of root conversations. Issue #122.

        A root is a row whose ``root_conversation_id`` equals its own
        ``id`` — equivalent to "row has no parent in the local DB".
        Cheap (covered by ``idx_conversations_root``).
        """
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE id = root_conversation_id"
        )
        return cursor.fetchone()[0]

    def count_subs(self) -> int:
        """Return count of sub-conversations. Issue #122.

        Inverse of :meth:`count_roots` — rows whose
        ``root_conversation_id`` differs from their own ``id``.
        """
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE id != root_conversation_id "
            "  AND root_conversation_id IS NOT NULL"
        )
        return cursor.fetchone()[0]

    def count_trees_with_subs(self) -> int:
        """Return count of distinct trees that contain at least one sub.

        Issue #122. Used by ``db status`` to report "across N trees".
        A root with zero subs is not counted; a root with two subs
        counts once.
        """
        cursor = self.conn.execute(
            "SELECT COUNT(DISTINCT root_conversation_id) "
            "FROM conversations "
            "WHERE id != root_conversation_id "
            "  AND root_conversation_id IS NOT NULL"
        )
        return cursor.fetchone()[0]

    def count(self) -> int:
        """Return count of registered conversations."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM conversations")
        return cursor.fetchone()[0]
    
    def count_with_metadata(self) -> int:
        """Return count of conversations that have metadata populated."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE created_at IS NOT NULL"
        )
        return cursor.fetchone()[0]
    
    def count_with_summary(self) -> int:
        """Return count of conversations that have summary populated."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE summary IS NOT NULL"
        )
        return cursor.fetchone()[0]
    
    def update_summary(self, conversation_id: str, summary: str) -> bool:
        """Update the summary for a conversation.
        
        Args:
            conversation_id: The conversation ID
            summary: The summary text to set
            
        Returns:
            True if a row was updated, False if conversation not found
        """
        cursor = self.conn.execute(
            "UPDATE conversations SET summary = ? WHERE id = ?",
            (summary, conversation_id),
        )
        return cursor.rowcount > 0

    # Sentinel used by update_metadata() to distinguish "leave unchanged"
    # from "explicitly clear" semantics. Pass a real value (string or None)
    # to write that value; omit the argument (or pass _UNSET) to skip.
    _UNSET: object = object()

    def update_metadata(
        self,
        conversation_id: str,
        *,
        title: str | None | object = _UNSET,
        labels: dict[str, str] | None | object = _UNSET,
        selected_repository: str | None | object = _UNSET,
        created_at: datetime | None | object = _UNSET,
    ) -> bool:
        """Update focused metadata columns for a conversation.

        Used by the metadata-refresh sync path (Issue #86 / #87) to propagate
        cloud-side edits without re-downloading trajectories. Issue #86
        introduced ``title``/``labels``; Issue #87 extends to
        ``selected_repository``/``created_at`` (the remaining listing-API
        fields).

        Args:
            conversation_id: Conversation ID. Normalized by stripping dashes
                (see AGENTS.md item 14 on ID normalization).
            title: New title value. Omit (or pass the _UNSET sentinel) to
                leave the column untouched. Pass ``None`` to clear it.
            labels: New labels dict. Omit (or pass the _UNSET sentinel) to
                leave the column untouched. Pass ``None`` or an empty dict
                to clear labels (empty dict is normalized to NULL to match
                ``sources/cloud.py:parse_conversation_info``).
            selected_repository: New repository value. Same _UNSET vs None
                semantics as ``title``. Issue #87.
            created_at: New created_at value (datetime). Same _UNSET vs None
                semantics. Stored as ISO 8601 string. Issue #87.

        Returns:
            True if a matching row was updated, False if the conversation
            ID does not exist in the index.
        """
        all_unset = (
            title is self._UNSET
            and labels is self._UNSET
            and selected_repository is self._UNSET
            and created_at is self._UNSET
        )
        if all_unset:
            # Nothing to do; treat as a successful no-op only when the row
            # exists, so callers can still distinguish "missing conversation"
            # from a real no-op (matches update_summary semantics).
            cursor = self.conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation_id.replace("-", ""),),
            )
            return cursor.fetchone() is not None

        normalized_id = conversation_id.replace("-", "")

        set_clauses: list[str] = []
        params: list[object] = []

        if title is not self._UNSET:
            set_clauses.append("title = ?")
            params.append(title)

        if labels is not self._UNSET:
            # Normalize empty dict -> None, matching parse_conversation_info.
            labels_value: dict[str, str] | None
            if isinstance(labels, dict) and len(labels) > 0:
                labels_value = labels  # type: ignore[assignment]
            else:
                labels_value = None
            labels_json = json.dumps(labels_value) if labels_value else None
            set_clauses.append("labels = ?")
            params.append(labels_json)

        if selected_repository is not self._UNSET:
            set_clauses.append("selected_repository = ?")
            params.append(selected_repository)

        if created_at is not self._UNSET:
            # Accept datetime or None. We don't accept raw strings — callers
            # already parse listing payloads via _parse_datetime before
            # invoking us.
            if created_at is None:
                params.append(None)
            elif isinstance(created_at, datetime):
                params.append(created_at.isoformat())
            else:
                raise TypeError(
                    f"created_at must be datetime or None, got {type(created_at).__name__}"
                )
            set_clauses.append("created_at = ?")

        params.append(normalized_id)
        sql = f"UPDATE conversations SET {', '.join(set_clauses)} WHERE id = ?"
        cursor = self.conn.execute(sql, params)
        return cursor.rowcount > 0
    
    def list_without_summary(self) -> list[Conversation]:
        """List conversations that don't have a summary yet."""
        cursor = self.conn.execute(
            f"SELECT {self._ALL_COLUMNS} FROM conversations WHERE summary IS NULL"
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]
    
    def list_by_label(self, key: str, value: str) -> list[Conversation]:
        """List conversations with a specific label key=value.
        
        Args:
            key: Label key to filter by
            value: Label value to match
            
        Returns:
            List of matching conversations, ordered by created_at descending
        """
        # Quote the key in JSON path to handle special characters (dots, brackets)
        # e.g., key "env.type" becomes '$."env.type"' instead of '$.env.type'
        cursor = self.conn.execute(
            f"""
            SELECT {self._ALL_COLUMNS}
            FROM conversations
            WHERE json_extract(labels, ?) = ?
            ORDER BY created_at DESC
            """,
            (f'$."{key}"', value),
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]
    
    def list_with_labels(self) -> list[Conversation]:
        """List conversations that have labels.
        
        Returns:
            List of conversations with labels, ordered by created_at descending
        """
        cursor = self.conn.execute(
            f"""
            SELECT {self._ALL_COLUMNS}
            FROM conversations
            WHERE labels IS NOT NULL AND labels != '{{}}'
            ORDER BY created_at DESC
            """
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]
    
    def count_with_labels(self) -> int:
        """Return count of conversations that have labels populated."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE labels IS NOT NULL AND labels != '{}'"
        )
        return cursor.fetchone()[0]

    def record_cloud_download(
        self,
        conversation_id: str,
        *,
        location: str,
        cloud_updated_at: str | None,
        parent_conversation_id: str | None = None,
        selected_branch: str | None = None,
    ) -> None:
        """Record that the cloud trajectory for ``conversation_id`` was just synced.

        Inserts a minimal row if the conversation has not been seen
        before (location + source='cloud' + cloud_updated_at +
        parent_conversation_id + selected_branch), or updates only
        ``location``, ``cloud_updated_at``,
        ``parent_conversation_id``, and ``selected_branch`` on an
        existing row. Crucially, this method NEVER overwrites
        metadata columns (``title``, ``event_count``, ``labels``,
        etc.) — those are owned by the scanner / LLM analysis paths.

        This is the writer for the columns reserved by migration 018
        (Issue #112 — ``cloud_updated_at``), migration 019
        (Issue #108 — ``parent_conversation_id``), and migration 021
        (Issue #114 Phase C — ``selected_branch``). Issue #111 is
        the first consumer of ``cloud_updated_at``; ``ohtv sync`` is
        the first consumer of ``parent_conversation_id``; Issue #114
        Phase C is the first consumer of ``selected_branch`` (mirrored
        from the trajectory ZIP's ``meta.json`` — the listing API
        doesn't carry this field).

        ``parent_conversation_id`` is normalized (dashes stripped) on
        write to match the rest of the conversations table per
        AGENTS.md item #14. ``None`` means "root conversation"; the
        column distinguishes the row.

        ``selected_branch`` carries through as-is; ``None`` means
        "no branch info available" (e.g. detached HEAD, or the
        trajectory pre-dates the field). Callers should pass
        ``None`` when the field is missing — explicitly clearing the
        column requires an empty string today (matching the rest of
        the cloud metadata cache).
        """
        normalized = conversation_id.replace("-", "")
        normalized_parent = (
            parent_conversation_id.replace("-", "")
            if parent_conversation_id
            else None
        )
        registered_at = datetime.now(timezone.utc).isoformat()

        # Issue #122: resolve root_conversation_id at write time. The
        # store owns this column; sync passes parent only, we walk
        # the tree.
        root_conversation_id = self._resolve_root_conversation_id(
            conv_id=normalized,
            incoming_parent_id=normalized_parent,
        )

        # INSERT path: we don't know the metadata yet. The scanner will
        # backfill on its next run. We set event_count=0 so a
        # subsequent scanner mtime check still treats the row as
        # "needs work" (an mtime delta vs the freshly-extracted events
        # dir always wins).
        #
        # Issue #114 Phase C: ``selected_branch`` participates in
        # COALESCE-preserve on update. Sync's typical case is that the
        # value moves from None → "main" on first download and then
        # stays put; but a re-download that produces no branch info
        # (None) should never clobber a previously-recorded value.
        self.conn.execute(
            """
            INSERT INTO conversations (
                id, location, registered_at, event_count, source,
                cloud_updated_at, parent_conversation_id,
                root_conversation_id, selected_branch
            )
            VALUES (?, ?, ?, 0, 'cloud', ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location = excluded.location,
                cloud_updated_at = excluded.cloud_updated_at,
                parent_conversation_id = excluded.parent_conversation_id,
                root_conversation_id = COALESCE(
                    excluded.root_conversation_id,
                    conversations.root_conversation_id
                ),
                selected_branch = COALESCE(
                    excluded.selected_branch,
                    conversations.selected_branch
                )
            """,
            (
                normalized,
                location,
                registered_at,
                cloud_updated_at,
                normalized_parent,
                root_conversation_id,
                selected_branch,
            ),
        )
