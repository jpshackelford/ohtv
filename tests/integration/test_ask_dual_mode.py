"""Integration test: same question routed through both investigation modes.

Issue #161 AC: "Same question routed through both modes produces non-empty
answers and writes both ``InvestigationResult``s (telemetry hookup lives
in the upcoming telemetry issue, but the data shape must be in place here)."

The LLM is mocked so we don't hit a real API; what we're testing is that
both code paths return an ``InvestigationResult`` of the right shape so
#162 can stamp telemetry on either path uniformly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.investigator import InvestigationResult


@pytest.fixture(autouse=True)
def _llm_api_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")


def _make_rag_answer():
    """Build a minimal RAG answer suitable for both investigators."""
    rag = MagicMock()
    rag.answer = "The initial RAG answer mentions conversation abc12345."
    rag.source_conversation_ids = {"abc12345"}
    rag.context_chunks = []
    return rag


def _fake_llm_completion_no_tool_calls(*args, **kwargs):
    """Fake LLM response: no tool calls, direct text response.

    Mimics the simplest investigation path — the LLM looks at the
    initial answer and decides nothing more needs to be done.
    """
    response = MagicMock()
    response.metrics = MagicMock()
    response.metrics.accumulated_token_usage = MagicMock(
        prompt_tokens=10, completion_tokens=20
    )
    response.metrics.accumulated_cost = 0.0001
    response.message = MagicMock()
    response.message.tool_calls = []
    # Text content with one chunk
    text_chunk = MagicMock()
    text_chunk.text = "Final synthesized answer."
    response.message.content = [text_chunk]
    return response


class TestDualMode:
    def test_cli_mode_returns_correct_shape(self):
        """--agent path returns InvestigationResult(mode='cli')."""
        from ohtv.analysis.investigator_cli import InvestigationAgentCli

        with patch(
            "openhands.sdk.llm.LLM.completion",
            side_effect=_fake_llm_completion_no_tool_calls,
        ):
            agent = InvestigationAgentCli(model="gpt-4o-mini", max_iterations=1)
            result = agent.investigate(
                question="What did we work on yesterday?",
                initial_answer=_make_rag_answer(),
            )

        assert isinstance(result, InvestigationResult)
        assert result.mode == "cli"
        assert result.final_answer  # non-empty
        assert result.error is None
        assert result.total_tokens > 0
        assert result.total_cost >= 0.0
        assert result.model == "gpt-4o-mini"

    def test_tools_mode_returns_correct_shape(self):
        """--agent-tools path returns InvestigationResult(mode='tools')."""
        from unittest.mock import MagicMock as MM

        from ohtv.analysis.investigator import InvestigationAgent

        # InvestigationAgent needs stores; use mocks.
        embed_store = MM()
        conv_store = MM()

        with patch(
            "openhands.sdk.llm.LLM.completion",
            side_effect=_fake_llm_completion_no_tool_calls,
        ):
            agent = InvestigationAgent(
                model="gpt-4o-mini",
                embed_store=embed_store,
                conv_store=conv_store,
                max_iterations=1,
            )
            result = agent.investigate(
                question="What did we work on yesterday?",
                initial_answer=_make_rag_answer(),
            )

        assert isinstance(result, InvestigationResult)
        assert result.mode == "tools"
        assert result.final_answer
        assert result.error is None
        assert result.total_tokens > 0

    def test_both_modes_share_identical_field_shape(self):
        """Field-by-field comparison: every InvestigationResult field
        is present and has the same type across modes. This is the
        primitive that #162 telemetry depends on."""
        from unittest.mock import MagicMock as MM

        from ohtv.analysis.investigator import InvestigationAgent
        from ohtv.analysis.investigator_cli import InvestigationAgentCli

        with patch(
            "openhands.sdk.llm.LLM.completion",
            side_effect=_fake_llm_completion_no_tool_calls,
        ):
            cli_result = InvestigationAgentCli(
                model="gpt-4o-mini", max_iterations=1
            ).investigate("q?", _make_rag_answer())
            tools_result = InvestigationAgent(
                model="gpt-4o-mini",
                embed_store=MM(),
                conv_store=MM(),
                max_iterations=1,
            ).investigate("q?", _make_rag_answer())

        # Both dataclasses have the same field set.
        from dataclasses import fields

        cli_field_names = {f.name for f in fields(cli_result)}
        tools_field_names = {f.name for f in fields(tools_result)}
        assert cli_field_names == tools_field_names
        # And the only field that differs by design is ``mode``.
        assert cli_result.mode == "cli"
        assert tools_result.mode == "tools"
