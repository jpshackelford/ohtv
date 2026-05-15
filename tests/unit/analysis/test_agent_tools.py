"""Tests for the agent tools module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.agent_tools import (
    GetRefsAction,
    GetRefsExecutor,
    GetRefsObservation,
    GetRefsTool,
    SearchConversationsAction,
    SearchConversationsExecutor,
    SearchConversationsObservation,
    SearchConversationsTool,
    ShowConversationAction,
    ShowConversationExecutor,
    ShowConversationObservation,
    ShowConversationTool,
)


class TestShowConversationAction:
    """Tests for ShowConversationAction."""

    def test_create_action(self):
        """Test creating a ShowConversationAction."""
        action = ShowConversationAction(
            conversation_id="abc12345",
            show_details=True,
            max_messages=100,
        )
        assert action.conversation_id == "abc12345"
        assert action.show_details is True
        assert action.max_messages == 100

    def test_action_defaults(self):
        """Test default values for ShowConversationAction."""
        action = ShowConversationAction(conversation_id="test123")
        assert action.show_details is False
        assert action.max_messages == 50


class TestShowConversationObservation:
    """Tests for ShowConversationObservation."""

    def test_create_observation(self):
        """Test creating a ShowConversationObservation."""
        obs = ShowConversationObservation(
            conversation_id="abc12345",
            title="Test Conversation",
            message_count=10,
            transcript="[USER]: Hello\n\n[ASSISTANT]: Hi there",
        )
        assert obs.conversation_id == "abc12345"
        assert obs.title == "Test Conversation"
        assert obs.message_count == 10
        assert "Hello" in obs.transcript
        assert obs.error is None

    def test_observation_with_error(self):
        """Test observation with error."""
        obs = ShowConversationObservation(
            conversation_id="notfound",
            title=None,
            message_count=0,
            transcript="",
            error="Conversation not found: notfound",
        )
        assert obs.error is not None
        assert "not found" in obs.error


class TestShowConversationExecutor:
    """Tests for ShowConversationExecutor."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_conv_store = MagicMock()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_conversation_not_found(self):
        """Test when conversation is not found."""
        executor = ShowConversationExecutor(
            conv_store=self.mock_conv_store,
            conversation_dirs=[self.temp_dir],
        )
        action = ShowConversationAction(conversation_id="notfound123")
        result = executor(action)

        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_find_conversation_by_prefix(self):
        """Test finding conversation by prefix."""
        # Create a test conversation directory
        conv_id = "abc123def456789"
        conv_dir = Path(self.temp_dir) / conv_id
        conv_dir.mkdir()

        # Create events directory with a simple event
        events_dir = conv_dir / "events"
        events_dir.mkdir()
        event = {
            "kind": "MessageEvent",
            "source": "user",
            "llm_message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
        with open(events_dir / "0001.json", "w") as f:
            json.dump(event, f)

        # Mock conversation store
        mock_conv = MagicMock()
        mock_conv.title = "Test Title"
        self.mock_conv_store.get.return_value = mock_conv

        executor = ShowConversationExecutor(
            conv_store=self.mock_conv_store,
            conversation_dirs=[self.temp_dir],
        )
        action = ShowConversationAction(conversation_id="abc123")
        result = executor(action)

        assert result.error is None
        assert result.conversation_id == conv_id
        assert result.title == "Test Title"
        assert result.message_count == 1
        assert "Hello world" in result.transcript


class TestSearchConversationsAction:
    """Tests for SearchConversationsAction."""

    def test_create_action(self):
        """Test creating a SearchConversationsAction."""
        action = SearchConversationsAction(
            query="authentication bug",
            max_results=10,
        )
        assert action.query == "authentication bug"
        assert action.max_results == 10

    def test_action_defaults(self):
        """Test default values for SearchConversationsAction."""
        action = SearchConversationsAction(query="test query")
        assert action.max_results == 5


class TestSearchConversationsObservation:
    """Tests for SearchConversationsObservation."""

    def test_create_observation(self):
        """Test creating a SearchConversationsObservation."""
        obs = SearchConversationsObservation(
            query="test",
            result_count=2,
            results="- [abc123] Test (2024-01-01)\n- [def456] Another (2024-01-02)",
        )
        assert obs.query == "test"
        assert obs.result_count == 2
        assert "abc123" in obs.results


class TestSearchConversationsExecutor:
    """Tests for SearchConversationsExecutor."""

    def test_no_results(self):
        """Test search with no results."""
        mock_embed_store = MagicMock()
        mock_embed_store.search_conversations.return_value = []
        mock_conv_store = MagicMock()

        executor = SearchConversationsExecutor(
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        action = SearchConversationsAction(query="nonexistent")
        result = executor(action)

        assert result.result_count == 0
        assert "No matching" in result.results

    def test_search_with_results(self):
        """Test search with results."""
        from datetime import datetime
        
        mock_embed_store = MagicMock()
        mock_result = MagicMock()
        mock_result.conversation_id = "abc12345"
        mock_result.score = 0.85
        mock_embed_store.search_conversations.return_value = [mock_result]

        mock_conv_store = MagicMock()
        mock_conv = MagicMock()
        mock_conv.title = "Test Conversation"
        mock_conv.created_at = datetime(2024, 1, 15)
        mock_conv.summary = "This is a test summary"
        mock_conv_store.get.return_value = mock_conv

        executor = SearchConversationsExecutor(
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        action = SearchConversationsAction(query="test")
        result = executor(action)

        assert result.result_count == 1
        assert "abc12345" in result.results
        assert "Test Conversation" in result.results
        assert "0.850" in result.results


class TestGetRefsAction:
    """Tests for GetRefsAction."""

    def test_create_action(self):
        """Test creating a GetRefsAction."""
        action = GetRefsAction(conversation_id="abc12345")
        assert action.conversation_id == "abc12345"


class TestGetRefsObservation:
    """Tests for GetRefsObservation."""

    def test_create_observation(self):
        """Test creating a GetRefsObservation."""
        obs = GetRefsObservation(
            conversation_id="abc12345",
            refs_summary="Repositories:\n  - owner/repo (read)\n\nPull Requests:\n  - owner/repo#42 (write)",
        )
        assert obs.conversation_id == "abc12345"
        assert "owner/repo" in obs.refs_summary
        assert obs.error is None


class TestGetRefsExecutor:
    """Tests for GetRefsExecutor."""

    def test_no_refs(self):
        """Test when conversation has no refs."""
        mock_link_store = MagicMock()
        mock_link_store.get_repos_for_conversation.return_value = []
        mock_link_store.get_refs_for_conversation.return_value = []
        mock_ref_store = MagicMock()
        mock_repo_store = MagicMock()

        executor = GetRefsExecutor(
            link_store=mock_link_store,
            ref_store=mock_ref_store,
            repo_store=mock_repo_store,
        )
        action = GetRefsAction(conversation_id="abc12345")
        result = executor(action)

        assert "No git references" in result.refs_summary

    def test_with_refs(self):
        """Test when conversation has refs."""
        from ohtv.db.models import LinkType, RefType

        mock_link_store = MagicMock()
        mock_link_store.get_repos_for_conversation.return_value = [(1, LinkType.READ)]
        mock_link_store.get_refs_for_conversation.return_value = [(2, LinkType.WRITE)]

        mock_repo_store = MagicMock()
        mock_repo = MagicMock()
        mock_repo.fqn = "owner/repo"
        mock_repo_store.get_by_id.return_value = mock_repo

        mock_ref_store = MagicMock()
        mock_ref = MagicMock()
        mock_ref.fqn = "owner/repo#42"
        mock_ref.ref_type = RefType.PR
        mock_ref.url = "https://github.com/owner/repo/pull/42"
        mock_ref_store.get_by_id.return_value = mock_ref

        executor = GetRefsExecutor(
            link_store=mock_link_store,
            ref_store=mock_ref_store,
            repo_store=mock_repo_store,
        )
        action = GetRefsAction(conversation_id="abc12345")
        result = executor(action)

        assert "owner/repo" in result.refs_summary
        assert "Pull Requests" in result.refs_summary


class TestToolCreation:
    """Tests for tool creation methods."""

    def test_show_conversation_tool_create(self):
        """Test ShowConversationTool.create()."""
        mock_conv_store = MagicMock()
        tools = ShowConversationTool.create(
            conv_store=mock_conv_store,
            conversation_dirs=["/tmp/convs"],
        )
        assert len(tools) == 1
        assert tools[0].name == "show_conversation"
        assert tools[0].executor is not None

    def test_show_conversation_tool_missing_store(self):
        """Test ShowConversationTool.create() without conv_store."""
        with pytest.raises(ValueError, match="conv_store is required"):
            ShowConversationTool.create()

    def test_search_conversations_tool_create(self):
        """Test SearchConversationsTool.create()."""
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        tools = SearchConversationsTool.create(
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        assert len(tools) == 1
        assert tools[0].name == "search_conversations"

    def test_get_refs_tool_create(self):
        """Test GetRefsTool.create()."""
        mock_link_store = MagicMock()
        mock_ref_store = MagicMock()
        mock_repo_store = MagicMock()
        tools = GetRefsTool.create(
            link_store=mock_link_store,
            ref_store=mock_ref_store,
            repo_store=mock_repo_store,
        )
        assert len(tools) == 1
        assert tools[0].name == "get_refs"

    def test_get_refs_tool_missing_stores(self):
        """Test GetRefsTool.create() without required stores."""
        with pytest.raises(ValueError, match="link_store is required"):
            GetRefsTool.create()
