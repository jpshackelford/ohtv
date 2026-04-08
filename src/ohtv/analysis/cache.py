"""Reusable caching infrastructure for LLM-based analysis.

Provides a base class and utilities for caching analysis results with
automatic invalidation when conversation content changes.

Cache invalidation strategy:
1. Quick check: Compare event count (fast, catches trajectory growth)
2. Full check: Compare content hash (catches any content changes)
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TypeVar

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


def load_cached_analysis(
    cache_file: Path,
    model_class: type[T],
    events: list[dict],
    content_hash: str,
) -> T | None:
    """Load and validate a cached analysis.

    Args:
        cache_file: Path to the cache JSON file.
        model_class: Pydantic model class to parse the cache into.
        events: Current events list (used for event count validation).
        content_hash: Current content hash to validate against.

    Returns:
        Validated analysis if cache is valid, None otherwise.

    Cache is invalidated if:
    - Cache file doesn't exist
    - Event count has changed (quick check)
    - Content hash has changed (full check)
    """
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
        analysis = model_class.model_validate(data)

        # Quick check: event count
        cached_event_count = getattr(analysis, "event_count", None)
        current_event_count = len(events)
        if cached_event_count is not None and cached_event_count != current_event_count:
            log.debug(
                "Cache invalidated: event count changed (%d -> %d)",
                cached_event_count,
                current_event_count,
            )
            return None

        # Full check: content hash
        if analysis.content_hash != content_hash:
            log.debug("Cache invalidated: content hash mismatch")
            return None

        return analysis

    except (json.JSONDecodeError, OSError, ValueError) as e:
        log.warning("Failed to load cached analysis: %s", e)
        return None


def save_cached_analysis(cache_file: Path, analysis: CachedAnalysis) -> None:
    """Save analysis to cache file."""
    cache_file.write_text(analysis.model_dump_json(indent=2))


class AnalysisCacheManager:
    """Manages caching for a specific analysis type.

    Handles event loading, hash computation, cache validation, and storage.
    Subclasses or users provide the content extraction logic.
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
            **validation_kwargs: Additional validation criteria (e.g., context_level).
                Each kwarg is compared against the cached analysis attribute.

        Returns:
            Validated analysis or None if cache is invalid.
        """
        cache_file = self.get_cache_file(conv_dir)

        analysis = load_cached_analysis(
            cache_file, self.model_class, events, content_hash
        )
        if analysis is None:
            return None

        # Check additional validation criteria
        for key, expected_value in validation_kwargs.items():
            cached_value = getattr(analysis, key, None)
            if cached_value != expected_value:
                log.debug(
                    "Cache invalidated: %s changed (%s -> %s)",
                    key,
                    cached_value,
                    expected_value,
                )
                return None

        return analysis

    def save(self, conv_dir: Path, analysis: T) -> None:
        """Save analysis to cache."""
        cache_file = self.get_cache_file(conv_dir)
        save_cached_analysis(cache_file, analysis)
        log.debug("Analysis cached to %s", cache_file)
