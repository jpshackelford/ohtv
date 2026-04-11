"""Data store for conversations."""

import sqlite3
from datetime import datetime, timezone

from ohtv.db.models import Conversation


class ConversationStore:
    """Data access for conversations."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, conversation: Conversation) -> None:
        """Insert or update a conversation.
        
        On insert, sets registered_at to current time if not provided.
        On update, preserves original registered_at.
        """
        registered_at = conversation.registered_at or datetime.now(timezone.utc)
        registered_at_str = registered_at.isoformat() if registered_at else None
        
        self.conn.execute(
            """
            INSERT INTO conversations (id, location, registered_at, events_mtime, event_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location = excluded.location,
                events_mtime = excluded.events_mtime,
                event_count = excluded.event_count
            """,
            (
                conversation.id,
                conversation.location,
                registered_at_str,
                conversation.events_mtime,
                conversation.event_count,
            ),
        )
    
    def get(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        cursor = self.conn.execute(
            "SELECT id, location, registered_at, events_mtime, event_count FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row:
            registered_at = None
            if row["registered_at"]:
                registered_at = datetime.fromisoformat(row["registered_at"])
            return Conversation(
                id=row["id"],
                location=row["location"],
                registered_at=registered_at,
                events_mtime=row["events_mtime"],
                event_count=row["event_count"] or 0,
            )
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
            "SELECT id, location, registered_at, events_mtime, event_count FROM conversations"
        )
        results = []
        for row in cursor.fetchall():
            registered_at = None
            if row["registered_at"]:
                registered_at = datetime.fromisoformat(row["registered_at"])
            results.append(Conversation(
                id=row["id"],
                location=row["location"],
                registered_at=registered_at,
                events_mtime=row["events_mtime"],
                event_count=row["event_count"] or 0,
            ))
        return results
    
    def count(self) -> int:
        """Return count of registered conversations."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM conversations")
        return cursor.fetchone()[0]
