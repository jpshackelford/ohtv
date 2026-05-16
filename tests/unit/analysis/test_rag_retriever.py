"""Tests for RAGRetriever and RAGRetrievalResult."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ohtv.analysis.rag import RAGRetriever, RAGRetrievalResult, ContextChunk


class TestRAGRetrievalResult:
    """Tests for RAGRetrievalResult dataclass."""

    def test_creation_with_defaults(self):
        """Test creating a result with minimal parameters."""
        result = RAGRetrievalResult(
            context_chunks=[],
            source_conversation_ids=set(),
            search_time_seconds=0.5,
        )
        assert result.context_chunks == []
        assert result.source_conversation_ids == set()
        assert result.search_time_seconds == 0.5
        assert result.temporal_filter_applied is False
        assert result.date_range is None

    def test_creation_with_temporal_filter(self):
        """Test creating a result with temporal filter applied."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        result = RAGRetrievalResult(
            context_chunks=[],
            source_conversation_ids={"abc", "def"},
            search_time_seconds=1.2,
            temporal_filter_applied=True,
            date_range=(start, end),
        )
        assert result.temporal_filter_applied is True
        assert result.date_range == (start, end)


class TestRAGRetrieverInit:
    """Tests for RAGRetriever initialization."""

    def test_init_with_minimal_params(self):
        """Test initializing with only required stores."""
        embed_store = MagicMock()
        conv_store = MagicMock()
        
        retriever = RAGRetriever(embed_store, conv_store)
        
        assert retriever.embed_store is embed_store
        assert retriever.conv_store is conv_store
        assert retriever.enable_temporal_filter is True
        assert retriever.link_store is None
        assert retriever.ref_store is None
        assert retriever.repo_store is None

    def test_init_with_all_params(self):
        """Test initializing with all optional stores."""
        embed_store = MagicMock()
        conv_store = MagicMock()
        link_store = MagicMock()
        ref_store = MagicMock()
        repo_store = MagicMock()
        
        retriever = RAGRetriever(
            embed_store, conv_store,
            enable_temporal_filter=False,
            link_store=link_store,
            ref_store=ref_store,
            repo_store=repo_store,
            cloud_base_url="https://test.example.com",
        )
        
        assert retriever.enable_temporal_filter is False
        assert retriever.link_store is link_store
        assert retriever.ref_store is ref_store
        assert retriever.repo_store is repo_store
        assert retriever.cloud_base_url == "https://test.example.com"

    def test_default_cloud_url(self):
        """Test default cloud URL when not provided."""
        retriever = RAGRetriever(MagicMock(), MagicMock())
        assert "app.all-hands.dev" in retriever.cloud_base_url


class TestRAGRetrieverHelpers:
    """Tests for RAGRetriever helper methods."""

    def test_get_cloud_url(self):
        """Test cloud URL generation."""
        retriever = RAGRetriever(
            MagicMock(), MagicMock(),
            cloud_base_url="https://test.example.com"
        )
        url = retriever._get_cloud_url("abc123")
        assert url == "https://test.example.com/conversations/abc123"

    def test_get_conversation_source_without_stores(self):
        """Test source info is None when stores not provided."""
        retriever = RAGRetriever(MagicMock(), MagicMock())
        result = retriever._get_conversation_source("abc123")
        assert result is None

    def test_get_conversation_source_with_stores(self):
        """Test source info retrieval with all stores."""
        embed_store = MagicMock()
        conv_store = MagicMock()
        link_store = MagicMock()
        ref_store = MagicMock()
        repo_store = MagicMock()
        
        # Mock conversation
        mock_conv = MagicMock()
        mock_conv.title = "Test Conversation"
        mock_conv.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_conv.summary = "Test summary"
        mock_conv.source = "cloud"
        conv_store.get.return_value = mock_conv
        
        # Mock links - empty
        link_store.get_repos_for_conversation.return_value = []
        link_store.get_refs_for_conversation.return_value = []
        
        retriever = RAGRetriever(
            embed_store, conv_store,
            link_store=link_store,
            ref_store=ref_store,
            repo_store=repo_store,
        )
        
        result = retriever._get_conversation_source("abc123")
        
        assert result is not None
        assert result.conversation_id == "abc123"
        assert result.title == "Test Conversation"
        assert result.source == "cloud"


class TestRAGRetrieverRetrieve:
    """Tests for RAGRetriever.retrieve method."""

    @patch("ohtv.analysis.embeddings.get_embedding")
    def test_retrieve_basic(self, mock_get_embedding):
        """Test basic retrieval without temporal filter."""
        # Setup mocks
        mock_get_embedding.return_value = MagicMock(embedding=[0.1] * 1536)
        
        embed_store = MagicMock()
        conv_store = MagicMock()
        
        # Mock embedding search results
        mock_result = MagicMock()
        mock_result.conversation_id = "abc123"
        mock_result.embed_type = "analysis"
        mock_result.source_text = "Test content"
        mock_result.score = 0.85
        mock_result.chunk_index = 0
        embed_store.get_context_for_rag.return_value = [mock_result]
        
        # Mock conversation
        mock_conv = MagicMock()
        mock_conv.title = "Test Conversation"
        mock_conv.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_conv.summary = None
        mock_conv.source = "local"
        conv_store.get.return_value = mock_conv
        
        retriever = RAGRetriever(
            embed_store, conv_store,
            enable_temporal_filter=False,
        )
        
        result = retriever.retrieve("test query", max_context_chunks=5)
        
        assert len(result.context_chunks) == 1
        assert result.source_conversation_ids == {"abc123"}
        assert result.temporal_filter_applied is False
        assert result.context_chunks[0].title == "Test Conversation"
        assert result.context_chunks[0].score == 0.85

    @patch("ohtv.analysis.embeddings.get_embedding")
    def test_retrieve_with_no_results(self, mock_get_embedding):
        """Test retrieval when no results found."""
        mock_get_embedding.return_value = MagicMock(embedding=[0.1] * 1536)
        
        embed_store = MagicMock()
        embed_store.get_context_for_rag.return_value = []
        
        retriever = RAGRetriever(
            embed_store, MagicMock(),
            enable_temporal_filter=False,
        )
        
        result = retriever.retrieve("test query")
        
        assert len(result.context_chunks) == 0
        assert result.source_conversation_ids == set()

    @patch("ohtv.analysis.temporal.extract_temporal_filter")
    @patch("ohtv.analysis.embeddings.get_embedding")
    def test_retrieve_with_temporal_filter(self, mock_get_embedding, mock_extract):
        """Test retrieval with temporal filter applied."""
        mock_get_embedding.return_value = MagicMock(embedding=[0.1] * 1536)
        
        # Mock temporal filter extraction
        mock_temporal = MagicMock()
        mock_temporal.has_temporal_intent = True
        mock_temporal.start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_temporal.end_date = datetime(2024, 1, 31, tzinfo=timezone.utc)
        mock_temporal.cleaned_query = "what happened"
        mock_extract.return_value = mock_temporal
        
        embed_store = MagicMock()
        conv_store = MagicMock()
        
        # Mock embedding search results
        mock_result = MagicMock()
        mock_result.conversation_id = "abc123"
        mock_result.embed_type = "summary"
        mock_result.source_text = "Content"
        mock_result.score = 0.75
        mock_result.chunk_index = 0
        embed_store.get_context_for_rag.return_value = [mock_result]
        
        mock_conv = MagicMock()
        mock_conv.title = "Test"
        mock_conv.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_conv.summary = None
        mock_conv.source = "cloud"
        conv_store.get.return_value = mock_conv
        
        retriever = RAGRetriever(
            embed_store, conv_store,
            enable_temporal_filter=True,
        )
        
        result = retriever.retrieve("what happened last month")
        
        assert result.temporal_filter_applied is True
        assert result.date_range == (mock_temporal.start_date, mock_temporal.end_date)

    @patch("ohtv.analysis.embeddings.get_embedding")
    def test_retrieve_respects_min_score(self, mock_get_embedding):
        """Test that min_score is passed to the store."""
        mock_get_embedding.return_value = MagicMock(embedding=[0.1] * 1536)
        
        embed_store = MagicMock()
        embed_store.get_context_for_rag.return_value = []
        
        retriever = RAGRetriever(
            embed_store, MagicMock(),
            enable_temporal_filter=False,
        )
        
        retriever.retrieve("test", min_score=0.6)
        
        embed_store.get_context_for_rag.assert_called_once()
        call_kwargs = embed_store.get_context_for_rag.call_args[1]
        assert call_kwargs["min_score"] == 0.6

    @patch("ohtv.analysis.embeddings.get_embedding")
    def test_retrieve_sorts_chunks(self, mock_get_embedding):
        """Test that chunks are sorted by conversation, type, index."""
        mock_get_embedding.return_value = MagicMock(embedding=[0.1] * 1536)
        
        embed_store = MagicMock()
        conv_store = MagicMock()
        
        # Create unsorted results
        results = [
            MagicMock(
                conversation_id="def",
                embed_type="content",
                source_text="Content 2",
                score=0.8,
                chunk_index=0,
            ),
            MagicMock(
                conversation_id="abc",
                embed_type="analysis",
                source_text="Analysis",
                score=0.9,
                chunk_index=0,
            ),
            MagicMock(
                conversation_id="abc",
                embed_type="summary",
                source_text="Summary",
                score=0.85,
                chunk_index=0,
            ),
        ]
        embed_store.get_context_for_rag.return_value = results
        
        mock_conv = MagicMock()
        mock_conv.title = "Test"
        mock_conv.created_at = None
        mock_conv.summary = None
        mock_conv.source = "local"
        conv_store.get.return_value = mock_conv
        
        retriever = RAGRetriever(
            embed_store, conv_store,
            enable_temporal_filter=False,
        )
        
        result = retriever.retrieve("test")
        
        # Should be sorted by conversation_id, then embed_type, then chunk_index
        assert result.context_chunks[0].conversation_id == "abc"
        assert result.context_chunks[0].embed_type == "analysis"
        assert result.context_chunks[1].conversation_id == "abc"
        assert result.context_chunks[1].embed_type == "summary"
        assert result.context_chunks[2].conversation_id == "def"


class TestDisplayRetrievalBreakdown:
    """Tests for _display_retrieval_breakdown CLI helper."""

    def test_import(self):
        """Test that the helper function can be imported from cli module."""
        # This is mainly a smoke test to ensure the function exists
        from ohtv.cli import _display_retrieval_breakdown
        assert callable(_display_retrieval_breakdown)

    def test_empty_chunks(self, capsys):
        """Test display with no chunks."""
        from ohtv.cli import _display_retrieval_breakdown
        
        _display_retrieval_breakdown(
            question="test query",
            chunks=[],
            search_time=0.5,
            temporal_applied=False,
            date_range=None,
            explicit_start=None,
            explicit_end=None,
        )
        
        captured = capsys.readouterr()
        assert "No relevant context found" in captured.out

    def test_with_chunks(self, capsys):
        """Test display with actual chunks."""
        from ohtv.cli import _display_retrieval_breakdown
        
        # Create mock chunks
        chunks = [
            MagicMock(
                conversation_id="abc123",
                embed_type="analysis",
                title="Test Conversation",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                summary=None,
                score=0.85,
            ),
            MagicMock(
                conversation_id="abc123",
                embed_type="summary",
                title="Test Conversation",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                summary=None,
                score=0.72,
            ),
        ]
        
        _display_retrieval_breakdown(
            question="test query",
            chunks=chunks,
            search_time=0.5,
            temporal_applied=False,
            date_range=None,
            explicit_start=None,
            explicit_end=None,
        )
        
        captured = capsys.readouterr()
        assert "Query:" in captured.out
        assert "test query" in captured.out
        assert "Retrieved 2 chunks from 1 conversations" in captured.out
        assert "analysis" in captured.out
        assert "summary" in captured.out
        assert "0.85" in captured.out or "0.850" in captured.out

    def test_with_temporal_filter(self, capsys):
        """Test display shows temporal filter info."""
        from ohtv.cli import _display_retrieval_breakdown
        
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        chunks = [
            MagicMock(
                conversation_id="abc123",
                embed_type="analysis",
                title="Test",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                summary=None,
                score=0.8,
            ),
        ]
        
        _display_retrieval_breakdown(
            question="test query",
            chunks=chunks,
            search_time=0.5,
            temporal_applied=True,
            date_range=(start, end),
            explicit_start=None,
            explicit_end=None,
        )
        
        captured = capsys.readouterr()
        assert "Auto-filtered" in captured.out
        assert "2024-01-01" in captured.out
        assert "2024-01-31" in captured.out

    def test_with_explicit_date_filter(self, capsys):
        """Test display shows explicit date filter info."""
        from ohtv.cli import _display_retrieval_breakdown
        
        explicit_start = datetime(2024, 2, 1, tzinfo=timezone.utc)
        
        chunks = [
            MagicMock(
                conversation_id="abc123",
                embed_type="summary",
                title="Test",
                created_at=datetime(2024, 2, 15, tzinfo=timezone.utc),
                summary=None,
                score=0.7,
            ),
        ]
        
        _display_retrieval_breakdown(
            question="test query",
            chunks=chunks,
            search_time=0.3,
            temporal_applied=False,
            date_range=None,
            explicit_start=explicit_start,
            explicit_end=None,
        )
        
        captured = capsys.readouterr()
        assert "Explicit filter" in captured.out
        assert "2024-02-01" in captured.out
