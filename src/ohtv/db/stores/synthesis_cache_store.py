"""Data store for conversation synthesis result caching.

This store manages cached LLM synthesis results (titles, objectives, worklog
summaries) with automatic invalidation based on conversation updates.

Issue #191. Unlike the file-based ``analysis_cache`` which stores multiple
analysis variants per conversation, this table stores a single "best"
synthesis result per conversation for fast retrieval in display/reporting.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SynthesisCacheEntry:
    """A cached synthesis entry."""
    conversation_id: str
    conversation_updated_at: str
    synthesized_title: str | None = None
    synthesized_objective: str | None = None
    worklog_purpose: str | None = None
    synthesis_model: str | None = None
    synthesis_version: str | None = None
    synthesized_at: datetime | None = None
    tokens_used: int | None = None


class SynthesisCacheStore:
    """Data access for synthesis cache."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def get_cached_title(
        self,
        conv_id: str,
        conv_updated_at: str,
        model: str,
        version: str
    ) -> str | None:
        """Get cached title if valid.
        
        Args:
            conv_id: Conversation ID
            conv_updated_at: Conversation updated_at timestamp
            model: LLM model name
            version: Synthesis schema version
        
        Returns:
            Cached title if cache is valid, None otherwise
        """
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conv_id.replace("-", "")
        
        cursor = self.conn.execute("""
            SELECT synthesized_title, conversation_updated_at,
                   synthesis_model, synthesis_version
            FROM conversation_synthesis
            WHERE conversation_id = ?
        """, (normalized_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        cached_title, cached_updated, cached_model, cached_version = row
        
        # Cache hit only if all validation fields match
        if (cached_updated == conv_updated_at and
            cached_model == model and
            cached_version == version and
            cached_title is not None):
            return cached_title
        
        return None  # Cache invalid
    
    def upsert_title(
        self,
        conv_id: str,
        conv_updated_at: str,
        title: str,
        model: str,
        version: str,
        tokens_used: int | None = None
    ) -> None:
        """Store or update cached title.
        
        Args:
            conv_id: Conversation ID
            conv_updated_at: Conversation updated_at timestamp
            title: Synthesized title
            model: LLM model name
            version: Synthesis schema version
            tokens_used: Estimated token count (optional)
        """
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conv_id.replace("-", "")
        
        self.conn.execute("""
            INSERT INTO conversation_synthesis
            (conversation_id, conversation_updated_at, synthesized_title,
             synthesis_model, synthesis_version, synthesized_at, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                conversation_updated_at = excluded.conversation_updated_at,
                synthesized_title = excluded.synthesized_title,
                synthesis_model = excluded.synthesis_model,
                synthesis_version = excluded.synthesis_version,
                synthesized_at = excluded.synthesized_at,
                tokens_used = COALESCE(excluded.tokens_used, conversation_synthesis.tokens_used)
        """, (normalized_id, conv_updated_at, title, model, version,
              datetime.now().isoformat(), tokens_used))
    
    def get_cached_objective(
        self,
        conv_id: str,
        conv_updated_at: str,
        model: str,
        version: str
    ) -> str | None:
        """Get cached objective if valid.
        
        Args:
            conv_id: Conversation ID
            conv_updated_at: Conversation updated_at timestamp
            model: LLM model name
            version: Synthesis schema version
        
        Returns:
            Cached objective if cache is valid, None otherwise
        """
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conv_id.replace("-", "")
        
        cursor = self.conn.execute("""
            SELECT synthesized_objective, conversation_updated_at,
                   synthesis_model, synthesis_version
            FROM conversation_synthesis
            WHERE conversation_id = ?
        """, (normalized_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        cached_obj, cached_updated, cached_model, cached_version = row
        
        # Cache hit only if all validation fields match
        if (cached_updated == conv_updated_at and
            cached_model == model and
            cached_version == version and
            cached_obj is not None):
            return cached_obj
        
        return None  # Cache invalid
    
    def upsert_objective(
        self,
        conv_id: str,
        conv_updated_at: str,
        objective: str,
        model: str,
        version: str,
        tokens_used: int | None = None
    ) -> None:
        """Store or update cached objective.
        
        Args:
            conv_id: Conversation ID
            conv_updated_at: Conversation updated_at timestamp
            objective: Synthesized objective
            model: LLM model name
            version: Synthesis schema version
            tokens_used: Estimated token count (optional)
        """
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conv_id.replace("-", "")
        
        self.conn.execute("""
            INSERT INTO conversation_synthesis
            (conversation_id, conversation_updated_at, synthesized_objective,
             synthesis_model, synthesis_version, synthesized_at, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                conversation_updated_at = excluded.conversation_updated_at,
                synthesized_objective = excluded.synthesized_objective,
                synthesis_model = excluded.synthesis_model,
                synthesis_version = excluded.synthesis_version,
                synthesized_at = excluded.synthesized_at,
                tokens_used = COALESCE(excluded.tokens_used, conversation_synthesis.tokens_used)
        """, (normalized_id, conv_updated_at, objective, model, version,
              datetime.now().isoformat(), tokens_used))
    
    def count_cached_titles(self) -> int:
        """Count conversations with cached titles."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversation_synthesis WHERE synthesized_title IS NOT NULL"
        )
        return cursor.fetchone()[0]
    
    def count_cached_objectives(self) -> int:
        """Count conversations with cached objectives."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM conversation_synthesis WHERE synthesized_objective IS NOT NULL"
        )
        return cursor.fetchone()[0]
    
    def count_stale_entries(self) -> int:
        """Count stale cache entries (conversation updated after synthesis).
        
        A stale entry is one where the conversation's current updated_at
        differs from the cached updated_at, indicating the conversation
        has been modified since synthesis.
        """
        cursor = self.conn.execute("""
            SELECT COUNT(*)
            FROM conversation_synthesis cs
            JOIN conversations c ON cs.conversation_id = c.id
            WHERE cs.conversation_updated_at != COALESCE(c.updated_at, '')
        """)
        return cursor.fetchone()[0]
    
    def get_total_tokens_saved(self) -> int:
        """Get estimated total tokens saved by cache hits.
        
        This is a rough estimate based on stored token counts.
        """
        cursor = self.conn.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) FROM conversation_synthesis"
        )
        return cursor.fetchone()[0]
    
    def clear_all(self) -> int:
        """Clear all synthesis cache entries.
        
        Returns:
            Number of entries deleted
        """
        cursor = self.conn.execute("DELETE FROM conversation_synthesis")
        return cursor.rowcount
    
    def clear_stale(self) -> int:
        """Clear only stale cache entries.
        
        Returns:
            Number of entries deleted
        """
        cursor = self.conn.execute("""
            DELETE FROM conversation_synthesis
            WHERE conversation_id IN (
                SELECT cs.conversation_id
                FROM conversation_synthesis cs
                JOIN conversations c ON cs.conversation_id = c.id
                WHERE cs.conversation_updated_at != COALESCE(c.updated_at, '')
            )
        """)
        return cursor.rowcount
    
    def delete_for_conversation(self, conversation_id: str) -> None:
        """Delete synthesis cache entry for a conversation.
        
        Args:
            conversation_id: Conversation ID
        """
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conversation_id.replace("-", "")
        
        self.conn.execute(
            "DELETE FROM conversation_synthesis WHERE conversation_id = ?",
            (normalized_id,)
        )
