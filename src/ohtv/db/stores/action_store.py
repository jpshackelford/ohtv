"""Data store for conversation actions."""

import json
import sqlite3
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction


class ActionStore:
    """Data access for conversation actions."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def insert(self, action: ConversationAction) -> int:
        """Insert a new action and return its ID."""
        metadata_json = json.dumps(action.metadata) if action.metadata else None
        cursor = self.conn.execute(
            """
            INSERT INTO actions (conversation_id, action_type, target, metadata, event_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                action.conversation_id,
                action.action_type.value,
                action.target,
                metadata_json,
                action.event_id,
            ),
        )
        return cursor.lastrowid
    
    def insert_many(self, actions: Sequence[ConversationAction]) -> int:
        """Insert multiple actions. Returns count of inserted rows."""
        if not actions:
            return 0
        
        rows = [
            (
                a.conversation_id,
                a.action_type.value,
                a.target,
                json.dumps(a.metadata) if a.metadata else None,
                a.event_id,
            )
            for a in actions
        ]
        self.conn.executemany(
            """
            INSERT INTO actions (conversation_id, action_type, target, metadata, event_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)
    
    def get_by_conversation(
        self,
        conversation_id: str,
        action_type: ActionType | None = None,
    ) -> list[ConversationAction]:
        """Get all actions for a conversation, optionally filtered by type."""
        if action_type:
            cursor = self.conn.execute(
                """
                SELECT id, conversation_id, action_type, target, metadata, event_id
                FROM actions
                WHERE conversation_id = ? AND action_type = ?
                ORDER BY id
                """,
                (conversation_id, action_type.value),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT id, conversation_id, action_type, target, metadata, event_id
                FROM actions
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            )
        return [self._row_to_action(row) for row in cursor.fetchall()]
    
    def get_by_type(
        self,
        action_type: ActionType,
        limit: int = 100,
    ) -> list[ConversationAction]:
        """Get actions of a specific type across all conversations."""
        cursor = self.conn.execute(
            """
            SELECT id, conversation_id, action_type, target, metadata, event_id
            FROM actions
            WHERE action_type = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (action_type.value, limit),
        )
        return [self._row_to_action(row) for row in cursor.fetchall()]
    
    def count_by_conversation(self, conversation_id: str) -> dict[str, int]:
        """Count actions by type for a conversation."""
        cursor = self.conn.execute(
            """
            SELECT action_type, COUNT(*) as count
            FROM actions
            WHERE conversation_id = ?
            GROUP BY action_type
            """,
            (conversation_id,),
        )
        return {row["action_type"]: row["count"] for row in cursor.fetchall()}
    
    def count_by_type(self) -> dict[str, int]:
        """Count all actions grouped by type."""
        cursor = self.conn.execute(
            """
            SELECT action_type, COUNT(*) as count
            FROM actions
            GROUP BY action_type
            ORDER BY count DESC
            """
        )
        return {row["action_type"]: row["count"] for row in cursor.fetchall()}
    
    def delete_for_conversation(self, conversation_id: str) -> int:
        """Delete all actions for a conversation. Returns count deleted."""
        cursor = self.conn.execute(
            "DELETE FROM actions WHERE conversation_id = ?",
            (conversation_id,),
        )
        return cursor.rowcount
    
    def _row_to_action(self, row: sqlite3.Row) -> ConversationAction:
        """Convert a database row to a ConversationAction."""
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return ConversationAction(
            id=row["id"],
            conversation_id=row["conversation_id"],
            action_type=ActionType(row["action_type"]),
            target=row["target"],
            metadata=metadata,
            event_id=row["event_id"],
        )
