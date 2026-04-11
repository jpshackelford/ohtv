"""Data store for conversations."""

import sqlite3

from ohtv.db.models import Conversation


class ConversationStore:
    """Data access for conversations."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, conversation: Conversation) -> None:
        """Insert or update a conversation."""
        self.conn.execute(
            "INSERT OR REPLACE INTO conversations (id, location) VALUES (?, ?)",
            (conversation.id, conversation.location),
        )
    
    def get(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        cursor = self.conn.execute(
            "SELECT id, location FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row:
            return Conversation(id=row["id"], location=row["location"])
        return None
    
    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return cursor.rowcount > 0
