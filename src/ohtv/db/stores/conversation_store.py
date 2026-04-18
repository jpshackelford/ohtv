"""Data store for conversations."""

import sqlite3
from datetime import datetime, timezone

from ohtv.db.models import Conversation


class ConversationStore:
    """Data access for conversations."""
    
    # All columns for SELECT queries
    _ALL_COLUMNS = """
        id, location, registered_at, events_mtime, event_count,
        title, created_at, updated_at, selected_repository, source
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
        
        self.conn.execute(
            """
            INSERT INTO conversations (
                id, location, registered_at, events_mtime, event_count,
                title, created_at, updated_at, selected_repository, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location = excluded.location,
                events_mtime = excluded.events_mtime,
                event_count = excluded.event_count,
                title = excluded.title,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                selected_repository = excluded.selected_repository,
                source = excluded.source
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
