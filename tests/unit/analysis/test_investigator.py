"""Tests for the investigator module."""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.investigator import (
    InvestigationAgent,
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

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_create_tools_with_config_includes_list_conversations(self):
        """Issue #160: When config is provided, list_conversations is registered."""
        from ohtv.analysis.investigator import InvestigationAgent

        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=MagicMock(),
            conv_store=MagicMock(),
            config=MagicMock(),
        )

        tool_names = [t.name for t in agent._create_tools()]
        assert "list_conversations" in tool_names

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_create_tools_without_config_skips_list_conversations(self):
        """When config is missing the new tool is silently omitted."""
        from ohtv.analysis.investigator import InvestigationAgent

        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=MagicMock(),
            conv_store=MagicMock(),
            config=None,
        )

        tool_names = [t.name for t in agent._create_tools()]
        assert "list_conversations" not in tool_names

    def test_system_prompt_mentions_list_conversations(self):
        """The system prompt must teach the agent when to choose browse vs. search."""
        from ohtv.analysis.investigator import get_investigation_system_prompt

        prompt = get_investigation_system_prompt()
        assert "list_conversations" in prompt
        # Must reference the temporal / enumerative cues
        assert "yesterday" in prompt or "temporal" in prompt
        assert "enumerative" in prompt or "list all" in prompt or "every X" in prompt


class TestInvestigationAgentInvestigate:
    """Integration tests for InvestigationAgent.investigate() method."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    @patch('ohtv.analysis.investigator.LLM')
    def test_investigate_basic_flow_finishes_immediately(self, mock_llm_class):
        """Test that investigate() completes successfully when LLM calls finish immediately."""
        from ohtv.analysis.investigator import InvestigationAgent
        from openhands.sdk.llm.message import MessageToolCall
        
        # Set up mock stores
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Create real tool call object with finish tool
        # The tool_call is accessed via .name and .arguments directly (not .function.*)
        finish_tool_call = MessageToolCall(
            id="call_123",
            name="finish",
            arguments='{"message": "The auth bug was fixed by updating token validation."}',
            origin="completion"
        )
        
        mock_response = MagicMock()
        mock_response.message.tool_calls = [finish_tool_call]
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


class TestSynthesizePartialFindings:
    """Tests for InvestigationAgent._synthesize_partial_findings method."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_basic_synthesis(self):
        """Test basic partial findings synthesis."""
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        # Create mock RAG answer
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "The auth bug was fixed by updating token validation."
        
        result = agent._synthesize_partial_findings(
            question="How did we fix the auth bug?",
            initial_answer=mock_rag_answer,
            investigation_steps=["Called show_conversation"],
            conversations_examined=set(),
        )
        
        # Should include the initial answer
        assert "auth bug was fixed" in result
        assert "token validation" in result
        
        # Should note that investigation reached limit
        assert "iteration limit" in result.lower()

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_synthesis_with_examined_conversations(self):
        """Test synthesis includes list of examined conversations."""
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial answer."
        
        result = agent._synthesize_partial_findings(
            question="Test question",
            initial_answer=mock_rag_answer,
            investigation_steps=["Step 1", "Step 2"],
            conversations_examined={"abc123def456", "xyz789ghi"},
        )
        
        # Should mention number of conversations examined
        assert "2 additional conversations" in result
        # Should include truncated IDs (8 chars)
        assert "abc123de" in result
        assert "xyz789gh" in result

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_synthesis_without_examined_conversations(self):
        """Test synthesis when no conversations were examined."""
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial answer only."
        
        result = agent._synthesize_partial_findings(
            question="Test question",
            initial_answer=mock_rag_answer,
            investigation_steps=[],
            conversations_examined=set(),
        )
        
        # Should include initial answer
        assert "Initial answer only" in result
        # Should NOT have the examined conversations section
        assert "additional conversations" not in result
        # Should still note iteration limit
        assert "iteration limit" in result.lower()

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_synthesis_includes_max_steps_hint(self):
        """Test synthesis includes hint about increasing max-steps."""
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Answer."
        
        result = agent._synthesize_partial_findings(
            question="Test",
            initial_answer=mock_rag_answer,
            investigation_steps=[],
            conversations_examined=set(),
        )
        
        # Should suggest increasing max-steps
        assert "--max-steps" in result


class TestShowToolProgress:
    """Tests for InvestigationAgent._show_tool_progress method."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_show_conversation_progress(self):
        """Test progress message for show_conversation tool."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Use a console that captures output
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        agent._show_tool_progress("show_conversation", {"conversation_id": "abc123def456"})
        
        result = output.getvalue()
        assert "📖" in result
        assert "abc123de" in result  # Truncated to 8 chars

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_search_conversations_progress(self):
        """Test progress message for search_conversations tool."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        agent._show_tool_progress("search_conversations", {"query": "auth bug fix"})
        
        result = output.getvalue()
        assert "🔍" in result
        assert "auth bug fix" in result

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_get_refs_progress(self):
        """Test progress message for get_refs tool."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        agent._show_tool_progress("get_refs", {"conversation_id": "xyz789abc"})
        
        result = output.getvalue()
        assert "🔗" in result
        assert "xyz789ab" in result  # Truncated to 8 chars

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_finish_progress(self):
        """Test progress message for finish tool."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        agent._show_tool_progress("finish", {"message": "Done"})
        
        result = output.getvalue()
        assert "✅" in result
        assert "Finalizing" in result

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_unknown_tool_progress(self):
        """Test progress message for unknown tool doesn't throw."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        # Should not raise for unknown tool
        agent._show_tool_progress("unknown_tool", {"foo": "bar"})
        
        result = output.getvalue()
        assert "🔧" in result
        assert "unknown_tool" in result

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_string_arguments_parsed(self):
        """Test that string arguments (JSON) are parsed correctly."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        # Pass arguments as JSON string (as they come from LLM)
        agent._show_tool_progress("show_conversation", '{"conversation_id": "testconv123"}')
        
        result = output.getvalue()
        assert "📖" in result
        assert "testconv" in result

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_invalid_json_handled(self):
        """Test that invalid JSON arguments don't cause errors."""
        from io import StringIO
        from rich.console import Console
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
        )
        
        # Invalid JSON should not throw
        agent._show_tool_progress("show_conversation", "not valid json {")
        
        # Should still produce output (with fallback to "unknown")
        result = output.getvalue()
        assert "📖" in result


class TestAddToolResponse:
    """Tests for InvestigationAgent._add_tool_response method."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    def test_add_tool_response_includes_name(self):
        """Test that _add_tool_response includes the tool name in the response message.
        
        This is required by the SDK - when tool_call_id is set, name must also be set.
        Regression test for: AssertionError: name is required when tool_call_id is not None
        """
        from openhands.sdk.llm.message import MessageToolCall
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        # Create a real tool call object (not a mock, since Message validates types)
        tool_call = MessageToolCall(
            id="call_abc123",
            name="search_conversations",
            arguments='{"query": "test"}',
            origin="completion"
        )
        
        messages = []
        agent._add_tool_response(messages, tool_call, "Search results here")
        
        # Should have 2 messages: assistant with tool_calls, tool with response
        assert len(messages) == 2
        
        # First message should be assistant with tool_calls
        assert messages[0].role == "assistant"
        assert len(messages[0].tool_calls) == 1
        assert messages[0].tool_calls[0].id == "call_abc123"
        
        # Second message should be tool response with both tool_call_id AND name
        assert messages[1].role == "tool"
        # Content is a list of TextContent objects
        assert len(messages[1].content) == 1
        assert messages[1].content[0].text == "Search results here"
        assert messages[1].tool_call_id == "call_abc123"
        assert messages[1].name == "search_conversations"  # This was the missing field!


class TestMultiToolCallBatching:
    """Tests for multi-tool call batching behavior in investigation loop."""

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    @patch('ohtv.analysis.investigator.LLM')
    def test_multiple_tool_calls_processed_before_next_iteration(self, mock_llm_class):
        """Test that multiple tool calls in a single LLM response are all processed.
        
        This test verifies the batching behavior: when the LLM returns multiple tool
        calls in one response, all of them should be processed before the next 
        LLM iteration, ensuring proper message history construction.
        """
        from io import StringIO
        from rich.console import Console
        from openhands.sdk.llm.message import MessageToolCall
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        mock_conv_store.get_title.return_value = "Test Conversation"
        
        output = StringIO()
        console = Console(file=output, force_terminal=True)
        
        # Create tool calls for two different tools
        search_tool_call = MessageToolCall(
            id="call_search_1",
            name="search_conversations",
            arguments='{"query": "auth bug"}',
            origin="completion"
        )
        show_tool_call = MessageToolCall(
            id="call_show_1",
            name="show_conversation",
            arguments='{"conversation_id": "abc123"}',
            origin="completion"
        )
        
        # First response: LLM returns TWO tool calls at once
        first_response = MagicMock()
        first_response.message.tool_calls = [search_tool_call, show_tool_call]
        first_response.message.content = None
        first_response.metrics = MagicMock()
        first_response.metrics.accumulated_token_usage = MagicMock()
        first_response.metrics.accumulated_token_usage.prompt_tokens = 100
        first_response.metrics.accumulated_token_usage.completion_tokens = 50
        first_response.metrics.accumulated_cost = 0.001
        
        # Second response: finish tool
        finish_tool_call = MessageToolCall(
            id="call_finish_1",
            name="finish",
            arguments='{"message": "Found the answer!"}',
            origin="completion"
        )
        second_response = MagicMock()
        second_response.message.tool_calls = [finish_tool_call]
        second_response.message.content = None
        second_response.metrics = MagicMock()
        second_response.metrics.accumulated_token_usage = MagicMock()
        second_response.metrics.accumulated_token_usage.prompt_tokens = 200
        second_response.metrics.accumulated_token_usage.completion_tokens = 30
        second_response.metrics.accumulated_cost = 0.001
        
        # Set up mock LLM to return responses in sequence
        mock_llm_instance = MagicMock()
        mock_llm_instance.completion.side_effect = [first_response, second_response]
        mock_llm_class.return_value = mock_llm_instance
        
        # Create mock RAG answer
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial answer"
        mock_rag_answer.source_conversation_ids = set()
        mock_rag_answer.context_chunks = []
        
        # Create agent with conversation directory
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
            console=console,
            conversation_dirs=["/tmp/test_conversations"],
        )
        
        # Mock the tool execution to return predictable results
        with patch.object(agent, '_process_tool_call') as mock_process:
            def process_side_effect(tool_call, tool_map, conversations_examined):
                if tool_call.name == "search_conversations":
                    return ("Search results for auth bug", None, False)
                elif tool_call.name == "show_conversation":
                    conversations_examined.add("abc123")
                    return ("Conversation content here", None, False)
                elif tool_call.name == "finish":
                    return (None, "Found the answer!", True)
                return ("Unknown tool result", None, False)
            
            mock_process.side_effect = process_side_effect
            
            result = agent.investigate(
                question="How did we fix the auth bug?",
                initial_answer=mock_rag_answer,
            )
        
        # Verify the result
        assert result.finished_normally is True
        assert "Found the answer!" in result.final_answer
        
        # Verify LLM was called exactly twice (once for batch, once for finish)
        assert mock_llm_instance.completion.call_count == 2
        
        # Verify both tool calls from first response were processed
        output_text = output.getvalue()
        assert "🔍" in output_text  # search_conversations progress
        assert "📖" in output_text  # show_conversation progress
        
        # Verify investigation steps include both tool calls
        assert any("search_conversations" in step for step in result.investigation_steps)
        assert any("show_conversation" in step for step in result.investigation_steps)
        
        # Verify the conversation was tracked as examined
        assert "abc123" in result.conversations_examined

    @patch.dict('os.environ', {'LLM_API_KEY': 'test-key'})
    @patch('ohtv.analysis.investigator.LLM')
    def test_batch_tool_calls_message_history_structure(self, mock_llm_class):
        """Test that message history is correctly structured after batch processing.
        
        When multiple tool calls are processed in a batch, the message history
        should contain all tool responses added after processing the batch,
        not interleaved with LLM calls.
        """
        from openhands.sdk.llm.message import MessageToolCall
        
        mock_embed_store = MagicMock()
        mock_conv_store = MagicMock()
        
        # Two tool calls in one response
        tool_call_1 = MessageToolCall(
            id="call_1",
            name="search_conversations",
            arguments='{"query": "test1"}',
            origin="completion"
        )
        tool_call_2 = MessageToolCall(
            id="call_2",
            name="search_conversations", 
            arguments='{"query": "test2"}',
            origin="completion"
        )
        
        # First response with two tool calls
        first_response = MagicMock()
        first_response.message.tool_calls = [tool_call_1, tool_call_2]
        first_response.message.content = None
        first_response.metrics.accumulated_token_usage.prompt_tokens = 100
        first_response.metrics.accumulated_token_usage.completion_tokens = 50
        first_response.metrics.accumulated_cost = 0.001
        
        # Second response finishes
        finish_call = MessageToolCall(
            id="call_finish",
            name="finish",
            arguments='{"message": "Done"}',
            origin="completion"
        )
        second_response = MagicMock()
        second_response.message.tool_calls = [finish_call]
        second_response.message.content = None
        second_response.metrics.accumulated_token_usage.prompt_tokens = 200
        second_response.metrics.accumulated_token_usage.completion_tokens = 30
        second_response.metrics.accumulated_cost = 0.001
        
        mock_llm_instance = MagicMock()
        mock_llm_instance.completion.side_effect = [first_response, second_response]
        mock_llm_class.return_value = mock_llm_instance
        
        mock_rag_answer = MagicMock()
        mock_rag_answer.answer = "Initial"
        mock_rag_answer.source_conversation_ids = set()
        mock_rag_answer.context_chunks = []
        
        agent = InvestigationAgent(
            model="gpt-4o-mini",
            embed_store=mock_embed_store,
            conv_store=mock_conv_store,
        )
        
        with patch.object(agent, '_process_tool_call') as mock_process:
            def process_fn(tc, tm, ce):
                if tc.name == "finish":
                    return (None, "Done", True)
                return (f"Result for {tc.id}", None, False)
            mock_process.side_effect = process_fn
            
            result = agent.investigate(
                question="Test?",
                initial_answer=mock_rag_answer,
            )
        
        # Check that the second LLM call received all tool responses
        # (The first call is the initial, second is after batch processing)
        calls = mock_llm_instance.completion.call_args_list
        assert len(calls) == 2
        
        # The second call should have messages including both tool responses
        second_call_messages = calls[1][0][0]  # First positional arg is messages
        
        # Count tool messages in the history sent to second call
        tool_messages = [m for m in second_call_messages if m.role == "tool"]
        # Should have 2 tool response messages (one for each batched call)
        assert len(tool_messages) == 2
