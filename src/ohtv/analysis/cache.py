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

Cache location:
- New location: ~/.ohtv/cache/analysis/<conversation_id>/objective_analysis.json
- Legacy location: <conv_dir>/objective_analysis.json (in conversation directory)
- The migrate_cache() function moves files from legacy to new location
"""

import filecmp
import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ohtv.config import get_analysis_cache_dir

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


def _get_cache_file_path(conv_dir: Path) -> Path:
    """Get the cache file path for a conversation.

    Uses the new location (~/.ohtv/cache/analysis/<conv_id>/objective_analysis.json).
    """
    conv_id = conv_dir.name
    return get_analysis_cache_dir() / conv_id / "objective_analysis.json"


def _get_legacy_cache_file_path(conv_dir: Path) -> Path:
    """Get the legacy cache file path (inside conversation directory)."""
    return conv_dir / "objective_analysis.json"


def _find_cache_file(conv_dir: Path, filename: str = "objective_analysis.json") -> Path | None:
    """Find existing cache file, checking new location first then legacy.

    Args:
        conv_dir: Path to conversation directory
        filename: Cache filename to look for

    Returns:
        Path to existing cache file, or None if no cache exists.
        Prefers new location (~/.ohtv/cache/) over legacy (conversation dir).
    """
    # Try new location first
    conv_id = conv_dir.name
    new_file = get_analysis_cache_dir() / conv_id / filename
    if new_file.exists():
        return new_file

    # Fall back to legacy location
    legacy_file = conv_dir / filename
    if legacy_file.exists():
        return legacy_file

    return None


def has_legacy_cache_files(conv_dirs: list[Path]) -> list[Path]:
    """Check if any conversation directories have legacy cache files.

    Args:
        conv_dirs: List of conversation directories to check

    Returns:
        List of conversation directories that have legacy cache files
    """
    legacy_dirs = []
    for conv_dir in conv_dirs:
        legacy_file = _get_legacy_cache_file_path(conv_dir)
        if legacy_file.exists():
            legacy_dirs.append(conv_dir)
    return legacy_dirs


def load_analysis(conv_dir: Path) -> dict | None:
    """Load cached analysis from a conversation.

    Checks the new location first, then falls back to legacy location.

    Args:
        conv_dir: Path to conversation directory

    Returns:
        Analysis dict with keys like 'goal', 'primary_outcomes', etc.
        Returns None if no cache exists or no analysis found.
    """
    cache_file = _find_cache_file(conv_dir)
    if cache_file is None:
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


def load_all_analyses(conv_dir: Path) -> dict[str, dict]:
    """Load all cached analyses from a conversation.

    Checks the new location first, then falls back to legacy location.

    Args:
        conv_dir: Path to conversation directory

    Returns:
        Dict mapping cache_key to analysis dict.
        Returns empty dict if no cache exists.
    """
    cache_file = _find_cache_file(conv_dir)
    if cache_file is None:
        return {}

    try:
        data = json.loads(cache_file.read_text())
        return data.get("analyses", {})
    except (json.JSONDecodeError, OSError):
        return {}


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
        """Get the cache file path for a conversation.

        Uses the new location (~/.ohtv/cache/analysis/<conv_id>/<filename>).
        """
        conv_id = conv_dir.name
        return get_analysis_cache_dir() / conv_id / self.cache_filename

    def get_legacy_cache_file(self, conv_dir: Path) -> Path:
        """Get the legacy cache file path (inside conversation directory)."""
        return conv_dir / self.cache_filename

    def has_legacy_cache(self, conv_dir: Path) -> bool:
        """Check if a legacy cache file exists for a conversation."""
        return self.get_legacy_cache_file(conv_dir).exists()

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
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, indent=2, default=str))

    def _find_cache_data(self, conv_dir: Path) -> dict | None:
        """Find and load cache data, checking new location first then legacy.

        Args:
            conv_dir: Conversation directory

        Returns:
            Cache data dict, or None if no valid cache exists.
        """
        # Try new location first
        cache_data = self._load_cache_data(self.get_cache_file(conv_dir))
        if cache_data is not None:
            return cache_data

        # Fall back to legacy location
        return self._load_cache_data(self.get_legacy_cache_file(conv_dir))

    def load_cached(
        self,
        conv_dir: Path,
        events: list[dict],
        content_hash: str,
        prompt_hash: str | None = None,
        **validation_kwargs,
    ) -> T | None:
        """Load cached analysis if valid.

        Checks the new location first, then falls back to legacy location.

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
        cache_data = self._find_cache_data(conv_dir)
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
            cache_key: The cache key identifying this analysis variant. Should match
                the format used in analysis_cache table, e.g.,
                'assess=False,context_level=minimal,detail_level=brief'.
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

        Checks the new location first, then falls back to legacy location.

        Args:
            conv_dir: Conversation directory
            event_count: Current event count (for invalidation check)

        Returns:
            Skip reason if skipped and still valid, None otherwise.
        """
        cache_data = self._find_cache_data(conv_dir)
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


class MigrationError(Exception):
    """Raised when cache file migration fails verification."""

    pass


def migrate_cache_file(
    conv_dir: Path,
    cache_filename: str = "objective_analysis.json",
    verify: bool = True,
) -> bool:
    """Migrate a single cache file from legacy to new location.

    Copies the cache file from the conversation directory to the new
    centralized cache location. Does not delete the original file
    (to avoid data loss during migration).

    Args:
        conv_dir: Path to conversation directory
        cache_filename: Name of the cache file
        verify: If True, verify the copy succeeded before returning

    Returns:
        True if migration was performed, False if no legacy file exists

    Raises:
        MigrationError: If verification fails (copy incomplete or unreadable)
        OSError: If there's insufficient disk space or permission issues
    """
    legacy_file = conv_dir / cache_filename
    if not legacy_file.exists():
        return False

    # Get new location
    conv_id = conv_dir.name
    new_file = get_analysis_cache_dir() / conv_id / cache_filename

    # Check disk space before copying (rough estimate: need at least 2x file size)
    source_size = legacy_file.stat().st_size
    try:
        target_dir = new_file.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        free_space = shutil.disk_usage(target_dir).free
        if free_space < source_size * 2:
            raise MigrationError(
                f"Insufficient disk space: {free_space} bytes free, "
                f"need at least {source_size * 2} bytes"
            )
    except (OSError, AttributeError):
        # disk_usage might not be available on all platforms
        pass

    # Copy file (don't delete original for safety)
    shutil.copy2(legacy_file, new_file)

    if verify:
        # Verify the copy succeeded
        if not new_file.exists():
            raise MigrationError(f"Target file not created: {new_file}")

        # Verify file contents match
        if not filecmp.cmp(legacy_file, new_file, shallow=False):
            # Clean up failed copy
            try:
                new_file.unlink()
            except OSError:
                pass
            raise MigrationError(
                f"File content mismatch after copy: {legacy_file} -> {new_file}"
            )

        # Verify the new file is readable and valid JSON
        try:
            data = json.loads(new_file.read_text())
            if "analyses" not in data and "skipped" not in data:
                log.warning("Migrated file has unexpected format: %s", new_file)
        except (json.JSONDecodeError, OSError) as e:
            # Clean up corrupted file
            try:
                new_file.unlink()
            except OSError:
                pass
            raise MigrationError(f"Migrated file is not readable: {e}")

    log.debug("Migrated cache file: %s -> %s", legacy_file, new_file)
    return True


def delete_legacy_cache_file(
    conv_dir: Path,
    cache_filename: str = "objective_analysis.json",
) -> bool:
    """Delete a legacy cache file after migration.

    Only call this after verifying the cache has been migrated successfully.

    Args:
        conv_dir: Path to conversation directory
        cache_filename: Name of the cache file

    Returns:
        True if file was deleted, False if it didn't exist
    """
    legacy_file = conv_dir / cache_filename
    if not legacy_file.exists():
        return False

    legacy_file.unlink()
    log.debug("Deleted legacy cache file: %s", legacy_file)
    return True


def count_legacy_cache_files(conv_dirs: list[Path]) -> int:
    """Count how many conversation directories have legacy cache files.

    Args:
        conv_dirs: List of conversation directories to check

    Returns:
        Number of directories with legacy cache files
    """
    count = 0
    for conv_dir in conv_dirs:
        if (conv_dir / "objective_analysis.json").exists():
            count += 1
    return count
