"""Tests for StageStore."""

import pytest
from datetime import datetime, timezone

from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore, StageStore


class TestMarkComplete:
    """Tests for mark_complete method."""

    def test_creates_stage_record(self, db_conn):
        """Should create a new stage completion record."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        
        record = stage_store.get("conv-1", "refs")
        assert record is not None
        assert record.conversation_id == "conv-1"
        assert record.stage == "refs"
        assert record.event_count == 10

    def test_updates_existing_stage_record(self, db_conn):
        """Should update an existing stage record."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=20))
        stage_store.mark_complete("conv-1", "refs", 10)
        stage_store.mark_complete("conv-1", "refs", 20)
        
        record = stage_store.get("conv-1", "refs")
        assert record.event_count == 20

    def test_tracks_multiple_stages_independently(self, db_conn):
        """Should track different stages separately."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=15))
        stage_store.mark_complete("conv-1", "refs", 10)
        stage_store.mark_complete("conv-1", "objectives", 15)
        
        refs_record = stage_store.get("conv-1", "refs")
        obj_record = stage_store.get("conv-1", "objectives")
        
        assert refs_record.event_count == 10
        assert obj_record.event_count == 15


class TestNeedsProcessing:
    """Tests for needs_processing method."""

    def test_returns_true_when_never_processed(self, db_conn):
        """Should return True for conversations never processed for a stage."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        
        assert stage_store.needs_processing("conv-1", "refs", 10) is True

    def test_returns_true_when_new_events(self, db_conn):
        """Should return True when conversation has new events since processing."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=20))
        stage_store.mark_complete("conv-1", "refs", 10)
        
        assert stage_store.needs_processing("conv-1", "refs", 20) is True

    def test_returns_false_when_up_to_date(self, db_conn):
        """Should return False when stage is current."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        
        assert stage_store.needs_processing("conv-1", "refs", 10) is False


class TestGetPendingConversations:
    """Tests for get_pending_conversations method."""

    def test_returns_never_processed_conversations(self, db_conn):
        """Should return conversations that have never been processed."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        conv_store.upsert(Conversation(id="conv-2", location="/path/to/conv-2", event_count=5))
        
        pending = stage_store.get_pending_conversations("refs")
        
        assert len(pending) == 2
        ids = [p[0] for p in pending]
        assert "conv-1" in ids
        assert "conv-2" in ids

    def test_returns_stale_conversations(self, db_conn):
        """Should return conversations with new events since processing."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=20))
        conv_store.upsert(Conversation(id="conv-2", location="/path/to/conv-2", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)  # Stale
        stage_store.mark_complete("conv-2", "refs", 10)  # Current
        
        pending = stage_store.get_pending_conversations("refs")
        
        assert len(pending) == 1
        assert pending[0][0] == "conv-1"
        assert pending[0][1] == 20  # Current event count

    def test_returns_empty_when_all_current(self, db_conn):
        """Should return empty list when all conversations are processed."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        
        pending = stage_store.get_pending_conversations("refs")
        
        assert len(pending) == 0


class TestClearStage:
    """Tests for clear_stage method."""

    def test_clears_specific_conversation(self, db_conn):
        """Should clear stage for a specific conversation."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        conv_store.upsert(Conversation(id="conv-2", location="/path/to/conv-2", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        stage_store.mark_complete("conv-2", "refs", 10)
        
        cleared = stage_store.clear_stage("refs", "conv-1")
        
        assert cleared == 1
        assert stage_store.get("conv-1", "refs") is None
        assert stage_store.get("conv-2", "refs") is not None

    def test_clears_all_conversations_for_stage(self, db_conn):
        """Should clear stage for all conversations when no ID specified."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        conv_store.upsert(Conversation(id="conv-2", location="/path/to/conv-2", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        stage_store.mark_complete("conv-2", "refs", 10)
        stage_store.mark_complete("conv-1", "objectives", 10)  # Different stage
        
        cleared = stage_store.clear_stage("refs")
        
        assert cleared == 2
        assert stage_store.get("conv-1", "refs") is None
        assert stage_store.get("conv-2", "refs") is None
        assert stage_store.get("conv-1", "objectives") is not None  # Preserved


class TestGetStagesForConversation:
    """Tests for get_stages_for_conversation method."""

    def test_returns_all_completed_stages(self, db_conn):
        """Should return all stages completed for a conversation."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        stage_store.mark_complete("conv-1", "refs", 10)
        stage_store.mark_complete("conv-1", "objectives", 10)
        
        stages = stage_store.get_stages_for_conversation("conv-1")
        
        assert len(stages) == 2
        stage_names = [s.stage for s in stages]
        assert "refs" in stage_names
        assert "objectives" in stage_names

    def test_returns_empty_when_none_completed(self, db_conn):
        """Should return empty list for conversations with no completed stages."""
        conv_store = ConversationStore(db_conn)
        stage_store = StageStore(db_conn)
        
        conv_store.upsert(Conversation(id="conv-1", location="/path/to/conv-1", event_count=10))
        
        stages = stage_store.get_stages_for_conversation("conv-1")
        
        assert len(stages) == 0
