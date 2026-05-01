"""Tests for EmbeddingStore."""

import pytest
import struct
from datetime import datetime, timezone

from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore, EmbeddingStore


@pytest.fixture
def embedding_store(db_conn):
    """EmbeddingStore backed by the test database."""
    return EmbeddingStore(db_conn)


@pytest.fixture
def conversation_store(db_conn):
    """ConversationStore backed by the test database."""
    return ConversationStore(db_conn)


@pytest.fixture
def sample_embedding():
    """Sample embedding vector (1536 dims like text-embedding-3-small)."""
    import random
    random.seed(42)
    return [random.random() for _ in range(1536)]


@pytest.fixture
def sample_embedding_small():
    """Small embedding vector for fast tests."""
    return [0.1, 0.2, 0.3, 0.4, 0.5]


def _create_conversation(store: ConversationStore, conv_id: str) -> None:
    """Helper to create a conversation for foreign key constraints."""
    conv = Conversation(id=conv_id, location=f"/test/{conv_id}")
    store.upsert(conv)


class TestEmbeddingStore:
    """Tests for basic embedding operations."""
    
    def test_upsert_and_get(self, embedding_store, conversation_store, sample_embedding_small):
        """Test inserting and retrieving an embedding."""
        import numpy as np
        
        conv_id = "test-conv-123"
        model = "openai/text-embedding-3-small"
        
        _create_conversation(conversation_store, conv_id)
        embedding_store.upsert(
            conv_id, sample_embedding_small, model, 
            embed_type="summary", token_count=100
        )
        
        result = embedding_store.get(conv_id, embed_type="summary")
        assert result is not None
        
        embedding, record = result
        # Use numpy for approximate comparison (float32 precision)
        assert np.allclose(embedding, sample_embedding_small, rtol=1e-5)
        assert record.conversation_id == conv_id
        assert record.dimensions == len(sample_embedding_small)
        assert record.model == model
        assert record.token_count == 100
        assert isinstance(record.created_at, datetime)
    
    def test_get_nonexistent(self, embedding_store):
        """Test getting a non-existent embedding returns None."""
        result = embedding_store.get("nonexistent-conv")
        assert result is None
    
    def test_upsert_updates_existing(self, embedding_store, conversation_store, sample_embedding_small):
        """Test that upsert updates an existing embedding."""
        import numpy as np
        
        conv_id = "test-conv-123"
        _create_conversation(conversation_store, conv_id)
        
        # Insert first embedding
        embedding_store.upsert(
            conv_id, sample_embedding_small, "model-v1", 
            embed_type="summary", token_count=100
        )
        
        # Update with new embedding
        new_embedding = [0.9, 0.8, 0.7, 0.6, 0.5]
        embedding_store.upsert(
            conv_id, new_embedding, "model-v2", 
            embed_type="summary", token_count=200
        )
        
        result = embedding_store.get(conv_id, embed_type="summary")
        assert result is not None
        
        embedding, record = result
        assert np.allclose(embedding, new_embedding, rtol=1e-5)
        assert record.model == "model-v2"
        assert record.token_count == 200
    
    def test_delete(self, embedding_store, conversation_store, sample_embedding_small):
        """Test deleting an embedding."""
        conv_id = "test-conv-123"
        _create_conversation(conversation_store, conv_id)
        embedding_store.upsert(
            conv_id, sample_embedding_small, "model", 
            embed_type="summary", token_count=100
        )
        
        assert embedding_store.get(conv_id) is not None
        
        deleted = embedding_store.delete(conv_id)
        assert deleted == 1  # Returns count of deleted rows
        assert embedding_store.get(conv_id) is None
    
    def test_delete_nonexistent(self, embedding_store):
        """Test deleting a non-existent embedding returns 0."""
        deleted = embedding_store.delete("nonexistent-conv")
        assert deleted == 0
    
    def test_count(self, embedding_store, conversation_store, sample_embedding_small):
        """Test counting embeddings."""
        assert embedding_store.count() == 0
        
        _create_conversation(conversation_store, "conv-1")
        embedding_store.upsert(
            "conv-1", sample_embedding_small, "model", 
            embed_type="summary", token_count=100
        )
        assert embedding_store.count() == 1
        
        _create_conversation(conversation_store, "conv-2")
        embedding_store.upsert(
            "conv-2", sample_embedding_small, "model", 
            embed_type="summary", token_count=100
        )
        assert embedding_store.count() == 2
        
        embedding_store.delete("conv-1")
        assert embedding_store.count() == 1
    
    def test_count_by_model(self, embedding_store, conversation_store, sample_embedding_small):
        """Test counting embeddings by model."""
        for i in range(1, 4):
            _create_conversation(conversation_store, f"conv-{i}")
        
        embedding_store.upsert(
            "conv-1", sample_embedding_small, "model-a", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-2", sample_embedding_small, "model-a", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-3", sample_embedding_small, "model-b", 
            embed_type="summary", token_count=100
        )
        
        counts = embedding_store.count_by_model()
        assert counts == {"model-a": 2, "model-b": 1}
    
    def test_list_conversation_ids(self, embedding_store, conversation_store, sample_embedding_small):
        """Test listing conversation IDs with embeddings."""
        assert embedding_store.list_conversation_ids() == []
        
        _create_conversation(conversation_store, "conv-1")
        _create_conversation(conversation_store, "conv-2")
        embedding_store.upsert(
            "conv-1", sample_embedding_small, "model", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-2", sample_embedding_small, "model", 
            embed_type="summary", token_count=100
        )
        
        ids = embedding_store.list_conversation_ids()
        assert set(ids) == {"conv-1", "conv-2"}


class TestSemanticSearch:
    """Tests for semantic search functionality."""
    
    def test_search_basic(self, embedding_store, conversation_store):
        """Test basic semantic search."""
        # Create conversations for FK constraints
        for i in range(1, 4):
            _create_conversation(conversation_store, f"conv-{i}")
        
        # Create some embeddings with distinct values
        embedding_store.upsert(
            "conv-1", [1.0, 0.0, 0.0], "model", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-2", [0.0, 1.0, 0.0], "model", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-3", [0.9, 0.1, 0.0], "model",  # Similar to conv-1
            embed_type="summary", token_count=100
        )
        
        # Search with a query similar to conv-1
        query = [0.95, 0.05, 0.0]
        results = embedding_store.search(query, limit=3)
        
        assert len(results) == 3
        # conv-3 and conv-1 should be most similar
        assert results[0].conversation_id in ("conv-1", "conv-3")
        assert results[0].rank == 1
        assert results[0].score > 0.9
    
    def test_search_limit(self, embedding_store, conversation_store):
        """Test search respects limit."""
        for i in range(10):
            _create_conversation(conversation_store, f"conv-{i}")
            embedding_store.upsert(
                f"conv-{i}", [1.0, 0.0, 0.0], "model", 
                embed_type="summary", token_count=100
            )
        
        results = embedding_store.search([1.0, 0.0, 0.0], limit=3)
        assert len(results) == 3
    
    def test_search_min_score(self, embedding_store, conversation_store):
        """Test search filters by minimum score."""
        _create_conversation(conversation_store, "conv-1")
        _create_conversation(conversation_store, "conv-2")
        
        embedding_store.upsert(
            "conv-1", [1.0, 0.0, 0.0], "model", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-2", [0.0, 1.0, 0.0], "model",  # Orthogonal = low score
            embed_type="summary", token_count=100
        )
        
        # With min_score=0, should get both
        results = embedding_store.search([1.0, 0.0, 0.0], min_score=0.0)
        assert len(results) == 2
        
        # With high min_score, should only get the similar one
        results = embedding_store.search([1.0, 0.0, 0.0], min_score=0.9)
        assert len(results) == 1
        assert results[0].conversation_id == "conv-1"
    
    def test_search_empty_database(self, embedding_store):
        """Test search on empty database."""
        results = embedding_store.search([1.0, 0.0, 0.0])
        assert results == []
    
    def test_search_dimension_mismatch(self, embedding_store, conversation_store):
        """Test search only matches embeddings with same dimensions."""
        _create_conversation(conversation_store, "conv-3d")
        _create_conversation(conversation_store, "conv-5d")
        
        embedding_store.upsert(
            "conv-3d", [1.0, 0.0, 0.0], "model", 
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-5d", [1.0, 0.0, 0.0, 0.0, 0.0], "model", 
            embed_type="summary", token_count=100
        )
        
        # Query with 3 dims should only match 3d embedding
        results = embedding_store.search([1.0, 0.0, 0.0])
        assert len(results) == 1
        assert results[0].conversation_id == "conv-3d"
        
        # Query with 5 dims should only match 5d embedding
        results = embedding_store.search([1.0, 0.0, 0.0, 0.0, 0.0])
        assert len(results) == 1
        assert results[0].conversation_id == "conv-5d"
    
    def test_search_by_embed_type(self, embedding_store, conversation_store):
        """Test filtering search by embedding type."""
        _create_conversation(conversation_store, "conv-1")
        
        # Create different embedding types for the same conversation
        embedding_store.upsert(
            "conv-1", [1.0, 0.0, 0.0], "model",
            embed_type="analysis", token_count=50
        )
        embedding_store.upsert(
            "conv-1", [0.8, 0.2, 0.0], "model",
            embed_type="summary", token_count=100
        )
        embedding_store.upsert(
            "conv-1", [0.5, 0.5, 0.0], "model",
            embed_type="content", chunk_index=0, token_count=200
        )
        
        # Search only analysis type
        results = embedding_store.search(
            [1.0, 0.0, 0.0], embed_types=["analysis"]
        )
        assert len(results) == 1
        assert results[0].embed_type == "analysis"
        
        # Search summary and content
        results = embedding_store.search(
            [1.0, 0.0, 0.0], embed_types=["summary", "content"]
        )
        assert len(results) == 2
        assert all(r.embed_type in ("summary", "content") for r in results)
    
    def test_search_conversations_aggregates(self, embedding_store, conversation_store):
        """Test search_conversations aggregates by conversation."""
        _create_conversation(conversation_store, "conv-1")
        _create_conversation(conversation_store, "conv-2")
        
        # Conv-1 has multiple embeddings
        embedding_store.upsert(
            "conv-1", [1.0, 0.0, 0.0], "model",
            embed_type="analysis", token_count=50
        )
        embedding_store.upsert(
            "conv-1", [0.9, 0.1, 0.0], "model",
            embed_type="summary", token_count=100
        )
        
        # Conv-2 has one embedding
        embedding_store.upsert(
            "conv-2", [0.5, 0.5, 0.0], "model",
            embed_type="summary", token_count=100
        )
        
        # Search conversations
        results = embedding_store.search_conversations([1.0, 0.0, 0.0], limit=10)
        
        # Should get 2 conversations, not 3 embeddings
        assert len(results) == 2
        
        # Conv-1 should be first (better match via analysis embedding)
        assert results[0].conversation_id == "conv-1"
        assert results[0].best_match_type == "analysis"
        assert len(results[0].all_matches) == 2


class TestDateFilteredSearch:
    """Tests for date-filtered semantic search."""
    
    def test_search_with_date_filter(self, embedding_store, conversation_store, db_conn):
        """Test search filters by conversation date."""
        from datetime import datetime, timezone
        
        # Create conversations with different dates
        conv1 = Conversation(id="conv-old", location="/test/conv-old")
        conv1.created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)  # Old
        conversation_store.upsert(conv1)
        
        conv2 = Conversation(id="conv-recent", location="/test/conv-recent")
        conv2.created_at = datetime(2026, 4, 20, tzinfo=timezone.utc)  # Recent
        conversation_store.upsert(conv2)
        
        conv3 = Conversation(id="conv-today", location="/test/conv-today")
        conv3.created_at = datetime(2026, 4, 22, tzinfo=timezone.utc)  # Today
        conversation_store.upsert(conv3)
        
        # Create embeddings for all conversations (similar vectors)
        embedding_store.upsert(
            "conv-old", [1.0, 0.0, 0.0], "model",
            embed_type="summary", source_text="Old conversation"
        )
        embedding_store.upsert(
            "conv-recent", [0.95, 0.05, 0.0], "model",
            embed_type="summary", source_text="Recent conversation"
        )
        embedding_store.upsert(
            "conv-today", [0.9, 0.1, 0.0], "model",
            embed_type="summary", source_text="Today's conversation"
        )
        
        # Search without date filter - should find all
        results = embedding_store.search([1.0, 0.0, 0.0], limit=10)
        assert len(results) == 3
        
        # Search with start_date filter - should exclude old
        start_date = datetime(2026, 4, 15, tzinfo=timezone.utc)
        results = embedding_store.search(
            [1.0, 0.0, 0.0], limit=10, start_date=start_date
        )
        assert len(results) == 2
        conv_ids = {r.conversation_id for r in results}
        assert "conv-old" not in conv_ids
        assert "conv-recent" in conv_ids
        assert "conv-today" in conv_ids
    
    def test_search_with_end_date(self, embedding_store, conversation_store):
        """Test search with end_date filter."""
        from datetime import datetime, timezone
        
        # Create conversations
        conv1 = Conversation(id="conv-old", location="/test/conv-old")
        conv1.created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
        conversation_store.upsert(conv1)
        
        conv2 = Conversation(id="conv-new", location="/test/conv-new")
        conv2.created_at = datetime(2026, 4, 22, tzinfo=timezone.utc)
        conversation_store.upsert(conv2)
        
        embedding_store.upsert("conv-old", [1.0, 0.0, 0.0], "model", embed_type="summary")
        embedding_store.upsert("conv-new", [1.0, 0.0, 0.0], "model", embed_type="summary")
        
        # Filter to only old conversations
        end_date = datetime(2026, 4, 15, tzinfo=timezone.utc)
        results = embedding_store.search([1.0, 0.0, 0.0], limit=10, end_date=end_date)
        
        assert len(results) == 1
        assert results[0].conversation_id == "conv-old"
    
    def test_search_with_date_range(self, embedding_store, conversation_store):
        """Test search with both start and end date."""
        from datetime import datetime, timezone
        
        dates = [
            ("conv-early", datetime(2026, 4, 1, tzinfo=timezone.utc)),
            ("conv-mid", datetime(2026, 4, 10, tzinfo=timezone.utc)),
            ("conv-late", datetime(2026, 4, 20, tzinfo=timezone.utc)),
        ]
        
        for conv_id, created_at in dates:
            conv = Conversation(id=conv_id, location=f"/test/{conv_id}")
            conv.created_at = created_at
            conversation_store.upsert(conv)
            embedding_store.upsert(conv_id, [1.0, 0.0, 0.0], "model", embed_type="summary")
        
        # Filter to middle period only
        start_date = datetime(2026, 4, 5, tzinfo=timezone.utc)
        end_date = datetime(2026, 4, 15, tzinfo=timezone.utc)
        
        results = embedding_store.search(
            [1.0, 0.0, 0.0], limit=10, 
            start_date=start_date, end_date=end_date
        )
        
        assert len(results) == 1
        assert results[0].conversation_id == "conv-mid"
    
    def test_get_context_for_rag_with_dates(self, embedding_store, conversation_store):
        """Test RAG context retrieval with date filtering."""
        from datetime import datetime, timezone
        
        # Create conversations
        conv1 = Conversation(id="conv-old", location="/test/conv-old")
        conv1.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        conversation_store.upsert(conv1)
        
        conv2 = Conversation(id="conv-new", location="/test/conv-new")
        conv2.created_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
        conversation_store.upsert(conv2)
        
        embedding_store.upsert(
            "conv-old", [1.0, 0.0, 0.0], "model",
            embed_type="summary", source_text="Old context text"
        )
        embedding_store.upsert(
            "conv-new", [0.99, 0.01, 0.0], "model",
            embed_type="summary", source_text="New context text"
        )
        
        # Get RAG context with date filter
        start_date = datetime(2026, 4, 20, tzinfo=timezone.utc)
        
        results = embedding_store.get_context_for_rag(
            [1.0, 0.0, 0.0], max_chunks=5, min_score=0.1,
            start_date=start_date
        )
        
        assert len(results) == 1
        assert results[0].conversation_id == "conv-new"
        assert results[0].source_text == "New context text"


class TestFTSSearch:
    """Tests for FTS5 keyword search."""
    
    def test_fts_upsert_and_search(self, embedding_store):
        """Test FTS insert and search."""
        embedding_store.upsert_fts("conv-1", "fix authentication bugs login")
        embedding_store.upsert_fts("conv-2", "docker deployment kubernetes")
        embedding_store.upsert_fts("conv-3", "authentication token jwt")
        
        # Search for authentication
        results = embedding_store.search_fts("authentication")
        assert len(results) == 2
        conv_ids = {r.conversation_id for r in results}
        assert conv_ids == {"conv-1", "conv-3"}
    
    def test_fts_update(self, embedding_store):
        """Test FTS update replaces content."""
        embedding_store.upsert_fts("conv-1", "old content")
        embedding_store.upsert_fts("conv-1", "new content")
        
        # Old content should not be found
        results = embedding_store.search_fts("old")
        assert len(results) == 0
        
        # New content should be found
        results = embedding_store.search_fts("new")
        assert len(results) == 1
    
    def test_fts_limit(self, embedding_store):
        """Test FTS search respects limit."""
        for i in range(10):
            embedding_store.upsert_fts(f"conv-{i}", "common word")
        
        results = embedding_store.search_fts("common", limit=3)
        assert len(results) == 3
    
    def test_fts_porter_stemming(self, embedding_store):
        """Test FTS uses porter stemmer (fixes -> fix)."""
        embedding_store.upsert_fts("conv-1", "fixing bugs")
        
        # "fix" should match "fixing" due to stemming
        results = embedding_store.search_fts("fix")
        assert len(results) == 1
    
    def test_fts_count(self, embedding_store):
        """Test counting FTS indexed conversations."""
        assert embedding_store.count_fts() == 0
        
        embedding_store.upsert_fts("conv-1", "content")
        embedding_store.upsert_fts("conv-2", "content")
        
        assert embedding_store.count_fts() == 2
    
    def test_fts_empty_search(self, embedding_store):
        """Test FTS search on empty database."""
        results = embedding_store.search_fts("anything")
        assert results == []


class TestListConversationsNeedingEmbeddings:
    """Tests for list_conversations_needing_embeddings method."""
    
    def test_returns_conversations_with_no_embeddings(
        self, db_conn, embedding_store, conversation_store, sample_embedding_small
    ):
        """Conversations with no embeddings at all should be returned."""
        # Create conversations
        _create_conversation(conversation_store, "conv1")
        _create_conversation(conversation_store, "conv2")
        _create_conversation(conversation_store, "conv3")
        db_conn.commit()
        
        # Only embed conv2
        embedding_store.upsert("conv2", sample_embedding_small, "test-model")
        db_conn.commit()
        
        # conv1 and conv3 should be returned (no embeddings at all)
        result = embedding_store.list_conversations_needing_embeddings(
            ["conv1", "conv2", "conv3"]
        )
        assert set(result) == {"conv1", "conv3"}
    
    def test_returns_empty_when_all_embedded(
        self, db_conn, embedding_store, conversation_store, sample_embedding_small
    ):
        """If all conversations have embeddings and no missing cache_keys, return empty."""
        _create_conversation(conversation_store, "conv1")
        _create_conversation(conversation_store, "conv2")
        db_conn.commit()
        
        embedding_store.upsert("conv1", sample_embedding_small, "test-model")
        embedding_store.upsert("conv2", sample_embedding_small, "test-model")
        db_conn.commit()
        
        result = embedding_store.list_conversations_needing_embeddings(
            ["conv1", "conv2"]
        )
        assert result == []
    
    def test_handles_dash_normalization(
        self, db_conn, embedding_store, conversation_store, sample_embedding_small
    ):
        """IDs with dashes should match embedded IDs without dashes."""
        # Embed without dashes (as stored in DB)
        _create_conversation(conversation_store, "abc123def456")
        embedding_store.upsert("abc123def456", sample_embedding_small, "test-model")
        db_conn.commit()
        
        # Query with dashes (as returned by some sources)
        result = embedding_store.list_conversations_needing_embeddings(
            ["abc-123-def-456"]  # With dashes
        )
        # Should not need work since it's already embedded
        assert result == []
    
    def test_returns_all_when_none_embedded(self, embedding_store):
        """If nothing is embedded, return all conversations."""
        result = embedding_store.list_conversations_needing_embeddings(
            ["conv1", "conv2", "conv3"]
        )
        assert set(result) == {"conv1", "conv2", "conv3"}
    
    def test_includes_conversations_missing_cache_key_embeddings(
        self, db_conn, embedding_store, conversation_store, sample_embedding_small
    ):
        """Conversations with cached analyses missing embeddings should be included."""
        from ohtv.db.stores import AnalysisCacheStore
        from ohtv.db.stores.analysis_cache_store import AnalysisCacheEntry
        from datetime import datetime, timezone
        
        _create_conversation(conversation_store, "conv1")
        _create_conversation(conversation_store, "conv2")
        db_conn.commit()
        
        # conv1 has an embedding (legacy, no cache_key)
        embedding_store.upsert("conv1", sample_embedding_small, "test-model", 
                               embed_type="analysis", cache_key="")
        # conv2 has an embedding for one cache_key
        embedding_store.upsert("conv2", sample_embedding_small, "test-model",
                               embed_type="analysis", cache_key="assess=False")
        db_conn.commit()
        
        # Add analysis_cache entries - conv1 now has a new cache_key variant
        cache_store = AnalysisCacheStore(db_conn)
        cache_store.upsert_cache(AnalysisCacheEntry(
            conversation_id="conv1",
            cache_key="assess=True",  # New variant, not embedded
            event_count=10,
            content_hash="abc123",
            analyzed_at=datetime.now(timezone.utc),
        ))
        # conv2's cached analysis IS embedded
        cache_store.upsert_cache(AnalysisCacheEntry(
            conversation_id="conv2",
            cache_key="assess=False",  # Already embedded
            event_count=10,
            content_hash="def456",
            analyzed_at=datetime.now(timezone.utc),
        ))
        db_conn.commit()
        
        # conv1 should be returned (has missing cache_key embedding)
        # conv2 should NOT be returned (cache_key is already embedded)
        result = embedding_store.list_conversations_needing_embeddings(
            ["conv1", "conv2"]
        )
        assert result == ["conv1"]
