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


class TestContextAwareSkipCache:
    """Tests for context-level-aware skip caching."""

    def test_skip_at_minimal_allows_retry_at_full(self):
        """Skip at 'minimal' context should allow retry at 'full'."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            is_skipped=True,
            skip_event_count=10,
            skip_context_level="minimal",
        )
        # Legacy property doesn't consider context
        assert status.needs_analysis is False
        # Context-aware method allows retry at higher level
        assert status.needs_analysis_for_context("minimal") is False
        assert status.needs_analysis_for_context("default") is True
        assert status.needs_analysis_for_context("full") is True

    def test_skip_at_default_allows_retry_at_full(self):
        """Skip at 'default' context should allow retry at 'full' only."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            is_skipped=True,
            skip_event_count=10,
            skip_context_level="default",
        )
        assert status.needs_analysis_for_context("minimal") is False
        assert status.needs_analysis_for_context("default") is False
        assert status.needs_analysis_for_context("full") is True

    def test_skip_at_full_blocks_all_contexts(self):
        """Skip at 'full' context should block all context levels."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            is_skipped=True,
            skip_event_count=10,
            skip_context_level="full",
        )
        assert status.needs_analysis_for_context("minimal") is False
        assert status.needs_analysis_for_context("default") is False
        assert status.needs_analysis_for_context("full") is False

    def test_legacy_skip_treated_as_minimal(self):
        """Skip without context_level should be treated as 'minimal'."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            is_skipped=True,
            skip_event_count=10,
            skip_context_level=None,  # Legacy entry
        )
        # Should allow retry at higher levels
        assert status.needs_analysis_for_context("minimal") is False
        assert status.needs_analysis_for_context("default") is True
        assert status.needs_analysis_for_context("full") is True

    def test_skip_still_invalidated_when_event_count_changes(self):
        """Skip should be invalidated if event count changed, regardless of context."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=15,  # Conversation grew
            is_skipped=True,
            skip_event_count=10,  # Old skip
            skip_context_level="full",
        )
        # Even at 'full', needs retry because event count changed
        assert status.needs_analysis_for_context("minimal") is True
        assert status.needs_analysis_for_context("full") is True

    def test_cached_analysis_still_valid(self):
        """Cached analysis should still block even with context-aware checks."""
        status = CacheStatus(
            conversation_id="test",
            current_event_count=10,
            cached_event_count=10,  # Cache hit
            is_skipped=False,
        )
        assert status.needs_analysis_for_context("minimal") is False
        assert status.needs_analysis_for_context("full") is False


class TestUpsertSkipWithContextLevel:
    """Tests for upsert_skip with context_level."""

    def test_inserts_skip_with_context_level(self, analysis_cache_store, sample_conversation, db_conn):
        entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
            context_level="default",
        )
        analysis_cache_store.upsert_skip(entry)
        db_conn.commit()
        
        # Verify context_level is stored
        cursor = db_conn.execute(
            "SELECT context_level FROM analysis_skips WHERE conversation_id = ?",
            ("abc123",),
        )
        row = cursor.fetchone()
        assert row[0] == "default"

    def test_does_not_downgrade_context_level(self, analysis_cache_store, sample_conversation, db_conn):
        """Skip at higher context should not be overwritten by lower context skip."""
        # First skip at 'full'
        entry1 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_content",
            skipped_at=datetime.now(timezone.utc),
            context_level="full",
        )
        analysis_cache_store.upsert_skip(entry1)
        db_conn.commit()
        
        # Try to skip at 'minimal' - should be ignored
        entry2 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
            context_level="minimal",
        )
        analysis_cache_store.upsert_skip(entry2)
        db_conn.commit()
        
        # Verify context_level is still 'full'
        cursor = db_conn.execute(
            "SELECT context_level, reason FROM analysis_skips WHERE conversation_id = ?",
            ("abc123",),
        )
        row = cursor.fetchone()
        assert row[0] == "full"
        assert row[1] == "no_content"

    def test_upgrades_context_level(self, analysis_cache_store, sample_conversation, db_conn):
        """Skip at lower context should be upgraded by higher context skip."""
        # First skip at 'minimal'
        entry1 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
            context_level="minimal",
        )
        analysis_cache_store.upsert_skip(entry1)
        db_conn.commit()
        
        # Skip at 'full' - should upgrade
        entry2 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_content",
            skipped_at=datetime.now(timezone.utc),
            context_level="full",
        )
        analysis_cache_store.upsert_skip(entry2)
        db_conn.commit()
        
        # Verify context_level is now 'full'
        cursor = db_conn.execute(
            "SELECT context_level, reason FROM analysis_skips WHERE conversation_id = ?",
            ("abc123",),
        )
        row = cursor.fetchone()
        assert row[0] == "full"
        assert row[1] == "no_content"

    def test_event_count_updated_despite_higher_context_skip(
        self, analysis_cache_store, sample_conversation, db_conn
    ):
        """Event count should be updated even when not downgrading context level.
        
        This prevents infinite retry loops when:
        1. Conversation is skipped at 'full' with event_count=10
        2. Conversation grows to 20 events
        3. Batch run at 'minimal' context fails, calls upsert_skip(20, 'minimal')
        4. Without this fix, the early return would leave event_count=10, causing endless retries
        """
        # Skip at 'full' with event_count=10
        entry1 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=10,
            reason="no_content",
            skipped_at=datetime.now(timezone.utc),
            context_level="full",
        )
        analysis_cache_store.upsert_skip(entry1)
        db_conn.commit()
        
        # Conversation grows to 20 events, batch run fails at 'minimal'
        entry2 = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=20,
            reason="still_no_content",
            skipped_at=datetime.now(timezone.utc),
            context_level="minimal",
        )
        analysis_cache_store.upsert_skip(entry2)
        db_conn.commit()
        
        # Verify event_count was updated (even though context stayed at 'full')
        cursor = db_conn.execute(
            "SELECT event_count, context_level, reason FROM analysis_skips WHERE conversation_id = ?",
            ("abc123",),
        )
        row = cursor.fetchone()
        assert row[0] == 20, "event_count should be updated to prevent retry loops"
        assert row[1] == "full", "context_level should remain at 'full'"
        # Reason should be preserved from the higher-context skip
        assert row[2] == "no_content"


class TestGetCacheStatusBatchWithContextLevel:
    """Tests for get_cache_status_batch returning skip_context_level."""

    def test_returns_skip_context_level(self, analysis_cache_store, sample_conversation, db_conn):
        entry = AnalysisSkipEntry(
            conversation_id="abc123",
            event_count=42,
            reason="no_events",
            skipped_at=datetime.now(timezone.utc),
            context_level="default",
        )
        analysis_cache_store.upsert_skip(entry)
        db_conn.commit()
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        assert "abc123" in status_map
        status = status_map["abc123"]
        assert status.is_skipped is True
        assert status.skip_context_level == "default"

    def test_legacy_skip_returns_minimal(self, analysis_cache_store, sample_conversation, db_conn):
        """Skip without explicit context_level should return default 'minimal'."""
        # Insert directly without context_level (simulates legacy data)
        db_conn.execute(
            """
            INSERT INTO analysis_skips (conversation_id, event_count, reason, skipped_at)
            VALUES (?, ?, ?, ?)
            """,
            ("abc123", 42, "no_events", datetime.now(timezone.utc).isoformat()),
        )
        db_conn.commit()
        
        status_map = analysis_cache_store.get_cache_status_batch(["abc123"], "test_key")
        
        status = status_map["abc123"]
        assert status.is_skipped is True
        # SQLite default is 'minimal' from migration
        assert status.skip_context_level == "minimal"
