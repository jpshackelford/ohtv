"""Tests for context-aware skip caching in AnalysisCacheManager."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from ohtv.analysis.cache import AnalysisCacheManager
from ohtv.analysis.objectives import ObjectiveAnalysis


@pytest.fixture
def cache_dir(tmp_path):
    """Create a temporary cache directory."""
    cache = tmp_path / "cache" / "analysis"
    cache.mkdir(parents=True)
    return cache


@pytest.fixture
def conv_dir(tmp_path):
    """Create a temporary conversation directory."""
    conv = tmp_path / "conversations" / "test_conv_123"
    conv.mkdir(parents=True)
    events_dir = conv / "events"
    events_dir.mkdir()
    return conv


@pytest.fixture
def cache_manager(cache_dir):
    """Create an AnalysisCacheManager with mocked cache dir."""
    with patch("ohtv.analysis.cache.get_analysis_cache_dir", return_value=cache_dir):
        yield AnalysisCacheManager(
            cache_filename="objective_analysis.json",
            model_class=ObjectiveAnalysis,
        )


class TestIsSkippedContextAware:
    """Tests for is_skipped with context level awareness."""

    def test_skip_at_minimal_blocks_minimal(self, cache_manager, conv_dir):
        """Skip at 'minimal' should block requests at 'minimal' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="minimal")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="minimal")
        assert result == "no_content"

    def test_skip_at_minimal_allows_default(self, cache_manager, conv_dir):
        """Skip at 'minimal' should allow retry at 'default' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="minimal")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="outcome")
        assert result is None

    def test_skip_at_minimal_allows_full(self, cache_manager, conv_dir):
        """Skip at 'minimal' should allow retry at 'full' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="minimal")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="observations")
        assert result is None

    def test_skip_at_default_blocks_minimal(self, cache_manager, conv_dir):
        """Skip at 'default' should block requests at 'minimal' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="outcome")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="minimal")
        assert result == "no_content"

    def test_skip_at_default_blocks_default(self, cache_manager, conv_dir):
        """Skip at 'default' should block requests at 'default' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="outcome")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="outcome")
        assert result == "no_content"

    def test_skip_at_default_allows_full(self, cache_manager, conv_dir):
        """Skip at 'default' should allow retry at 'full' level."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="outcome")
        
        result = cache_manager.is_skipped(conv_dir, 5, context_level="observations")
        assert result is None

    def test_skip_at_full_blocks_all(self, cache_manager, conv_dir):
        """Skip at 'full' should block all context levels."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="observations")
        
        assert cache_manager.is_skipped(conv_dir, 5, context_level="minimal") == "no_content"
        assert cache_manager.is_skipped(conv_dir, 5, context_level="outcome") == "no_content"
        assert cache_manager.is_skipped(conv_dir, 5, context_level="observations") == "no_content"

    def test_event_count_change_invalidates_skip(self, cache_manager, conv_dir):
        """Skip should be invalidated if event count changes, regardless of context."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="observations")
        
        # Event count changed (conversation grew)
        result = cache_manager.is_skipped(conv_dir, 10, context_level="minimal")
        assert result is None

    def test_default_context_level_is_minimal(self, cache_manager, conv_dir):
        """Default context level should be 'minimal'."""
        # Mark skipped without explicit context_level
        cache_manager.mark_skipped(conv_dir, 5, "no_content")
        
        # Default is minimal, so should block minimal but allow higher
        assert cache_manager.is_skipped(conv_dir, 5) == "no_content"
        assert cache_manager.is_skipped(conv_dir, 5, context_level="minimal") == "no_content"
        assert cache_manager.is_skipped(conv_dir, 5, context_level="observations") is None


class TestMarkSkippedContextLevel:
    """Tests for mark_skipped with context level."""

    def test_stores_context_level_in_cache(self, cache_manager, conv_dir, cache_dir):
        """Context level should be stored in cache file."""
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="outcome")
        
        cache_file = cache_dir / conv_dir.name / "objective_analysis.json"
        data = json.loads(cache_file.read_text())
        
        assert data["skipped"]["context_level"] == "outcome"

    def test_does_not_downgrade_context_level(self, cache_manager, conv_dir, cache_dir):
        """Mark skipped should not overwrite higher context level with lower."""
        # First mark at 'full'
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="observations")
        
        # Try to mark at 'minimal'
        cache_manager.mark_skipped(conv_dir, 5, "different_reason", context_level="minimal")
        
        # Should still be 'full'
        cache_file = cache_dir / conv_dir.name / "objective_analysis.json"
        data = json.loads(cache_file.read_text())
        
        assert data["skipped"]["context_level"] == "observations"
        assert data["skipped"]["reason"] == "no_content"

    def test_upgrades_context_level(self, cache_manager, conv_dir, cache_dir):
        """Mark skipped at higher context should upgrade existing skip."""
        # First mark at 'minimal'
        cache_manager.mark_skipped(conv_dir, 5, "no_content", context_level="minimal")
        
        # Mark at 'full'
        cache_manager.mark_skipped(conv_dir, 5, "still_no_content", context_level="observations")
        
        # Should now be 'full'
        cache_file = cache_dir / conv_dir.name / "objective_analysis.json"
        data = json.loads(cache_file.read_text())
        
        assert data["skipped"]["context_level"] == "observations"
        assert data["skipped"]["reason"] == "still_no_content"

    def test_event_count_updated_despite_higher_context_skip(self, cache_manager, conv_dir, cache_dir):
        """Event count should be updated even when not downgrading context level.
        
        This prevents infinite retry loops when:
        1. Conversation is skipped at 'full' with event_count=10
        2. Conversation grows to 20 events
        3. Batch run at 'minimal' context fails, calls mark_skipped(20, 'minimal')
        4. Without this fix, the early return would leave event_count=10, causing endless retries
        """
        # Skip at 'full' with event_count=10
        cache_manager.mark_skipped(conv_dir, 10, "no_content", context_level="observations")
        
        # Conversation grows to 20 events, batch run fails at 'minimal'
        cache_manager.mark_skipped(conv_dir, 20, "still_no_content", context_level="minimal")
        
        # Verify event_count was updated (even though context stayed at 'full')
        cache_file = cache_dir / conv_dir.name / "objective_analysis.json"
        data = json.loads(cache_file.read_text())
        
        assert data["event_count"] == 20, "event_count should be updated to prevent retry loops"
        assert data["skipped"]["context_level"] == "observations", "context_level should remain at observations"
        # Reason should be preserved from the higher-context skip
        assert data["skipped"]["reason"] == "no_content"


class TestLegacyCacheCompatibility:
    """Tests for backward compatibility with existing cache files."""

    def test_legacy_cache_without_context_level(self, cache_manager, conv_dir, cache_dir):
        """Legacy cache without context_level should be treated as 'minimal'."""
        # Create legacy cache file (no context_level)
        cache_file = cache_dir / conv_dir.name / "objective_analysis.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "event_count": 5,
            "analyses": {},
            "skipped": {
                "reason": "no_content",
                "at": datetime.now(timezone.utc).isoformat(),
                # No context_level field
            }
        }))
        
        # Should block minimal (default behavior)
        assert cache_manager.is_skipped(conv_dir, 5, context_level="minimal") == "no_content"
        
        # Should allow higher levels
        assert cache_manager.is_skipped(conv_dir, 5, context_level="outcome") is None
        assert cache_manager.is_skipped(conv_dir, 5, context_level="observations") is None
