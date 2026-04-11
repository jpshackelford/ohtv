"""Data store for processing stages."""

import sqlite3
from datetime import datetime, timezone

from ohtv.db.models.stage import ProcessingStage


class StageStore:
    """Data access for conversation processing stages."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def mark_complete(
        self,
        conversation_id: str,
        stage: str,
        event_count: int,
        completed_at: datetime | None = None,
    ) -> None:
        """Mark a processing stage as complete for a conversation.
        
        Args:
            conversation_id: The conversation ID
            stage: Name of the stage (e.g., 'refs', 'objectives')
            event_count: Current event count (checkpoint for future runs)
            completed_at: Completion timestamp (defaults to now)
        """
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        
        self.conn.execute(
            """
            INSERT INTO conversation_stages (conversation_id, stage, completed_at, event_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id, stage) DO UPDATE SET
                completed_at = excluded.completed_at,
                event_count = excluded.event_count
            """,
            (conversation_id, stage, completed_at.isoformat(), event_count),
        )
    
    def get(self, conversation_id: str, stage: str) -> ProcessingStage | None:
        """Get the processing stage record for a conversation."""
        cursor = self.conn.execute(
            "SELECT conversation_id, stage, completed_at, event_count FROM conversation_stages WHERE conversation_id = ? AND stage = ?",
            (conversation_id, stage),
        )
        row = cursor.fetchone()
        if row:
            return ProcessingStage(
                conversation_id=row["conversation_id"],
                stage=row["stage"],
                completed_at=datetime.fromisoformat(row["completed_at"]),
                event_count=row["event_count"],
            )
        return None
    
    def get_stages_for_conversation(self, conversation_id: str) -> list[ProcessingStage]:
        """Get all completed stages for a conversation."""
        cursor = self.conn.execute(
            "SELECT conversation_id, stage, completed_at, event_count FROM conversation_stages WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [
            ProcessingStage(
                conversation_id=row["conversation_id"],
                stage=row["stage"],
                completed_at=datetime.fromisoformat(row["completed_at"]),
                event_count=row["event_count"],
            )
            for row in cursor.fetchall()
        ]
    
    def needs_processing(self, conversation_id: str, stage: str, current_event_count: int) -> bool:
        """Check if a conversation needs processing for a given stage.
        
        Returns True if:
        - Stage has never been run for this conversation, OR
        - Stage was run with fewer events than current count
        """
        record = self.get(conversation_id, stage)
        if record is None:
            return True
        return record.event_count < current_event_count
    
    def get_pending_conversations(self, stage: str) -> list[tuple[str, int]]:
        """Get conversations that need processing for a stage.
        
        Returns list of (conversation_id, current_event_count) for conversations
        where the stage has never run or is stale (processed fewer events).
        """
        cursor = self.conn.execute(
            """
            SELECT c.id, c.event_count
            FROM conversations c
            LEFT JOIN conversation_stages cs 
                ON c.id = cs.conversation_id AND cs.stage = ?
            WHERE cs.conversation_id IS NULL
               OR cs.event_count < c.event_count
            """,
            (stage,),
        )
        return [(row["id"], row["event_count"]) for row in cursor.fetchall()]
    
    def clear_stage(self, stage: str, conversation_id: str | None = None) -> int:
        """Clear stage completion records (for --force reprocessing).
        
        Args:
            stage: The stage to clear
            conversation_id: Optional specific conversation (if None, clears all)
            
        Returns:
            Number of records cleared
        """
        if conversation_id:
            cursor = self.conn.execute(
                "DELETE FROM conversation_stages WHERE stage = ? AND conversation_id = ?",
                (stage, conversation_id),
            )
        else:
            cursor = self.conn.execute(
                "DELETE FROM conversation_stages WHERE stage = ?",
                (stage,),
            )
        return cursor.rowcount
    
    def clear_all_stages(self, conversation_id: str | None = None) -> int:
        """Clear all stage records for reprocessing.
        
        Args:
            conversation_id: Optional specific conversation (if None, clears all)
            
        Returns:
            Number of records cleared
        """
        if conversation_id:
            cursor = self.conn.execute(
                "DELETE FROM conversation_stages WHERE conversation_id = ?",
                (conversation_id,),
            )
        else:
            cursor = self.conn.execute("DELETE FROM conversation_stages")
        return cursor.rowcount
