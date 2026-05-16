"""Data store for analysis cache metadata.

This store tracks which conversations have cached LLM analyses,
enabling fast O(1) cache status checks via database query instead
of O(N) file reads.

The actual analysis content remains in JSON files on disk.
This table only stores metadata for fast lookup.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AnalysisCacheEntry:
    """A cached analysis entry."""
    conversation_id: str
    cache_key: str
    event_count: int
    content_hash: str
    analyzed_at: datetime


@dataclass
class AnalysisSkipEntry:
    """A skipped analysis entry."""
    conversation_id: str
    event_count: int
    reason: str
    skipped_at: datetime
    context_level: str = "minimal"  # The context level at which skip occurred


# Context levels ordered from lowest to highest content inclusion
CONTEXT_LEVELS = ["minimal", "default", "full"]


def context_level_index(level: str) -> int:
    """Get the numeric index of a context level (0=minimal, 1=default, 2=full)."""
    try:
        return CONTEXT_LEVELS.index(level)
    except ValueError:
        # Unknown level treated as minimal for safety
        return 0


@dataclass
class CacheStatus:
    """Cache status for a conversation.
    
    Attributes:
        conversation_id: The conversation ID
        current_event_count: Current event count in conversations table
        cached_event_count: Event count when analysis was cached (None if not cached)
        cache_key: The cache key if cached
        is_skipped: Whether this conversation is marked as skipped
        skip_reason: Reason for skip (if skipped)
        skip_event_count: Event count when skip marker was set (None if not skipped)
        skip_context_level: Context level at which skip occurred (if skipped)
    """
    conversation_id: str
    current_event_count: int
    cached_event_count: int | None = None
    cache_key: str | None = None
    is_skipped: bool = False
    skip_reason: str | None = None
    skip_event_count: int | None = None
    skip_context_level: str | None = None
    
    @property
    def needs_analysis(self) -> bool:
        """True if this conversation needs (re)analysis.
        
        Note: This is a legacy property that doesn't consider context level.
        For context-aware checks, use needs_analysis_for_context().
        """
        # Skipped and event count unchanged = don't retry
        if self.is_skipped and self.skip_event_count == self.current_event_count:
            return False
        # Cached and event count unchanged = cache hit
        if self.cached_event_count is not None and self.cached_event_count == self.current_event_count:
            return False
        # Otherwise needs analysis
        return True
    
    def needs_analysis_for_context(self, requested_context: str) -> bool:
        """True if this conversation needs (re)analysis at the requested context level.
        
        This is context-aware: a skip at 'minimal' allows retry at 'full'.
        
        Args:
            requested_context: The context level being requested (minimal, default, full)
        
        Returns:
            True if analysis should be attempted, False if cached/skipped result is valid
        """
        # Cached and event count unchanged = cache hit (cache_key already includes context)
        if self.cached_event_count is not None and self.cached_event_count == self.current_event_count:
            return False
        
        # Check skip with context awareness
        if self.is_skipped and self.skip_event_count == self.current_event_count:
            # If skip_context_level is None or matches/exceeds requested, skip is valid
            skip_context = self.skip_context_level or "minimal"
            if context_level_index(requested_context) <= context_level_index(skip_context):
                return False
            # Higher context level requested than skip - allow retry
        
        return True


class AnalysisCacheStore:
    """Data access for analysis cache metadata."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert_cache(self, entry: AnalysisCacheEntry) -> None:
        """Insert or update a cache entry."""
        analyzed_at_str = entry.analyzed_at.isoformat()
        
        # Normalize conversation ID (remove dashes) to match embeddings table
        normalized_id = entry.conversation_id.replace("-", "")
        
        self.conn.execute(
            """
            INSERT INTO analysis_cache (conversation_id, cache_key, event_count, content_hash, analyzed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, cache_key) DO UPDATE SET
                event_count = excluded.event_count,
                content_hash = excluded.content_hash,
                analyzed_at = excluded.analyzed_at
            """,
            (
                normalized_id,
                entry.cache_key,
                entry.event_count,
                entry.content_hash,
                analyzed_at_str,
            ),
        )
        
        # Clear any skip marker when we successfully cache
        self.conn.execute(
            "DELETE FROM analysis_skips WHERE conversation_id = ?",
            (normalized_id,),
        )
    
    def upsert_skip(self, entry: AnalysisSkipEntry) -> None:
        """Insert or update a skip entry.
        
        Note: If a skip already exists at a HIGHER context level, we don't
        update it. A skip at 'full' encompasses all lower levels.
        """
        skipped_at_str = entry.skipped_at.isoformat()
        
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = entry.conversation_id.replace("-", "")
        
        # Check if there's an existing skip at a higher context level
        cursor = self.conn.execute(
            "SELECT context_level FROM analysis_skips WHERE conversation_id = ?",
            (normalized_id,),
        )
        row = cursor.fetchone()
        if row:
            existing_context = row[0] if row[0] else "minimal"
            new_context = entry.context_level or "minimal"
            # Don't downgrade: if existing skip is at higher context, keep it
            if context_level_index(existing_context) > context_level_index(new_context):
                return
        
        self.conn.execute(
            """
            INSERT INTO analysis_skips (conversation_id, event_count, reason, skipped_at, context_level)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                event_count = excluded.event_count,
                reason = excluded.reason,
                skipped_at = excluded.skipped_at,
                context_level = excluded.context_level
            """,
            (
                normalized_id,
                entry.event_count,
                entry.reason,
                skipped_at_str,
                entry.context_level,
            ),
        )
    
    def get_cache_status_batch(
        self,
        conversation_ids: list[str],
        cache_key: str,
    ) -> dict[str, CacheStatus]:
        """Get cache status for multiple conversations in one query.
        
        Args:
            conversation_ids: List of conversation IDs to check
            cache_key: The cache key to check (e.g., "assess=False,context_level=minimal,detail_level=brief")
        
        Returns:
            Dict mapping conversation_id to CacheStatus
        """
        if not conversation_ids:
            return {}
        
        # Build placeholders for IN clause
        placeholders = ",".join("?" * len(conversation_ids))
        
        # Query joins conversations with cache and skips tables
        query = f"""
            SELECT 
                c.id as conversation_id,
                c.event_count as current_event_count,
                ac.event_count as cached_event_count,
                ac.cache_key,
                s.event_count as skip_event_count,
                s.reason as skip_reason,
                s.context_level as skip_context_level
            FROM conversations c
            LEFT JOIN analysis_cache ac ON c.id = ac.conversation_id AND ac.cache_key = ?
            LEFT JOIN analysis_skips s ON c.id = s.conversation_id
            WHERE c.id IN ({placeholders})
        """
        
        cursor = self.conn.execute(query, [cache_key] + conversation_ids)
        
        results = {}
        for row in cursor.fetchall():
            conv_id = row["conversation_id"]
            current_count = row["current_event_count"] or 0
            cached_count = row["cached_event_count"]
            skip_count = row["skip_event_count"]
            skip_reason = row["skip_reason"]
            skip_context = row["skip_context_level"]
            
            # is_skipped indicates a skip marker exists (validity checked in needs_analysis)
            is_skipped = skip_count is not None
            
            results[conv_id] = CacheStatus(
                conversation_id=conv_id,
                current_event_count=current_count,
                cached_event_count=cached_count,
                cache_key=row["cache_key"],
                is_skipped=is_skipped,
                skip_reason=skip_reason if is_skipped else None,
                skip_event_count=skip_count,
                skip_context_level=skip_context if is_skipped else None,
            )
        
        return results
    
    def get_uncached_conversation_ids(
        self,
        conversation_ids: list[str],
        cache_key: str,
    ) -> list[str]:
        """Get IDs of conversations that need analysis.
        
        This is a convenience method that filters to only conversations
        where needs_analysis is True.
        
        Args:
            conversation_ids: List of conversation IDs to check
            cache_key: The cache key to check
        
        Returns:
            List of conversation IDs that need analysis
        """
        status_map = self.get_cache_status_batch(conversation_ids, cache_key)
        return [
            conv_id for conv_id, status in status_map.items()
            if status.needs_analysis
        ]
    
    def count_cached(self, cache_key: str | None = None) -> int:
        """Count cached analyses, optionally filtered by cache key."""
        if cache_key:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM analysis_cache WHERE cache_key = ?",
                (cache_key,),
            )
        else:
            cursor = self.conn.execute("SELECT COUNT(*) FROM analysis_cache")
        return cursor.fetchone()[0]
    
    def count_by_cache_key(self) -> dict[str, int]:
        """Count cached analyses grouped by cache key."""
        cursor = self.conn.execute(
            "SELECT cache_key, COUNT(*) FROM analysis_cache GROUP BY cache_key ORDER BY cache_key"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def count_conversations_cached(self) -> int:
        """Count unique conversations with any cached analysis."""
        cursor = self.conn.execute(
            "SELECT COUNT(DISTINCT conversation_id) FROM analysis_cache"
        )
        return cursor.fetchone()[0]
    
    def count_skipped(self) -> int:
        """Count skipped conversations."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM analysis_skips")
        return cursor.fetchone()[0]
    
    def delete_for_conversation(self, conversation_id: str) -> None:
        """Delete all cache and skip entries for a conversation."""
        # Normalize conversation ID (remove dashes) for consistency
        normalized_id = conversation_id.replace("-", "")
        
        self.conn.execute(
            "DELETE FROM analysis_cache WHERE conversation_id = ?",
            (normalized_id,),
        )
        self.conn.execute(
            "DELETE FROM analysis_skips WHERE conversation_id = ?",
            (normalized_id,),
        )
