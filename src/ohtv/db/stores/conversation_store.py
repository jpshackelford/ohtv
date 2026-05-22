"""Data store for conversations."""

import json
import sqlite3
from datetime import datetime, timezone

from ohtv.db.models import Conversation


class ConversationStore:
    """Data access for conversations."""
    
    # All columns for SELECT queries
    _ALL_COLUMNS = """
        id, location, registered_at, events_mtime, event_count,
        title, created_at, updated_at, selected_repository, source, summary, labels
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
        )
    
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
        
        self.conn.execute(
            """
            INSERT INTO conversations (
                id, location, registered_at, events_mtime, event_count,
                title, created_at, updated_at, selected_repository, source, summary, labels
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                labels = excluded.labels
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
    ) -> list[Conversation]:
        """List conversations within a date range.
        
        Args:
            since: Include conversations created on or after this time
            until: Include conversations created before this time
            source: Filter by source (e.g., 'local', 'cloud')
        
        Returns:
            List of matching conversations, ordered by created_at descending
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
    
    def list_by_source(self, source: str) -> list[Conversation]:
        """List conversations from a specific source."""
        cursor = self.conn.execute(
            f"SELECT {self._ALL_COLUMNS} FROM conversations WHERE source = ?",
            (source,),
        )
        return [self._row_to_conversation(row) for row in cursor.fetchall()]
    
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
    ) -> bool:
        """Update only the title and/or labels for a conversation.

        Used by the metadata-refresh sync path (Issue #86) to propagate
        cloud-side title/label edits without re-downloading trajectories.

        Args:
            conversation_id: Conversation ID. Normalized by stripping dashes
                (see AGENTS.md item 14 on ID normalization).
            title: New title value. Omit (or pass the _UNSET sentinel) to
                leave the column untouched. Pass ``None`` to clear it.
            labels: New labels dict. Omit (or pass the _UNSET sentinel) to
                leave the column untouched. Pass ``None`` or an empty dict
                to clear labels (empty dict is normalized to NULL to match
                ``sources/cloud.py:parse_conversation_info``).

        Returns:
            True if a matching row was updated, False if the conversation
            ID does not exist in the index.
        """
        if title is self._UNSET and labels is self._UNSET:
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
