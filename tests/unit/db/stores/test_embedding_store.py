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
        embedding_store.upsert(conv_id, sample_embedding_small, model, token_count=100)
        
        result = embedding_store.get(conv_id)
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
        embedding_store.upsert(conv_id, sample_embedding_small, "model-v1", 100)
        
        # Update with new embedding
        new_embedding = [0.9, 0.8, 0.7, 0.6, 0.5]
        embedding_store.upsert(conv_id, new_embedding, "model-v2", 200)
        
        result = embedding_store.get(conv_id)
        assert result is not None
        
        embedding, record = result
        assert np.allclose(embedding, new_embedding, rtol=1e-5)
        assert record.model == "model-v2"
        assert record.token_count == 200
    
    def test_delete(self, embedding_store, conversation_store, sample_embedding_small):
        """Test deleting an embedding."""
        conv_id = "test-conv-123"
        _create_conversation(conversation_store, conv_id)
        embedding_store.upsert(conv_id, sample_embedding_small, "model", 100)
        
        assert embedding_store.get(conv_id) is not None
        
        deleted = embedding_store.delete(conv_id)
        assert deleted is True
        assert embedding_store.get(conv_id) is None
    
    def test_delete_nonexistent(self, embedding_store):
        """Test deleting a non-existent embedding returns False."""
        deleted = embedding_store.delete("nonexistent-conv")
        assert deleted is False
    
    def test_count(self, embedding_store, conversation_store, sample_embedding_small):
        """Test counting embeddings."""
        assert embedding_store.count() == 0
        
        _create_conversation(conversation_store, "conv-1")
        embedding_store.upsert("conv-1", sample_embedding_small, "model", 100)
        assert embedding_store.count() == 1
        
        _create_conversation(conversation_store, "conv-2")
        embedding_store.upsert("conv-2", sample_embedding_small, "model", 100)
        assert embedding_store.count() == 2
        
        embedding_store.delete("conv-1")
        assert embedding_store.count() == 1
    
    def test_count_by_model(self, embedding_store, conversation_store, sample_embedding_small):
        """Test counting embeddings by model."""
        for i in range(1, 4):
            _create_conversation(conversation_store, f"conv-{i}")
        
        embedding_store.upsert("conv-1", sample_embedding_small, "model-a", 100)
        embedding_store.upsert("conv-2", sample_embedding_small, "model-a", 100)
        embedding_store.upsert("conv-3", sample_embedding_small, "model-b", 100)
        
        counts = embedding_store.count_by_model()
        assert counts == {"model-a": 2, "model-b": 1}
    
    def test_list_conversation_ids(self, embedding_store, conversation_store, sample_embedding_small):
        """Test listing conversation IDs with embeddings."""
        assert embedding_store.list_conversation_ids() == []
        
        _create_conversation(conversation_store, "conv-1")
        _create_conversation(conversation_store, "conv-2")
        embedding_store.upsert("conv-1", sample_embedding_small, "model", 100)
        embedding_store.upsert("conv-2", sample_embedding_small, "model", 100)
        
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
        embedding_store.upsert("conv-1", [1.0, 0.0, 0.0], "model", 100)
        embedding_store.upsert("conv-2", [0.0, 1.0, 0.0], "model", 100)
        embedding_store.upsert("conv-3", [0.9, 0.1, 0.0], "model", 100)  # Similar to conv-1
        
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
            embedding_store.upsert(f"conv-{i}", [1.0, 0.0, 0.0], "model", 100)
        
        results = embedding_store.search([1.0, 0.0, 0.0], limit=3)
        assert len(results) == 3
    
    def test_search_min_score(self, embedding_store, conversation_store):
        """Test search filters by minimum score."""
        _create_conversation(conversation_store, "conv-1")
        _create_conversation(conversation_store, "conv-2")
        
        embedding_store.upsert("conv-1", [1.0, 0.0, 0.0], "model", 100)
        embedding_store.upsert("conv-2", [0.0, 1.0, 0.0], "model", 100)  # Orthogonal = low score
        
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
        
        embedding_store.upsert("conv-3d", [1.0, 0.0, 0.0], "model", 100)
        embedding_store.upsert("conv-5d", [1.0, 0.0, 0.0, 0.0, 0.0], "model", 100)
        
        # Query with 3 dims should only match 3d embedding
        results = embedding_store.search([1.0, 0.0, 0.0])
        assert len(results) == 1
        assert results[0].conversation_id == "conv-3d"
        
        # Query with 5 dims should only match 5d embedding
        results = embedding_store.search([1.0, 0.0, 0.0, 0.0, 0.0])
        assert len(results) == 1
        assert results[0].conversation_id == "conv-5d"


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
