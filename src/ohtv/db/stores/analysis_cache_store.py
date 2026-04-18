"""Data store for analysis cache metadata.

This store tracks which conversations have cached LLM analyses,
enabling fast O(1) cache status checks via database query instead
of O(N) file reads.

The actual analysis content remains in JSON files on disk.
This table only stores metadata for fast lookup.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


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
    """
    conversation_id: str
    current_event_count: int
    cached_event_count: int | None = None
    cache_key: str | None = None
    is_skipped: bool = False
    skip_reason: str | None = None
    skip_event_count: int | None = None
    
    @property
    def needs_analysis(self) -> bool:
        """True if this conversation needs (re)analysis."""
        # Skipped and event count unchanged = don't retry
        if self.is_skipped and self.skip_event_count == self.current_event_count:
            return False
        # Cached and event count unchanged = cache hit
        if self.cached_event_count is not None and self.cached_event_count == self.current_event_count:
            return False
        # Otherwise needs analysis
        return True


class AnalysisCacheStore:
    """Data access for analysis cache metadata."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert_cache(self, entry: AnalysisCacheEntry) -> None:
        """Insert or update a cache entry."""
        analyzed_at_str = entry.analyzed_at.isoformat()
        
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
                entry.conversation_id,
                entry.cache_key,
                entry.event_count,
                entry.content_hash,
                analyzed_at_str,
            ),
        )
        
        # Clear any skip marker when we successfully cache
        self.conn.execute(
            "DELETE FROM analysis_skips WHERE conversation_id = ?",
            (entry.conversation_id,),
        )
    
    def upsert_skip(self, entry: AnalysisSkipEntry) -> None:
        """Insert or update a skip entry."""
        skipped_at_str = entry.skipped_at.isoformat()
        
        self.conn.execute(
            """
            INSERT INTO analysis_skips (conversation_id, event_count, reason, skipped_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                event_count = excluded.event_count,
                reason = excluded.reason,
                skipped_at = excluded.skipped_at
            """,
            (
                entry.conversation_id,
                entry.event_count,
                entry.reason,
                skipped_at_str,
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
                s.reason as skip_reason
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
    
    def count_skipped(self) -> int:
        """Count skipped conversations."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM analysis_skips")
        return cursor.fetchone()[0]
    
    def delete_for_conversation(self, conversation_id: str) -> None:
        """Delete all cache and skip entries for a conversation."""
        self.conn.execute(
            "DELETE FROM analysis_cache WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.conn.execute(
            "DELETE FROM analysis_skips WHERE conversation_id = ?",
            (conversation_id,),
        )
