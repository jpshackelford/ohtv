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
from datetime import datetime
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
        **validation_kwargs,
    ) -> T | None:
        """Load cached analysis if valid.

        Args:
            conv_dir: Conversation directory
            events: Current events list
            content_hash: Current content hash
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

    def save(self, conv_dir: Path, analysis: T, **key_kwargs) -> None:
        """Save analysis to cache.

        Args:
            conv_dir: Conversation directory
            analysis: Analysis result to cache
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

        self._save_cache_data(cache_file, cache_data)
        log.debug("Analysis cached to %s (key: %s)", cache_file, cache_key)
