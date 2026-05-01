"""Reusable caching infrastructure for LLM-based analysis.

Provides a base class and utilities for caching analysis results with
automatic invalidation when conversation content changes.

Cache design:
- Multiple analyses with different parameters are stored in a single file
- Each analysis is keyed by its parameter combination (e.g., context_level, detail_level)
- All analyses are invalidated when event count changes (conversation grew)
- Individual analyses track their own content hash for finer invalidation

Cache invalidation strategy:
1. Quick check: Compare event count (fast, catches trajectory growth)
2. Full check: Compare content hash per analysis (catches content changes)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

log = logging.getLogger("ohtv")

T = TypeVar("T", bound="CachedAnalysis")


class CachedAnalysis(BaseModel):
    """Base class for cached analysis results.

    Subclasses should add their analysis-specific fields.
    The cache validation fields are used to detect when the
    underlying conversation has changed.
    """

    conversation_id: str
    analyzed_at: datetime
    model_used: str

    # Cache validation fields
    event_count: int
    content_hash: str
    prompt_hash: str | None = None  # Hash of prompt used (for cache invalidation)


def load_events(conv_dir: Path) -> list[dict]:
    """Load all events from a conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


def load_analysis(conv_dir: Path) -> dict | None:
    """Load cached analysis from a conversation directory.

    Args:
        conv_dir: Path to conversation directory

    Returns:
        Analysis dict with keys like 'goal', 'primary_outcomes', etc.
        Returns None if no cache exists or no analysis found.
    """
    cache_file = conv_dir / "objective_analysis.json"
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
        analyses = data.get("analyses", {})
        if not analyses:
            return None
        # Return first analysis found (they all have the same goal/outcomes)
        return next(iter(analyses.values()))
    except (json.JSONDecodeError, OSError):
        return None


def compute_content_hash(content: str | list | dict) -> str:
    """Compute a hash of content for cache invalidation.

    Args:
        content: String, list, or dict to hash. Non-strings are
            JSON-serialized with sorted keys for consistency.

    Returns:
        16-character hex hash string.
    """
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _make_cache_key(**kwargs: Any) -> str:
    """Create a cache key from keyword arguments.

    Args:
        **kwargs: Parameters that distinguish different analysis types.

    Returns:
        A string key like "context=minimal,detail=brief,assess=False"
    """
    # Sort keys for consistent ordering
    parts = [f"{k}={v}" for k, v in sorted(kwargs.items())]
    return ",".join(parts) if parts else "default"


def make_cache_key(context: str, detail: str, assess: bool) -> str:
    """Create a cache key for analysis parameters.
    
    This is the public API for creating cache keys that match
    those used internally by AnalysisCacheManager.
    
    Args:
        context: Context level (minimal, default, full)
        detail: Detail level (brief, standard, detailed)
        assess: Whether assessment is enabled
    
    Returns:
        A cache key string
    """
    return _make_cache_key(
        assess=assess,
        context_level=context,
        detail_level=detail,
    )


class AnalysisCacheManager:
    """Manages caching for a specific analysis type.

    Stores multiple analyses with different parameters in a single cache file.
    Each analysis is keyed by its parameter combination, allowing different
    analysis modes to coexist without overwriting each other.

    Cache structure:
    {
        "event_count": 42,  # For quick invalidation check
        "analyses": {
            "context=minimal,detail=brief,assess=False": { ... analysis data ... },
            "context=default,detail=standard,assess=True": { ... analysis data ... }
        }
    }
    """

    def __init__(
        self,
        cache_filename: str,
        model_class: type[T],
    ):
        """Initialize cache manager.

        Args:
            cache_filename: Name of the cache file (e.g., "objective_analysis.json")
            model_class: Pydantic model class for the analysis results
        """
        self.cache_filename = cache_filename
        self.model_class = model_class

    def get_cache_file(self, conv_dir: Path) -> Path:
        """Get the cache file path for a conversation."""
        return conv_dir / self.cache_filename

    def _load_cache_data(self, cache_file: Path) -> dict | None:
        """Load raw cache data from file."""
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text())

            # Check for valid format (must have "analyses" key)
            if "analyses" not in data:
                log.debug("Invalid cache format, will be overwritten")
                return None

            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load cache file: %s", e)
            return None

    def _save_cache_data(self, cache_file: Path, data: dict) -> None:
        """Save raw cache data to file."""
        cache_file.write_text(json.dumps(data, indent=2, default=str))

    def load_cached(
        self,
        conv_dir: Path,
        events: list[dict],
        content_hash: str,
        prompt_hash: str | None = None,
        **validation_kwargs,
    ) -> T | None:
        """Load cached analysis if valid.

        Args:
            conv_dir: Conversation directory
            events: Current events list
            content_hash: Current content hash
            prompt_hash: Current prompt hash (if provided, must match cached value)
            **validation_kwargs: Parameters that identify the analysis type
                (e.g., context_level, detail_level, assess). Used both as
                cache key and for validation.

        Returns:
            Validated analysis or None if cache is invalid/missing.
        """
        cache_file = self.get_cache_file(conv_dir)
        cache_data = self._load_cache_data(cache_file)

        if cache_data is None:
            return None

        # Quick check: event count (invalidates ALL cached analyses)
        cached_event_count = cache_data.get("event_count")
        current_event_count = len(events)
        if cached_event_count is not None and cached_event_count != current_event_count:
            log.debug(
                "Cache invalidated: event count changed (%d -> %d)",
                cached_event_count,
                current_event_count,
            )
            return None

        # Look up analysis by parameter key
        cache_key = _make_cache_key(**validation_kwargs)
        analyses = cache_data.get("analyses", {})

        if cache_key not in analyses:
            log.debug("Cache miss: no analysis for key '%s'", cache_key)
            return None

        # Parse the cached analysis
        try:
            analysis = self.model_class.model_validate(analyses[cache_key])
        except (ValueError, TypeError) as e:
            log.warning("Failed to parse cached analysis for key '%s': %s", cache_key, e)
            return None

        # Validate content hash (specific to this analysis's context level)
        if analysis.content_hash != content_hash:
            log.debug("Cache invalidated for key '%s': content hash mismatch", cache_key)
            return None

        # Validate prompt hash (if provided and cached analysis has one)
        if prompt_hash is not None and analysis.prompt_hash is not None:
            if analysis.prompt_hash != prompt_hash:
                log.debug(
                    "Cache invalidated for key '%s': prompt hash mismatch (%s -> %s)",
                    cache_key,
                    analysis.prompt_hash,
                    prompt_hash,
                )
                return None

        # Validate that stored parameters match requested parameters
        for key, expected_value in validation_kwargs.items():
            cached_value = getattr(analysis, key, None)
            if cached_value != expected_value:
                log.debug(
                    "Cache invalidated for key '%s': %s changed (%s -> %s)",
                    cache_key,
                    key,
                    cached_value,
                    expected_value,
                )
                return None

        log.debug("Cache hit for key '%s'", cache_key)
        return analysis

    def save(
        self,
        conv_dir: Path,
        analysis: T,
        update_embeddings: bool = False,
        **key_kwargs,
    ) -> None:
        """Save analysis to cache.

        Args:
            conv_dir: Conversation directory
            analysis: Analysis result to cache
            update_embeddings: Whether to update the analysis embedding in the
                database. This triggers an API call to generate embeddings.
                Default is False to avoid hidden side effects.
            **key_kwargs: Parameters that identify the analysis type.
                If not provided, extracts from analysis object attributes
                matching common parameter names.
        """
        cache_file = self.get_cache_file(conv_dir)

        # Load existing cache data or create new
        cache_data = self._load_cache_data(cache_file) or {}

        # Update event count
        cache_data["event_count"] = analysis.event_count

        # Determine cache key from kwargs or analysis attributes
        if not key_kwargs:
            # Try to extract key parameters from common attribute names
            for attr in ["context_level", "detail_level", "assess"]:
                if hasattr(analysis, attr):
                    key_kwargs[attr] = getattr(analysis, attr)

        cache_key = _make_cache_key(**key_kwargs)

        # Store analysis under its key
        if "analyses" not in cache_data:
            cache_data["analyses"] = {}

        cache_data["analyses"][cache_key] = analysis.model_dump(mode="json")

        # Clear any skip marker since we successfully analyzed
        cache_data.pop("skipped", None)

        self._save_cache_data(cache_file, cache_data)
        log.debug("Analysis cached to %s (key: %s)", cache_file, cache_key)
        
        # Sync to database if available
        self._sync_cache_to_db(conv_dir.name, cache_key, analysis)
        
        # Update analysis embedding only if explicitly requested
        if update_embeddings:
            self._update_analysis_embedding(conv_dir, analysis, cache_key)

    def _sync_cache_to_db(self, conversation_id: str, cache_key: str, analysis: T) -> None:
        """Sync cache entry to database for fast lookup.
        
        This is optional - if database is not available, we just skip.
        The file-based cache is the source of truth.
        """
        try:
            from ohtv.db import get_connection, migrate
            from ohtv.db.stores import AnalysisCacheStore, ConversationStore
            from ohtv.db.stores.analysis_cache_store import AnalysisCacheEntry
            
            with get_connection() as conn:
                migrate(conn)
                cache_store = AnalysisCacheStore(conn)
                entry = AnalysisCacheEntry(
                    conversation_id=conversation_id,
                    cache_key=cache_key,
                    event_count=analysis.event_count,
                    content_hash=analysis.content_hash,
                    analyzed_at=analysis.analyzed_at,
                )
                cache_store.upsert_cache(entry)
                
                # Also sync goal to conversation summary
                analysis_dict = analysis.model_dump() if hasattr(analysis, 'model_dump') else {}
                goal = analysis_dict.get("goal")
                if goal:
                    conv_store = ConversationStore(conn)
                    conv_store.update_summary(conversation_id, goal)
                    log.debug("Updated conversation summary: %s", conversation_id)
                
                conn.commit()
                log.debug("Synced cache to DB: %s (key: %s)", conversation_id, cache_key)
        except Exception as e:
            # DB sync is optional, don't fail if it doesn't work
            log.debug("Failed to sync cache to DB (non-fatal): %s", e)
    
    def _update_analysis_embedding(self, conv_dir: Path, analysis: T, cache_key: str) -> None:
        """Update the analysis embedding after new analysis is cached.
        
        This ensures the embedding store stays in sync with analysis changes.
        Only updates the 'analysis' embedding type, not summary/content.
        
        Args:
            conv_dir: Conversation directory
            analysis: The analysis result
            cache_key: The cache key identifying this analysis variant
        """
        try:
            from ohtv.db import get_connection, migrate
            from ohtv.db.stores import EmbeddingStore
            from ohtv.analysis.embeddings import (
                build_analysis_text, get_embedding, get_embedding_model
            )
            import os
            
            # Only attempt if LLM_API_KEY is configured
            if not os.environ.get("LLM_API_KEY"):
                log.debug("Skipping embedding update - LLM_API_KEY not set")
                return
            
            # Build analysis text
            analysis_dict = analysis.model_dump()
            analysis_text = build_analysis_text(analysis_dict)
            
            if not analysis_text:
                log.debug("No analysis text to embed for %s", conv_dir.name)
                return
            
            # Get embedding
            model = get_embedding_model()
            result = get_embedding(analysis_text, model=model)
            
            # Save to database
            with get_connection() as conn:
                migrate(conn)
                store = EmbeddingStore(conn)
                store.upsert(
                    conversation_id=conv_dir.name,
                    embedding=result.embedding,
                    model=result.model,
                    embed_type="analysis",
                    chunk_index=0,
                    cache_key=cache_key,
                    token_count=result.token_count,
                    source_text=analysis_text,
                )
                conn.commit()
                log.debug("Updated analysis embedding for %s (cache_key: %s)", conv_dir.name, cache_key)
                
        except (ImportError, RuntimeError, OSError) as e:
            # Embedding update is optional, don't fail analysis
            # - ImportError: missing dependencies
            # - RuntimeError: API errors (e.g., LLM call failed)
            # - OSError: I/O errors (database access issues)
            log.debug("Failed to update analysis embedding (non-fatal): %s", e)

    def is_skipped(self, conv_dir: Path, event_count: int) -> str | None:
        """Check if conversation is marked as skipped.

        Args:
            conv_dir: Conversation directory
            event_count: Current event count (for invalidation check)

        Returns:
            Skip reason if skipped and still valid, None otherwise.
        """
        cache_file = self.get_cache_file(conv_dir)
        cache_data = self._load_cache_data(cache_file)

        if cache_data is None:
            return None

        skipped = cache_data.get("skipped")
        if not skipped:
            return None

        # Check if event count changed (conversation grew, should retry)
        cached_event_count = cache_data.get("event_count")
        if cached_event_count != event_count:
            log.debug(
                "Skip marker invalidated: event count changed (%s -> %d)",
                cached_event_count,
                event_count,
            )
            return None

        return skipped.get("reason")

    def mark_skipped(self, conv_dir: Path, event_count: int, reason: str) -> None:
        """Mark a conversation as skipped (cannot be analyzed).

        Args:
            conv_dir: Conversation directory
            event_count: Current event count
            reason: Why the conversation was skipped
        """
        cache_file = self.get_cache_file(conv_dir)
        cache_data = self._load_cache_data(cache_file) or {"analyses": {}}

        cache_data["event_count"] = event_count
        cache_data["skipped"] = {
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
        }

        self._save_cache_data(cache_file, cache_data)
        log.debug("Conversation marked as skipped: %s (reason: %s)", conv_dir.name, reason)
        
        # Sync to database if available
        self._sync_skip_to_db(conv_dir.name, event_count, reason)

    def _sync_skip_to_db(self, conversation_id: str, event_count: int, reason: str) -> None:
        """Sync skip entry to database for fast lookup.
        
        This is optional - if database is not available, we just skip.
        The file-based cache is the source of truth.
        """
        try:
            from ohtv.db import get_connection, migrate
            from ohtv.db.stores import AnalysisCacheStore
            from ohtv.db.stores.analysis_cache_store import AnalysisSkipEntry
            
            with get_connection() as conn:
                migrate(conn)
                store = AnalysisCacheStore(conn)
                entry = AnalysisSkipEntry(
                    conversation_id=conversation_id,
                    event_count=event_count,
                    reason=reason,
                    skipped_at=datetime.now(timezone.utc),
                )
                store.upsert_skip(entry)
                conn.commit()
                log.debug("Synced skip to DB: %s (reason: %s)", conversation_id, reason)
        except Exception as e:
            # DB sync is optional, don't fail if it doesn't work
            log.debug("Failed to sync skip to DB (non-fatal): %s", e)
