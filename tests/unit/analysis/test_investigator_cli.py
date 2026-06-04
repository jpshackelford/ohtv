"""Tests for the prompt-cookbook (CLI-mode) investigator (Issue #161)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.investigator import InvestigationResult
from ohtv.analysis.investigator_cli import (
    InvestigationAgentCli,
    RunOhtvAction,
    RunOhtvExecutor,
    RunOhtvObservation,
    RunOhtvTool,
)


@pytest.fixture(autouse=True)
def _llm_api_key(monkeypatch):
    """Provide a dummy LLM_API_KEY so InvestigationAgentCli.__init__ succeeds."""
    monkeypatch.setenv("LLM_API_KEY", "test-key")


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_mode_field_defaults_to_tools_for_backcompat(self):
        """InvestigationResult.mode defaults to 'tools' so legacy callers
        don't have to update their constructors."""
        r = InvestigationResult(
            final_answer="x",
            initial_answer="y",
            investigation_steps=[],
            conversations_examined=set(),
            total_iterations=0,
            total_cost=0.0,
            total_tokens=0,
            model="m",
            elapsed_seconds=0.0,
        )
        assert r.mode == "tools"

    def test_mode_can_be_set_to_cli(self):
        r = InvestigationResult(
            final_answer="x",
            initial_answer="y",
            investigation_steps=[],
            conversations_examined=set(),
            total_iterations=0,
            total_cost=0.0,
            total_tokens=0,
            model="m",
            elapsed_seconds=0.0,
            mode="cli",
        )
        assert r.mode == "cli"


# ---------------------------------------------------------------------------
# Tool definition shape
# ---------------------------------------------------------------------------


class TestRunOhtvTool:
    def test_tool_create_returns_single_tool(self):
        tools = RunOhtvTool.create()
        assert len(tools) == 1
        assert tools[0].name == "run_ohtv"

    def test_executor_returns_observation(self):
        executor = RunOhtvExecutor()
        # Use a non-allow-listed argv so we don't actually invoke ohtv;
        # the runner rejects without calling Click.
        obs = executor(RunOhtvAction(argv=["bogus"]))
        assert isinstance(obs, RunOhtvObservation)
        assert obs.rejected is True
        assert obs.rejection_reason == "not_in_allow_list"

    def test_executor_catches_exceptions(self):
        executor = RunOhtvExecutor()
        with patch(
            "ohtv.analysis.investigator_cli.run_ohtv",
            side_effect=RuntimeError("boom"),
        ):
            obs = executor(RunOhtvAction(argv=["show", "abc"]))
        # Error is surfaced on the observation rather than propagated.
        assert obs.error is not None
        assert "boom" in obs.error

    def test_observation_to_text_handles_rejection(self):
        obs = RunOhtvObservation(
            argv=["sync"],
            stderr="not allowed",
            exit_code=2,
            rejected=True,
            rejection_reason="blocked_command",
        )
        assert "REJECTED" in obs.to_text()
        assert "blocked_command" in obs.to_text()


# ---------------------------------------------------------------------------
# Investigator construction + mode banner
# ---------------------------------------------------------------------------


class TestInvestigationAgentCli:
    def test_init_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="LLM_API_KEY"):
            InvestigationAgentCli(model="gpt-4o-mini")

    def test_default_command_count_cap_is_3x_iterations(self):
        agent = InvestigationAgentCli(model="m", max_iterations=4)
        assert agent.command_count_cap == 12

    def test_custom_command_count_cap(self):
        agent = InvestigationAgentCli(
            model="m", max_iterations=5, command_count_cap=50
        )
        assert agent.command_count_cap == 50

    def test_create_tools_returns_run_ohtv_only(self):
        agent = InvestigationAgentCli(model="m")
        tools = agent._create_tools()
        assert len(tools) == 1
        assert tools[0].name == "run_ohtv"

    def test_investigate_returns_mode_cli(self):
        """End-to-end: investigate() stamps mode='cli' on the result.

        We mock out the LLM loop and just verify the result shape.
        """
        agent = InvestigationAgentCli(model="gpt-4o-mini", max_iterations=1)

        rag_answer = MagicMock()
        rag_answer.answer = "Initial RAG answer"
        rag_answer.source_conversation_ids = set()
        rag_answer.context_chunks = []

        # Replace _run_investigation_loop so we don't call the LLM.
        agent._run_investigation_loop = MagicMock(  # type: ignore[method-assign]
            return_value={
                "answer": "Final answer",
                "total_tokens": 100,
                "total_cost": 0.005,
                "finished": True,
            }
        )

        result = agent.investigate(question="q?", initial_answer=rag_answer)
        assert isinstance(result, InvestigationResult)
        assert result.mode == "cli"
        assert result.final_answer == "Final answer"
        assert result.total_cost == 0.005
        assert result.total_tokens == 100

    def test_investigate_falls_back_to_initial_on_exception(self):
        """Loop exceptions fall back to the initial RAG answer.

        Same behaviour as the legacy investigator — preserves the
        contract that `--agent` never makes the answer worse than the
        single-turn RAG path.
        """
        agent = InvestigationAgentCli(model="gpt-4o-mini")

        rag_answer = MagicMock()
        rag_answer.answer = "Initial answer"
        rag_answer.source_conversation_ids = set()
        rag_answer.context_chunks = []

        agent._run_investigation_loop = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("LLM died")
        )

        result = agent.investigate(question="q?", initial_answer=rag_answer)
        assert result.mode == "cli"
        assert result.error is not None
        assert result.final_answer == "Initial answer"


# ---------------------------------------------------------------------------
# argv-based conversations_examined extraction
# ---------------------------------------------------------------------------


class TestConversationsExaminedFromArgv:
    """The CLI mode populates ``conversations_examined`` by parsing IDs
    out of argv (the runner doesn't know the conv-store schema).

    The legacy tools mode does the same via tool observation hooks; both
    fields must have the same shape so #162 telemetry can compare paths.
    """

    def test_process_tool_call_extracts_ids_from_argv(self):
        from ohtv.analysis.investigator_cli import RunOhtvObservation

        agent = InvestigationAgentCli(model="m")
        conversations_examined: set[str] = set()

        # Build a fake tool call + tool map. The tool returns an
        # observation directly so we don't hit the real CLI.
        fake_tool = MagicMock()
        fake_tool.executor = True
        fake_tool.action_from_arguments = MagicMock(
            return_value=RunOhtvAction(argv=["show", "abc12345", "-F", "json"])
        )
        fake_tool.__call__ = MagicMock(
            return_value=RunOhtvObservation(
                argv=["show", "abc12345", "-F", "json"],
                stdout="...",
                exit_code=0,
            )
        )
        # ``observation = tool(action)`` — make the tool callable.
        fake_tool.return_value = RunOhtvObservation(
            argv=["show", "abc12345", "-F", "json"],
            stdout="conversation content",
            exit_code=0,
        )

        tool_call = MagicMock()
        tool_call.name = "run_ohtv"
        tool_call.arguments = {"argv": ["show", "abc12345", "-F", "json"]}

        agent._process_tool_call(
            tool_call,
            {"run_ohtv": fake_tool},
            conversations_examined,
        )

        assert "abc12345" in conversations_examined


# ---------------------------------------------------------------------------
# Helper: show_tool_progress doesn't crash on edge cases
# ---------------------------------------------------------------------------


class TestProgressHelpers:
    def test_show_tool_progress_handles_run_ohtv(self, capsys):
        agent = InvestigationAgentCli(model="m")
        agent._show_tool_progress("run_ohtv", {"argv": ["show", "abc"]})
        # No exception, that's the contract.

    def test_show_tool_progress_handles_finish(self):
        agent = InvestigationAgentCli(model="m")
        agent._show_tool_progress("finish", {})

    def test_show_tool_progress_handles_string_args(self):
        agent = InvestigationAgentCli(model="m")
        agent._show_tool_progress("run_ohtv", '{"argv": ["show", "abc"]}')

    def test_show_tool_progress_handles_malformed_args(self):
        agent = InvestigationAgentCli(model="m")
        agent._show_tool_progress("run_ohtv", "not valid json")

    def test_synthesize_partial_findings_with_no_examined(self):
        agent = InvestigationAgentCli(model="m")
        rag = MagicMock()
        rag.answer = "initial"
        text = agent._synthesize_partial_findings(rag, set())
        assert "initial" in text
        assert "limit" in text.lower()

    def test_synthesize_partial_findings_with_examined(self):
        agent = InvestigationAgentCli(model="m")
        rag = MagicMock()
        rag.answer = "initial"
        text = agent._synthesize_partial_findings(rag, {"abc12345"})
        assert "abc12345" in text
        assert "1 additional conversation" in text
