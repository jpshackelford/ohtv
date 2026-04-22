"""Tests for ohtv.analysis.embeddings module.

These tests verify:
1. Module imports work correctly
2. Text building functions produce expected output
3. Token estimation and cost calculation work
4. The embed_conversation_full function integrates correctly
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import tempfile


class TestModuleImports:
    """Verify all public functions can be imported."""

    def test_import_embedding_result(self):
        from ohtv.analysis.embeddings import EmbeddingResult
        assert EmbeddingResult is not None

    def test_import_get_embedding_model(self):
        from ohtv.analysis.embeddings import get_embedding_model
        assert callable(get_embedding_model)

    def test_import_get_embedding_dimension(self):
        from ohtv.analysis.embeddings import get_embedding_dimension
        assert callable(get_embedding_dimension)

    def test_import_estimate_cost(self):
        from ohtv.analysis.embeddings import estimate_cost
        assert callable(estimate_cost)

    def test_import_get_embedding(self):
        from ohtv.analysis.embeddings import get_embedding
        assert callable(get_embedding)

    def test_import_build_analysis_text(self):
        from ohtv.analysis.embeddings import build_analysis_text
        assert callable(build_analysis_text)

    def test_import_build_summary_text(self):
        from ohtv.analysis.embeddings import build_summary_text
        assert callable(build_summary_text)

    def test_import_build_content_text(self):
        from ohtv.analysis.embeddings import build_content_text
        assert callable(build_content_text)

    def test_import_build_conversation_texts(self):
        from ohtv.analysis.embeddings import build_conversation_texts
        assert callable(build_conversation_texts)

    def test_import_build_lean_transcript(self):
        from ohtv.analysis.embeddings import build_lean_transcript
        assert callable(build_lean_transcript)

    def test_import_estimate_tokens(self):
        from ohtv.analysis.embeddings import estimate_tokens
        assert callable(estimate_tokens)

    def test_import_embedding_stats(self):
        from ohtv.analysis.embeddings import EmbeddingStats
        assert EmbeddingStats is not None

    def test_import_embed_conversation(self):
        from ohtv.analysis.embeddings import embed_conversation
        assert callable(embed_conversation)

    def test_import_embed_conversation_full(self):
        from ohtv.analysis.embeddings import embed_conversation_full
        assert callable(embed_conversation_full)

    def test_import_estimate_conversation_tokens(self):
        from ohtv.analysis.embeddings import estimate_conversation_tokens
        assert callable(estimate_conversation_tokens)

    def test_import_check_embedding_status(self):
        from ohtv.analysis.embeddings import check_embedding_status
        assert callable(check_embedding_status)

    def test_import_check_embedding_types(self):
        from ohtv.analysis.embeddings import check_embedding_types
        assert callable(check_embedding_types)

    def test_import_chunk_text(self):
        from ohtv.analysis.embeddings import chunk_text
        assert callable(chunk_text)

    def test_import_conversation_texts(self):
        from ohtv.analysis.embeddings import ConversationTexts
        assert ConversationTexts is not None

    def test_import_text_chunk(self):
        from ohtv.analysis.embeddings import TextChunk
        assert TextChunk is not None


class TestGetEmbeddingModel:
    """Tests for get_embedding_model()."""

    def test_returns_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        from ohtv.analysis.embeddings import get_embedding_model, DEFAULT_EMBEDDING_MODEL
        assert get_embedding_model() == DEFAULT_EMBEDDING_MODEL

    def test_returns_env_value_when_set(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "custom/model")
        from ohtv.analysis.embeddings import get_embedding_model
        assert get_embedding_model() == "custom/model"


class TestGetEmbeddingDimension:
    """Tests for get_embedding_dimension()."""

    def test_returns_known_dimension(self):
        from ohtv.analysis.embeddings import get_embedding_dimension
        assert get_embedding_dimension("openai/text-embedding-3-small") == 1536
        assert get_embedding_dimension("openai/text-embedding-3-large") == 3072

    def test_returns_default_for_unknown_model(self):
        from ohtv.analysis.embeddings import get_embedding_dimension
        assert get_embedding_dimension("unknown/model") == 1536

    def test_uses_env_model_when_none(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
        from ohtv.analysis.embeddings import get_embedding_dimension
        assert get_embedding_dimension(None) == 3072


class TestEstimateCost:
    """Tests for estimate_cost()."""

    def test_calculates_cost_for_known_model(self):
        from ohtv.analysis.embeddings import estimate_cost
        # 1M tokens at $0.02/M = $0.02
        assert estimate_cost(1_000_000, "openai/text-embedding-3-small") == pytest.approx(0.02)

    def test_calculates_cost_for_unknown_model(self):
        from ohtv.analysis.embeddings import estimate_cost
        # Unknown models default to 3-small pricing
        assert estimate_cost(1_000_000, "unknown/model") == pytest.approx(0.02)

    def test_scales_with_token_count(self):
        from ohtv.analysis.embeddings import estimate_cost
        assert estimate_cost(500_000, "openai/text-embedding-3-small") == pytest.approx(0.01)


class TestEstimateTokens:
    """Tests for estimate_tokens()."""

    def test_estimates_tokens_from_words(self):
        from ohtv.analysis.embeddings import estimate_tokens
        # ~1.3 tokens per word
        text = "one two three four five"  # 5 words
        result = estimate_tokens(text)
        assert result == int(5 * 1.3)

    def test_handles_empty_text(self):
        from ohtv.analysis.embeddings import estimate_tokens
        assert estimate_tokens("") == 0


class TestBuildAnalysisText:
    """Tests for build_analysis_text()."""

    def test_builds_text_from_analysis(self):
        from ohtv.analysis.embeddings import build_analysis_text
        analysis = {
            "goal": "Fix the bug",
            "primary_outcomes": ["Bug fixed", "Tests pass"],
            "secondary_outcomes": ["Documentation updated"],
            "tags": ["bugfix", "testing"],
        }
        result = build_analysis_text(analysis)
        assert "Goal: Fix the bug" in result
        assert "Outcomes: Bug fixed; Tests pass" in result
        assert "Additional: Documentation updated" in result
        assert "Tags: bugfix, testing" in result

    def test_returns_none_for_empty_analysis(self):
        from ohtv.analysis.embeddings import build_analysis_text
        assert build_analysis_text({}) is None
        assert build_analysis_text(None) is None

    def test_handles_partial_analysis(self):
        from ohtv.analysis.embeddings import build_analysis_text
        analysis = {"goal": "Fix the bug"}
        result = build_analysis_text(analysis)
        assert "Goal: Fix the bug" in result
        assert "Outcomes" not in result


class TestBuildSummaryText:
    """Tests for build_summary_text()."""

    def test_extracts_user_messages(self):
        from ohtv.analysis.embeddings import build_summary_text
        # Use llm_message format which is how real events are structured
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello world"}],
                },
            }
        ]
        result = build_summary_text(events)
        assert "[USER]: Hello world" in result

    def test_extracts_user_messages_string_content(self):
        """Test with simple string content format."""
        from ohtv.analysis.embeddings import build_summary_text
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "content": "Hello world",
            }
        ]
        result = build_summary_text(events)
        assert "[USER]: Hello world" in result

    def test_includes_refs(self):
        from ohtv.analysis.embeddings import build_summary_text
        events = []
        refs = [
            # Note: ref_type values must match what the function expects
            {"ref_type": "pull_request", "url": "https://github.com/org/repo/pull/123"},
            {"ref_type": "repo", "url": "https://github.com/org/repo"},
        ]
        result = build_summary_text(events, refs)
        assert "github.com/org/repo/pull/123" in result
        assert "github.com/org/repo" in result

    def test_handles_empty_events(self):
        from ohtv.analysis.embeddings import build_summary_text
        result = build_summary_text([])
        # Should return empty or minimal string, not crash
        assert result is not None


class TestBuildLeanTranscript:
    """Tests for build_lean_transcript()."""

    def test_includes_user_messages(self):
        from ohtv.analysis.embeddings import build_lean_transcript
        # Use llm_message format for proper extraction
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }
        ]
        result = build_lean_transcript(events)
        assert "[USER]: Hello" in result

    def test_includes_user_messages_string_content(self):
        """Test with simple string content format."""
        from ohtv.analysis.embeddings import build_lean_transcript
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "content": "Hello",
            }
        ]
        result = build_lean_transcript(events)
        assert "[USER]: Hello" in result

    def test_includes_finish_actions(self):
        from ohtv.analysis.embeddings import build_lean_transcript
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "finish",
                "action": {"message": "Task completed"},
            }
        ]
        result = build_lean_transcript(events)
        assert "[FINISH]: Task completed" in result

    def test_includes_think_actions(self):
        from ohtv.analysis.embeddings import build_lean_transcript
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "think",
                "action": {"thought": "Let me think about this"},
            }
        ]
        result = build_lean_transcript(events)
        assert "[THINKING]: Let me think about this" in result

    def test_truncates_long_messages(self):
        from ohtv.analysis.embeddings import build_lean_transcript
        long_message = "x" * 3000
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "finish",
                "action": {"message": long_message},
            }
        ]
        result = build_lean_transcript(events)
        assert len(result) < 3000
        assert "..." in result


class TestBuildConversationTexts:
    """Tests for build_conversation_texts()."""

    def test_builds_all_components(self):
        from ohtv.analysis.embeddings import build_conversation_texts
        # Use llm_message format for proper extraction
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }
        ]
        analysis = {"goal": "Test goal"}
        refs = [{"ref_type": "repo", "url": "https://github.com/org/repo"}]

        result = build_conversation_texts(events, analysis, refs)

        assert result.analysis_text is not None
        assert "Test goal" in result.analysis_text
        assert result.summary_text is not None
        assert "[USER]: Hello" in result.summary_text

    def test_handles_no_analysis(self):
        from ohtv.analysis.embeddings import build_conversation_texts
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "content": "Hello",  # Use simple string format
            }
        ]
        result = build_conversation_texts(events, analysis=None, refs=None)
        assert result.analysis_text is None
        assert result.summary_text is not None


class TestChunkText:
    """Tests for chunk_text()."""

    def test_chunks_long_text_with_paragraphs(self):
        """Test chunking of text with paragraph structure."""
        from ohtv.analysis.embeddings import chunk_text
        # Create text with many paragraphs (chunking is paragraph-based)
        paragraphs = [f"This is paragraph number {i}. " * 20 for i in range(50)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.chunk_index >= 0
            assert len(chunk.text) > 0

    def test_chunks_large_paragraph_with_sentences(self):
        """Test chunking of a single large paragraph with sentences."""
        from ohtv.analysis.embeddings import chunk_text
        # Create a single paragraph with many sentences
        sentences = ["This is sentence number %d." % i for i in range(500)]
        text = " ".join(sentences)
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.chunk_index >= 0
            assert len(chunk.text) > 0

    def test_returns_single_chunk_for_short_text(self):
        from ohtv.analysis.embeddings import chunk_text
        text = "short text"
        chunks = chunk_text(text, chunk_size=1000, overlap=100)
        # Short text should produce at most one chunk
        assert len(chunks) <= 1

    def test_handles_empty_text(self):
        from ohtv.analysis.embeddings import chunk_text
        chunks = chunk_text("")
        assert chunks == []


class TestEmbeddingStats:
    """Tests for EmbeddingStats dataclass."""

    def test_default_values(self):
        from ohtv.analysis.embeddings import EmbeddingStats
        stats = EmbeddingStats(conversation_id="test-123")
        assert stats.conversation_id == "test-123"
        assert stats.analysis_tokens == 0
        assert stats.summary_tokens == 0
        assert stats.content_tokens == 0
        assert stats.content_chunks == 0
        assert stats.total_tokens == 0
        assert stats.embeddings_created == 0


class TestEmbeddingResult:
    """Tests for EmbeddingResult dataclass."""

    def test_creation(self):
        from ohtv.analysis.embeddings import EmbeddingResult
        result = EmbeddingResult(
            embedding=[0.1, 0.2, 0.3],
            token_count=10,
            model="test-model",
            dimensions=3,
        )
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.token_count == 10
        assert result.model == "test-model"
        assert result.dimensions == 3


class TestConversationTexts:
    """Tests for ConversationTexts dataclass."""

    def test_default_values(self):
        from ohtv.analysis.embeddings import ConversationTexts
        texts = ConversationTexts()
        assert texts.analysis_text is None
        assert texts.summary_text is None
        assert texts.content_chunks == []


class TestTextChunk:
    """Tests for TextChunk dataclass."""

    def test_creation(self):
        from ohtv.analysis.embeddings import TextChunk
        chunk = TextChunk(text="hello", chunk_index=0, estimated_tokens=5)
        assert chunk.text == "hello"
        assert chunk.chunk_index == 0
        assert chunk.estimated_tokens == 5


class TestCheckEmbeddingStatus:
    """Tests for check_embedding_status()."""

    def test_returns_dict_of_statuses(self, db_conn):
        from ohtv.analysis.embeddings import check_embedding_status
        from ohtv.db.stores import ConversationStore, EmbeddingStore
        from ohtv.db.models import Conversation

        # Create conversations
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(Conversation(id="conv-1", location="/test/conv-1"))
        conv_store.upsert(Conversation(id="conv-2", location="/test/conv-2"))

        # Add embedding for conv-1 only
        embed_store = EmbeddingStore(db_conn)
        embed_store.upsert(
            "conv-1", [0.1, 0.2], "test-model",
            embed_type="summary", token_count=10
        )
        db_conn.commit()

        result = check_embedding_status(["conv-1", "conv-2", "conv-3"], db_conn)
        assert result["conv-1"] is True
        assert result["conv-2"] is False
        assert result["conv-3"] is False


class TestCheckEmbeddingTypes:
    """Tests for check_embedding_types()."""

    def test_returns_type_existence(self, db_conn):
        from ohtv.analysis.embeddings import check_embedding_types
        from ohtv.db.stores import ConversationStore, EmbeddingStore
        from ohtv.db.models import Conversation

        # Create conversation
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(Conversation(id="conv-1", location="/test/conv-1"))

        # Add only analysis and summary embeddings
        embed_store = EmbeddingStore(db_conn)
        embed_store.upsert(
            "conv-1", [0.1, 0.2], "test-model",
            embed_type="analysis", token_count=10
        )
        embed_store.upsert(
            "conv-1", [0.1, 0.2], "test-model",
            embed_type="summary", token_count=10
        )
        db_conn.commit()

        result = check_embedding_types("conv-1", db_conn)
        assert result["analysis"] is True
        assert result["summary"] is True
        assert result["content"] is False


class TestEmbedConversationFull:
    """Tests for embed_conversation_full().
    
    This function orchestrates the full embedding process and is the main
    entry point for creating conversation embeddings.
    """

    def test_embed_conversation_full_with_refs_provided(self, db_conn, tmp_path):
        """Test embed_conversation_full when refs are explicitly provided."""
        from ohtv.analysis.embeddings import embed_conversation_full
        from ohtv.db.stores import ConversationStore
        from ohtv.db.models import Conversation
        from unittest.mock import patch, MagicMock

        # Create conversation directory with events
        conv_id = "test-conv-123"
        conv_dir = tmp_path / conv_id
        conv_dir.mkdir()
        events_dir = conv_dir / "events"
        events_dir.mkdir()

        # Create a simple event file
        event_data = {
            "kind": "MessageEvent",
            "source": "user",
            "content": "Hello world",
        }
        (events_dir / "event-001.json").write_text(json.dumps(event_data))

        # Register conversation in database
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(Conversation(id=conv_id, location=str(conv_dir)))
        db_conn.commit()

        # Mock get_embedding to avoid actual API calls
        mock_result = MagicMock()
        mock_result.embedding = [0.1, 0.2, 0.3]
        mock_result.token_count = 10
        mock_result.model = "test-model"

        with patch("ohtv.analysis.embeddings.client.get_embedding", return_value=mock_result):
            stats = embed_conversation_full(
                conv_dir=conv_dir,
                conn=db_conn,
                model="test-model",
                refs=[],
            )

        assert stats.conversation_id == conv_id
        assert stats.embeddings_created >= 1

    def test_embed_conversation_full_loads_refs_from_database(self, db_conn, tmp_path):
        """Test embed_conversation_full loads refs from DB when not provided."""
        from ohtv.analysis.embeddings import embed_conversation_full
        from ohtv.db.stores import ConversationStore, LinkStore, ReferenceStore
        from ohtv.db.models import Conversation, Reference, RefType, LinkType
        from unittest.mock import patch, MagicMock

        # Create conversation directory with events
        conv_id = "test-conv-789"
        conv_dir = tmp_path / conv_id
        conv_dir.mkdir()
        events_dir = conv_dir / "events"
        events_dir.mkdir()

        event_data = {
            "kind": "MessageEvent",
            "source": "user",
            "content": "Hello world",
        }
        (events_dir / "event-001.json").write_text(json.dumps(event_data))

        # Set up database with conversation and refs
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(Conversation(id=conv_id, location=str(conv_dir)))

        ref_store = ReferenceStore(db_conn)
        ref_id = ref_store.upsert(Reference(
            id=None,  # Auto-generated
            ref_type=RefType.PR,
            url="https://github.com/org/repo/pull/123",
            fqn="org/repo#123",
            display_name="repo #123",
        ))

        link_store = LinkStore(db_conn)
        link_store.link_ref(conv_id, ref_id, LinkType.READ)
        db_conn.commit()

        # Mock get_embedding
        mock_result = MagicMock()
        mock_result.embedding = [0.1, 0.2, 0.3]
        mock_result.token_count = 10
        mock_result.model = "test-model"

        with patch("ohtv.analysis.embeddings.client.get_embedding", return_value=mock_result):
            stats = embed_conversation_full(
                conv_dir=conv_dir,
                conn=db_conn,
                model="test-model",
                refs=None,  # Should load from database
            )

        assert stats.conversation_id == conv_id
        assert stats.embeddings_created >= 1

    def test_embed_conversation_full_returns_stats_for_empty_conversation(self, db_conn, tmp_path):
        """Test that embed_conversation_full handles empty conversations gracefully."""
        from ohtv.analysis.embeddings import embed_conversation_full

        conv_id = "empty-conv"
        conv_dir = tmp_path / conv_id
        conv_dir.mkdir()
        events_dir = conv_dir / "events"
        events_dir.mkdir()

        stats = embed_conversation_full(
            conv_dir=conv_dir,
            conn=db_conn,
            model="test-model",
            refs=[],
        )

        assert stats.conversation_id == conv_id
        assert stats.embeddings_created == 0
        assert stats.total_tokens == 0


# Fixtures
@pytest.fixture
def db_conn():
    """Fresh in-memory database with migrations applied."""
    import sqlite3
    from ohtv.db import migrate

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_events():
    """Sample conversation events for testing."""
    return [
        {
            "kind": "MessageEvent",
            "source": "user",
            "content": [{"type": "text", "text": "Please fix the bug in main.py"}],
        },
        {
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {"command": "view", "path": "/project/main.py"},
        },
        {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "pytest tests/"},
        },
        {
            "kind": "ActionEvent",
            "tool_name": "finish",
            "action": {"message": "Fixed the bug and all tests pass."},
        },
    ]


@pytest.fixture
def sample_analysis():
    """Sample cached analysis for testing."""
    return {
        "goal": "Fix the bug in main.py",
        "primary_outcomes": ["Bug fixed", "Tests passing"],
        "secondary_outcomes": ["Code refactored"],
        "tags": ["bugfix", "python"],
    }
