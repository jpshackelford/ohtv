"""Unit tests for AnalysisCacheStore."""

import pytest
from datetime import datetime, timezone

from ohtv.db.stores import AnalysisCacheStore
from ohtv.db.stores.analysis_cache_store import (
    AnalysisCacheEntry,
    AnalysisSkipEntry,
    CacheStatus,
)
from ohtv.db.models import Conversation


@pytest.fixture
def analysis_cache_store(db_conn):
    """AnalysisCacheStore backed by the test database."""
    return AnalysisCacheStore(db_conn)


@pytest.fixture
def sample_conversation(conversation_store, db_conn):
    """Create a sample conversation in the database."""
    conv = Conversation(
        id="abc123",
        location="/path/to/conv",
        event_count=42,
    )
    conversation_store.upsert(conv)
    db_conn.commit()
    return conv


class TestUpsertCache:
    """Tests for upsert_cache method."""

    def test_inserts_new_entry(self, analysis_cache_store, sample_conversation):
        entry = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=42,
            content_hash="abcd1234",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry)
        
        assert analysis_cache_store.count_cached("test_key") == 1

    def test_updates_existing_entry(self, analysis_cache_store, sample_conversation):
        entry1 = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=42,
            content_hash="old_hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry1)
        
        entry2 = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=50,
            content_hash="new_hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry2)
        
        # Should still be 1 entry, not 2
        assert analysis_cache_store.count_cached("test_key") == 1

    def test_clears_skip_marker_on_successful_cache(self, analysis_cache_store, sample_conversation):
        # First mark as skipped
        skip_entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_content",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(skip_entry)
        assert analysis_cache_store.count_skipped() == 1
        
        # Now cache successfully
        cache_entry = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=50,
            content_hash="hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(cache_entry)
        
        # Skip marker should be cleared
        assert analysis_cache_store.count_skipped() == 0


class TestUpsertSkip:
    """Tests for upsert_skip method."""

    def test_inserts_skip_marker(self, analysis_cache_store, sample_conversation):
        entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(entry)
        
        assert analysis_cache_store.count_skipped() == 1

    def test_updates_existing_skip_marker(self, analysis_cache_store, sample_conversation):
        entry1 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="old_reason",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(entry1)
        
        entry2 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=50,
            reason="new_reason",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(entry2)
        
        # Should still be 1 entry
        assert analysis_cache_store.count_skipped() == 1


class TestGetCacheStatusBatch:
    """Tests for get_cache_status_batch method."""

    def test_returns_cached_status(self, analysis_cache_store, sample_conversation):
        entry = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=42,  # Same as conversation event_count
            content_hash="hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry)
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        assert "abc123" in status_map
        status = status_map["abc123"]
        assert status.current_event_count == 42
        assert status.cached_event_count == 42
        assert status.needs_analysis is False

    def test_returns_needs_analysis_when_event_count_changed(self, analysis_cache_store, sample_conversation):
        entry = AnalysisCacheEntry(
            conversation_id="abc123",
            cache_key="test_key",
            event_count=30,  # Different from conversation event_count (42)
            content_hash="hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry)
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        status = status_map["abc123"]
        assert status.current_event_count == 42
        assert status.cached_event_count == 30
        assert status.needs_analysis is True

    def test_returns_needs_analysis_when_not_cached(self, analysis_cache_store, sample_conversation):
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        status = status_map["abc123"]
        assert status.cached_event_count is None
        assert status.needs_analysis is True

    def test_handles_skipped_status(self, analysis_cache_store, sample_conversation):
        entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,  # Same as conversation
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(entry)
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        status = status_map["abc123"]
        assert status.is_skipped is True
        assert status.skip_reason == "no_events"
        assert status.needs_analysis is False

    def test_skipped_needs_retry_when_event_count_changed(self, analysis_cache_store, conversation_store):
        # Create conversation with 50 events
        conv = Conversation(id="abc123", location="/path", event_count=50)
        conversation_store.upsert(conv)
        
        # Mark as skipped at 42 events
        entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,  # Different from current 50
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(entry)
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        status = status_map["abc123"]
        # is_skipped indicates skip marker exists, but needs_analysis should be True
        # because event count changed (conversation grew since it was skipped)
        assert status.is_skipped is True
        assert status.skip_event_count == 42
        assert status.current_event_count == 50
        assert status.needs_analysis is True  # Should retry because event count changed

    def test_handles_multiple_conversations(self, analysis_cache_store, conversation_store):
        # Create multiple conversations
        for i in range(3):
            conv = Conversation(id=f"conv{i}", location=f"/path/{i}", event_count=10 + i)
            conversation_store.upsert(conv)
        
        # Cache one
        entry = AnalysisCacheEntry(
            conversation_id="conv0",
            cache_key="key",
            event_count=10,
            content_hash="hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry)
        
        # Skip one
        skip = AnalysisSkipEntry(
            conversation_id="conv1",
            event_count=11,
            reason="no_content",
            skipped_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_skip(skip)
        
        status_map = analysis_cache_store.get_cache_status_batch(["conv0", "conv1", "conv2"], "key")
        
        assert status_map["conv0"].needs_analysis is False  # Cached
        assert status_map["conv1"].needs_analysis is False  # Skipped
        assert status_map["conv2"].needs_analysis is True   # Neither

    def test_returns_empty_for_empty_input(self, analysis_cache_store):
        status_map = analysis_cache_store.get_cache_status_batch([], "test_key")
        assert status_map == {}


class TestGetUncachedConversationIds:
    """Tests for get_uncached_conversation_ids method."""

    def test_returns_uncached_ids(self, analysis_cache_store, conversation_store):
        # Create conversations
        for i in range(3):
            conv = Conversation(id=f"conv{i}", location=f"/path/{i}", event_count=10)
            conversation_store.upsert(conv)
        
        # Cache conv0
        entry = AnalysisCacheEntry(
            conversation_id="conv0",
            cache_key="key",
            event_count=10,
            content_hash="hash",
            analyzed_at=datetime.now(timezone.utc),
        )
        analysis_cache_store.upsert_cache(entry)
        
        uncached = analysis_cache_store.get_uncached_conversation_ids(["conv0", "conv1", "conv2"], "key")
        
        assert sorted(uncached) == ["conv1", "conv2"]


class TestCacheStatus:
    """Tests for CacheStatus dataclass."""

    def test_needs_analysis_when_not_cached(self):
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            cached_event_count=None,
        )
        assert status.needs_analysis is True

    def test_no_analysis_when_cached_current(self):
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            cached_event_count=10,
        )
        assert status.needs_analysis is False

    def test_needs_analysis_when_cached_stale(self):
        status = CacheStatus(
            conversation_id="test",
            current_event_count=15,
            cached_event_count=10,
        )
        assert status.needs_analysis is True

    def test_no_analysis_when_skipped_current(self):
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            is_skipped=True,
            skip_event_count=10,  # Matches current
        )
        assert status.needs_analysis is False

    def test_needs_analysis_when_skipped_stale(self):
        status = CacheStatus(
            conversation_id="test",
            current_event_count=15,  # Conversation grew
            is_skipped=True,
            skip_event_count=10,  # Older skip
        )
        assert status.needs_analysis is True
