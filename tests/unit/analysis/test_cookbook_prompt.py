"""Snapshot test for the CLI-mode investigator system prompt (Issue #161).

The cookbook lives at module scope so behavioural drift is caught at PR
review. The assertions below are deliberately broad — they don't pin the
exact wording (which is allowed to evolve), but they DO pin the cookbook
contract: every allow-listed command appears, plus the JSON / browse /
finish guidance the issue body called out.

If you legitimately need to change the prompt, update this test in the
same commit; reviewers should see the diff side-by-side.
"""

from ohtv.analysis.investigator_cli import (
    COOKBOOK_PROMPT,
    get_investigation_cli_system_prompt,
)
from ohtv.analysis.ohtv_runner import ALLOWED_SUBCOMMANDS


class TestCookbookPrompt:
    def test_accessor_returns_module_constant(self):
        assert get_investigation_cli_system_prompt() is COOKBOOK_PROMPT

    def test_mentions_run_ohtv_tool(self):
        assert "run_ohtv" in COOKBOOK_PROMPT
        # The cookbook teaches argv shape, not Python tool calls.
        assert "argv" in COOKBOOK_PROMPT

    def test_lists_every_allow_listed_subcommand(self):
        """Every allow-listed prefix must appear in the cookbook.

        This is the hard contract — if the runner allows a command,
        the cookbook must teach the agent how to invoke it.
        """
        for prefix in ALLOWED_SUBCOMMANDS:
            assert " ".join(prefix) in COOKBOOK_PROMPT, (
                f"Allow-listed prefix {prefix!r} is missing from the cookbook. "
                "Either add it to the prompt or remove it from the allow-list."
            )

    def test_teaches_F_json_for_structured_output(self):
        assert "-F json" in COOKBOOK_PROMPT

    def test_teaches_finish_tool(self):
        assert "finish" in COOKBOOK_PROMPT

    def test_calls_out_cache_only_semantics(self):
        # Per Issue #161 AC: the agent must know that ``gen objs`` is
        # cache-only and that ``goal: null`` is a "no cached analysis"
        # signal, not "no goal".
        assert "cache-only" in COOKBOOK_PROMPT.lower() or "cache only" in COOKBOOK_PROMPT.lower()
        assert "goal: null" in COOKBOOK_PROMPT or "goal=null" in COOKBOOK_PROMPT.lower()

    def test_browse_vs_search_guidance(self):
        # Issue #161 §"System prompt cookbook" Guideline 4.
        lowered = COOKBOOK_PROMPT.lower()
        assert "browse" in lowered or "temporal" in lowered or "enumerative" in lowered
        assert "search" in lowered

    def test_short_id_hint(self):
        # 8-char IDs work everywhere; the cookbook should say so.
        assert "8" in COOKBOOK_PROMPT and "id" in COOKBOOK_PROMPT.lower()

    def test_prompt_is_non_empty_and_reasonable_size(self):
        # Floor: cookbook can't shrink to nothing without losing the
        # contract. Ceiling: we don't want runaway prompt bloat.
        assert 500 < len(COOKBOOK_PROMPT) < 5000
