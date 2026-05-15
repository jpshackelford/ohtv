"""Tests for the investigator module."""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.investigator import (
    InvestigationResult,
    format_initial_context,
    get_investigation_system_prompt,
)


class TestInvestigationResult:
    """Tests for InvestigationResult dataclass."""

    def test_create_result(self):
        """Test creating an InvestigationResult."""
        result = InvestigationResult(
            final_answer="The bug was fixed by updating the auth module.",
            initial_answer="There was a bug in auth.",
            investigation_steps=["Called show_conversation: abc123"],
            conversations_examined={"abc123", "def456"},
            total_iterations=2,
            total_cost=0.0123,
            total_tokens=1500,
            model="gpt-4o-mini",
            elapsed_seconds=5.5,
            finished_normally=True,
            error=None,
        )
        assert "bug was fixed" in result.final_answer
        assert result.total_iterations == 2
        assert len(result.conversations_examined) == 2
        assert result.finished_normally is True

    def test_result_with_error(self):
        """Test result with error."""
        result = InvestigationResult(
            final_answer="",
            initial_answer="Initial answer",
            investigation_steps=[],
            conversations_examined=set(),
            total_iterations=0,
            total_cost=0.0,
            total_tokens=0,
            model="gpt-4o-mini",
            elapsed_seconds=0.5,
            finished_normally=False,
            error="LLM API call failed",
        )
        assert result.error is not None
        assert result.finished_normally is False


class TestGetInvestigationSystemPrompt:
    """Tests for get_investigation_system_prompt."""

    def test_prompt_content(self):
        """Test that system prompt contains expected content."""
        prompt = get_investigation_system_prompt()
        
        # Should mention the available tools
        assert "show_conversation" in prompt
        assert "search_conversations" in prompt
        assert "get_refs" in prompt
        
        # Should mention the finish tool
        assert "finish" in prompt
        
        # Should have guidelines
        assert "Guidelines" in prompt


class TestFormatInitialContext:
    """Tests for format_initial_context."""

    def test_basic_formatting(self):
        """Test basic context formatting."""
        # Create mock RAG answer
        mock_answer = MagicMock()
        mock_answer.answer = "The auth bug was fixed."
        mock_answer.source_conversation_ids = {"abc123"}
        mock_answer.context_chunks = []
        
        context = format_initial_context(
            question="How did we fix the auth bug?",
            rag_answer=mock_answer,
        )
        
        assert "How did we fix the auth bug?" in context
        assert "The auth bug was fixed" in context
        assert "Question" in context
        assert "Initial Answer" in context

    def test_formatting_with_sources(self):
        """Test formatting with source chunks."""
        # Create mock source
        mock_source = MagicMock()
        mock_source.title = "Fix auth bug"
        mock_source.summary = "Fixed the authentication issue"
        mock_source.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_source.prs = [MagicMock(fqn="owner/repo#42")]
        mock_source.repos = [MagicMock(fqn="owner/repo")]
        
        mock_chunk = MagicMock()
        mock_chunk.conversation_id = "abc123def456"
        mock_chunk.source = mock_source
        
        mock_answer = MagicMock()
        mock_answer.answer = "The bug was fixed."
        mock_answer.source_conversation_ids = {"abc123def456"}
        mock_answer.context_chunks = [mock_chunk]
        
        context = format_initial_context(
            question="Test question",
            rag_answer=mock_answer,
        )
        
        assert "abc123de" in context  # First 8 chars
        assert "Fix auth bug" in context
        assert "owner/repo#42" in context


class TestInvestigationAgentInit:
    """Tests for InvestigationAgent initialization."""

    def test_missing_api_key(self):
        """Test that missing API key raises error."""
        from ohtv.analysis.investigator import InvestigationAgent
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Ensure LLM_API_KEY is not set
        with patch.dict('os.environ', {'LLM_API_KEY': ''}, clear=False):
            # Remove the key if it exists
            import os
            old_key = os.environ.pop('LLM_API_KEY', None)
            try:
                with pytest.raises(RuntimeError, match="LLM_API_KEY"):
                    InvestigationAgent(
                        model="gpt-4o-mini",
                        embed_store=mock_embed_store,
                        conv_store=mock_conv_store,
                    )
            finally:
                if old_key:
                    os.environ['LLM_API_KEY'] = old_key


class TestInvestigationAgentCreateTools:
    """Tests for InvestigationAgent tool creation."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_create_tools_without_ref_stores(self):
        """Test creating tools without ref stores."""
        from ohtv.analysis.investigator import InvestigationAgent
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            link_store=None,
            ref_store=None,
            repo_store=None,
        )
        
        tools = agent._create_tools()
        
        # Should have show_conversation and search_conversations
        tool_names = [t.name for t in tools]
        assert "show_conversation" in tool_names
        assert "search_conversations" in tool_names
        # get_refs should NOT be included without ref stores
        assert "get_refs" not in tool_names

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_create_tools_with_ref_stores(self):
        """Test creating tools with ref stores."""
        from ohtv.analysis.investigator import InvestigationAgent
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        mock_link_store = MagicMock()
        mock_ref_store = MagicMock()
        mock_repo_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            link_store=mock_link_store,
            ref_store=mock_ref_store,
            repo_store=mock_repo_store,
        )
        
        tools = agent._create_tools()
        
        # Should have all tools including get_refs
        tool_names = [t.name for t in tools]
        assert "show_conversation" in tool_names
        assert "search_conversations" in tool_names
        assert "get_refs" in tool_names


class TestInvestigationAgentInvestigate:
    """Integration tests for InvestigationAgent.investigate() method."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    @patch('ohtv.analysis.investigator.LLM')
    def test_investigate_basic_flow_finishes_immediately(self, mock_llm_class):
        """Test that investigate() completes successfully when LLM calls finish immediately."""
        from ohtv.analysis.investigator import InvestigationAgent
        
        # Set up mock stores
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Create mock LLM response with finish tool call
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "finish"
        mock_tool_call.function.arguments = '{"message": "The auth bug was fixed by updating token validation."}'
        mock_tool_call.id = "call_123"
        
        mock_response = MagicMock()
        mock_response.message.tool_calls = [mock_tool_call]
        mock_response.message.content = None
        mock_response.metrics = MagicMock()
        mock_response.metrics.accumulated_token_usage = MagicMock()
        mock_response.metrics.accumulated_token_usage.prompt_tokens = 100
        mock_response.metrics.accumulated_token_usage.completion_tokens = 50
        mock_response.metrics.accumulated_cost = 0.002
        
        # Configure mock LLM instance
        mock_llm_instance = MagicMock()
        mock_llm_instance.completion.return_value = mock_response
        mock_llm_class.return_value = mock_llm_instance
        
        # Create mock RAG answer
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial answer about auth bug"
        mock_rag_answer.source_conversation_ids = set()
        mock_rag_answer.context_chunks = []
        
        # Create agent and run investigation
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        result = agent.investigate(
            question="How did we fix the auth bug?",
            initial_answer=mock_rag_answer,
        )
        
        # Verify result
        assert result.finished_normally is True
        assert result.total_iterations == 1  # finish tool call counts as 1 step
        assert "token validation" in result.final_answer
        assert result.total_tokens == 150  # 100 + 50
        assert result.total_cost == 0.002
        assert result.error is None
        assert result.initial_answer == "Initial answer about auth bug"
        
        # Verify LLM was called
        mock_llm_instance.completion.assert_called_once()

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    @patch('ohtv.analysis.investigator.LLM')
    def test_investigate_handles_loop_error_gracefully(self, mock_llm_class):
        """Test that investigate() handles LLM errors within the loop gracefully.
        
        Errors within the investigation loop are logged and break the loop,
        but don't bubble up to the outer try/except.
        """
        from ohtv.analysis.investigator import InvestigationAgent
        
        # Set up mock stores
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Configure mock LLM to raise an exception
        mock_llm_instance = MagicMock()
        mock_llm_instance.completion.side_effect = RuntimeError("LLM API error")
        mock_llm_class.return_value = mock_llm_instance
        
        # Create mock RAG answer
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial answer about auth bug"
        mock_rag_answer.source_conversation_ids = set()
        mock_rag_answer.context_chunks = []
        
        # Create agent and run investigation
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        result = agent.investigate(
            question="How did we fix the auth bug?",
            initial_answer=mock_rag_answer,
        )
        
        # Verify the investigation didn't finish normally
        assert result.finished_normally is False
        # Error is logged in investigation_steps, not in error field
        assert any("Error: LLM API error" in step for step in result.investigation_steps)
        # Investigation returned the fallback message (not a real answer)
        assert "iteration limit" in result.final_answer.lower() or "partial findings" in result.final_answer.lower()
