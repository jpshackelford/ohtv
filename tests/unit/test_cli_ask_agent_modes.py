"""CLI dispatch tests for ``ohtv ask`` agent modes (Issue #161).

Covers the mutual-exclusion behaviour, the mode banner, and the
``--max-steps 0`` short-circuit. The actual investigation loops are
exercised in the per-investigator unit tests; here we just verify that
``cli.ask`` routes correctly.
"""

from __future__ import annotations


import pytest
from click.testing import CliRunner

from ohtv.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestMutualExclusion:
    def test_both_agent_flags_raise_usage_error(self, runner):
        result = runner.invoke(main, ["ask", "q?", "--agent", "--agent-tools"])
        # UsageError → exit code 2
        assert result.exit_code == 2
        # Click renders UsageError text on stderr
        output = (result.stdout or "") + (result.stderr or "")
        assert "mutually exclusive" in output

    def test_help_lists_both_flags(self, runner):
        result = runner.invoke(main, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--agent" in result.stdout
        assert "--agent-tools" in result.stdout


class TestAskDispatch:
    """Smoke-level routing tests.

    We don't run the investigation loop — we just verify the ``ask``
    handler accepts both flags and renders the right help output.
    """

    def test_agent_flag_accepted(self, runner):
        """--agent on its own passes Click parsing (DB error is fine)."""
        result = runner.invoke(main, ["ask", "q", "--agent", "--max-steps", "0"])
        # Either succeeds or fails with a "no database" / "no embeddings"
        # message — what we're verifying is that Click parses --agent
        # without complaining.
        output = (result.stdout or "") + (result.stderr or "")
        assert "mutually exclusive" not in output
        assert "No such option" not in output

    def test_agent_tools_flag_accepted(self, runner):
        """--agent-tools on its own passes Click parsing."""
        result = runner.invoke(
            main, ["ask", "q", "--agent-tools", "--max-steps", "0"]
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert "mutually exclusive" not in output
        assert "No such option" not in output


class TestAgentDeprecationNotice:
    """Behavioural-change notice for users with scripted ``ohtv ask --agent``.

    Issue #161 redefined ``--agent`` to select the prompt-cookbook agent
    (different surface from the legacy 4-tool agent, which moved to
    ``--agent-tools``). A one-line stderr notice points users at
    ``--agent-tools`` if they wanted the old behaviour.
    """

    def test_agent_emits_notice_on_stderr(self, runner):
        result = runner.invoke(main, ["ask", "q", "--agent", "--max-steps", "0"])
        # The notice must land on stderr so JSON / pipe consumers aren't
        # disturbed by it on stdout.
        assert "Note: --agent now selects the prompt-cookbook agent" in (
            result.stderr or ""
        )
        # And it must mention the legacy escape hatch so users know
        # what to flip to.
        assert "--agent-tools" in (result.stderr or "")

    def test_agent_tools_does_not_emit_notice(self, runner):
        result = runner.invoke(
            main, ["ask", "q", "--agent-tools", "--max-steps", "0"]
        )
        # --agent-tools is the legacy flag with its original meaning;
        # no behavioural-change notice should fire for it.
        assert "Note: --agent now selects" not in (result.stderr or "")

    def test_no_agent_flag_no_notice(self, runner):
        """Plain ``ohtv ask`` (no agent flag) must not print the notice."""
        result = runner.invoke(main, ["ask", "q"])
        assert "Note: --agent now selects" not in (result.stderr or "")
