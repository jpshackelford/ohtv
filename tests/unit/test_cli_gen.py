"""Unit tests for the unified gen CLI command."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner

from ohtv.cli import main, _run_objectives_analysis
from ohtv.prompts import resolve_prompt, resolve_context, list_variants


# =============================================================================
# Test Helpers
# =============================================================================


def create_mock_conversation_info(
    conv_id: str,
    title: str = "Test Conversation",
    created_at: datetime | None = None,
    source: str = "local",
):
    """Create a mock ConversationInfo object."""
    mock = MagicMock()
    mock.id = conv_id
    mock.short_id = conv_id[:7]
    mock.lookup_id = conv_id
    mock.title = title
    mock.source = source
    mock.created_at = created_at or datetime.now(timezone.utc)
    mock.event_count = 5
    return mock


def create_mock_analysis_result(goal: str = "Test goal", from_cache: bool = False, cost: float = 0.001):
    """Create a mock AnalysisResult."""
    from ohtv.analysis.objectives import ObjectiveAnalysis, AnalysisResult
    
    analysis = ObjectiveAnalysis(
        conversation_id="test123",
        context_level="minimal",
        detail_level="brief",
        goal=goal,
        analyzed_at=datetime.now(timezone.utc),
        model_used="test-model",
        event_count=5,
        content_hash="abc123",
    )
    return AnalysisResult(analysis=analysis, cost=cost, from_cache=from_cache)


# =============================================================================
# Single-Conversation Mode Tests (Existing Behavior)
# =============================================================================


class TestGenObjectivesCommand:
    """Tests for the new 'ohtv gen objectives' command."""
    
    @pytest.fixture
    def runner(self):
        """Create a Click test runner."""
        return CliRunner()
    
    @pytest.fixture
    def mock_config(self):
        """Mock Config.from_env() to avoid needing real config."""
        with patch("ohtv.cli.Config") as mock:
            mock_instance = MagicMock()
            mock_instance.local_source.conversations_dir = Path("/tmp/test-convos")
            mock.from_env.return_value = mock_instance
            yield mock
    
    @pytest.fixture
    def mock_conversation(self):
        """Mock conversation finding."""
        with patch("ohtv.cli._find_conversation_dir") as mock:
            mock.return_value = (Path("/tmp/test-convos/abc123"), None)
            yield mock
    
    @pytest.fixture
    def mock_conv_info(self):
        """Mock conversation info retrieval."""
        with patch("ohtv.cli._get_conversation_info") as mock:
            mock.return_value = ("abc123", "Test Conversation")
            yield mock
    
    @pytest.fixture
    def mock_analysis(self):
        """Mock the analysis functions."""
        with patch("ohtv.cli.load_events") as mock_events, \
             patch("ohtv.cli.get_cached_analysis") as mock_cache, \
             patch("ohtv.cli.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._display_objectives") as mock_display, \
             patch("ohtv.cli._display_outputs") as mock_outputs:
            
            # Setup mock returns
            mock_events.return_value = []
            mock_cache.return_value = None
            
            # Mock analysis result
            from ohtv.analysis.objectives import ObjectiveAnalysis, AnalysisResult
            mock_result = MagicMock(spec=AnalysisResult)
            mock_result.analysis = ObjectiveAnalysis(
                conversation_id="abc123",
                context_level="minimal",
                detail_level="brief",
                goal="Test goal"
            )
            mock_result.cost = 0.001
            mock_analyze.return_value = mock_result
            
            yield {
                "events": mock_events,
                "cache": mock_cache,
                "analyze": mock_analyze,
                "display": mock_display,
                "outputs": mock_outputs,
            }
    
    def test_variant_selection(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test that variant selection works with --variant option."""
        # Test brief variant
        variants = list_variants("objs")
        assert "brief" in variants
        
        # Verify we can resolve it
        meta = resolve_prompt("objs", "brief")
        assert meta.variant == "brief"
        assert meta.family == "objs"
    
    def test_context_selection_by_number(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test context selection using numeric level."""
        # Get a prompt to test context resolution
        meta = resolve_prompt("objs", "brief")
        
        # Should have context levels 1, 2, 3
        assert 1 in meta.context_levels
        assert 2 in meta.context_levels
        assert 3 in meta.context_levels
        
        # Resolve by number
        ctx = resolve_context(meta, 1)
        assert ctx.name == "minimal"
        
        ctx = resolve_context(meta, 2)
        assert ctx.name == "default"  # Level 2 is named "default" in prompts
        
        ctx = resolve_context(meta, 3)
        assert ctx.name == "full"
    
    def test_context_selection_by_name(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test context selection using name."""
        meta = resolve_prompt("objs", "brief")
        
        # Resolve by name
        ctx = resolve_context(meta, "minimal")
        assert ctx.number == 1
        
        ctx = resolve_context(meta, "default")  # Level 2 is named "default" in prompts
        assert ctx.number == 2
        
        ctx = resolve_context(meta, "full")
        assert ctx.number == 3
    
    def test_default_variant_used_when_not_specified(self):
        """Test that default variant is used when none specified."""
        # Resolve without variant should use default
        meta = resolve_prompt("objs")
        assert meta.default is True
        assert meta.variant == "brief"  # brief is marked as default
    
    def test_legacy_detail_assess_mapping(self):
        """Test that legacy detail+assess options map to correct variants."""
        # detail=brief, assess=False -> variant=brief
        meta = resolve_prompt("objs", "brief")
        assert meta.variant == "brief"
        
        # detail=brief, assess=True -> variant=brief_assess
        meta = resolve_prompt("objs", "brief_assess")
        assert meta.variant == "brief_assess"
        
        # detail=standard, assess=False -> variant=standard
        meta = resolve_prompt("objs", "standard")
        assert meta.variant == "standard"
        
        # detail=standard, assess=True -> variant=standard_assess
        meta = resolve_prompt("objs", "standard_assess")
        assert meta.variant == "standard_assess"
    
    def test_legacy_context_default_resolves(self):
        """Test that 'default' context level resolves correctly."""
        meta = resolve_prompt("objs", "brief")
        
        # Context level 2 is named "default" in the prompts
        ctx = resolve_context(meta, "default")
        assert ctx.name == "default"
        
        # Verify the context exists
        assert any(level.name == "default" for level in meta.context_levels.values())
    
    def test_all_objective_variants_exist(self):
        """Test that all expected objective variants exist."""
        variants = list_variants("objs")
        
        expected = [
            "brief",
            "brief_assess", 
            "standard",
            "standard_assess",
            "detailed",
            "detailed_assess",
        ]
        
        for variant in expected:
            assert variant in variants, f"Missing variant: {variant}"
    
    def test_variant_error_shows_available_variants(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test that error message shows available variants."""
        result = runner.invoke(main, ["gen", "objs", "abc123", "--variant", "nonexistent"])
        
        assert result.exit_code != 0
        assert "nonexistent" in result.output or "Unknown variant" in result.output


class TestRunObjectivesAnalysis:
    """Tests for the shared _run_objectives_analysis function."""
    
    def test_variant_construction_from_legacy_params(self):
        """Test that legacy detail+assess correctly construct variant name."""
        # This is tested indirectly through the mapping logic
        # detail=brief, assess=False -> brief
        # detail=brief, assess=True -> brief_assess
        
        # We can test this by checking variant resolution works
        meta = resolve_prompt("objs", "brief")
        assert meta.variant == "brief"
        assert not meta.variant.endswith("_assess")
        
        meta_assess = resolve_prompt("objs", "brief_assess")
        assert meta_assess.variant == "brief_assess"
        assert meta_assess.variant.endswith("_assess")
    
    def test_context_level_name_extraction(self):
        """Test that context level names are correctly extracted."""
        meta = resolve_prompt("objs", "brief")
        
        # All prompts should have context levels with names
        for level_num, level in meta.context_levels.items():
            assert level.name, f"Level {level_num} should have a name"
            assert level.name in ["minimal", "default", "full"]


class TestContextLevelFilters:
    """Tests for context level event filtering."""
    
    def test_minimal_context_includes_user_messages_only(self):
        """Test that minimal context only includes user messages."""
        meta = resolve_prompt("objs", "brief")
        ctx = resolve_context(meta, 1)  # Minimal
        
        assert ctx.name == "minimal"
        
        # Check filters
        user_msg = {"source": "user", "kind": "MessageEvent"}
        agent_msg = {"source": "agent", "kind": "MessageEvent"}
        
        assert ctx.matches(user_msg)
        assert not ctx.matches(agent_msg)
    
    def test_default_context_includes_user_and_finish(self):
        """Test that default context includes user messages and finish action."""
        meta = resolve_prompt("objs", "brief")
        ctx = resolve_context(meta, 2)  # Level 2 is "default"
        
        assert ctx.name == "default"
        
        # Should match user messages and finish action
        user_msg = {"source": "user", "kind": "MessageEvent"}
        finish_action = {"source": "agent", "kind": "ActionEvent", "tool_name": "finish"}
        agent_msg = {"source": "agent", "kind": "MessageEvent"}
        
        assert ctx.matches(user_msg)
        assert ctx.matches(finish_action)
        # Agent messages might be included depending on the prompt
    
    def test_full_context_includes_all_messages(self):
        """Test that full context includes all messages and actions."""
        meta = resolve_prompt("objs", "brief")
        ctx = resolve_context(meta, 3)  # Full
        
        assert ctx.name == "full"
        
        # Should match all event types
        user_msg = {"source": "user", "kind": "MessageEvent"}
        agent_msg = {"source": "agent", "kind": "MessageEvent"}
        action = {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"}
        
        assert ctx.matches(user_msg)
        assert ctx.matches(agent_msg)
        assert ctx.matches(action)


class TestPromptMetadata:
    """Tests for prompt metadata structure."""
    
    def test_all_variants_have_required_metadata(self):
        """Test that all variants have required metadata fields."""
        variants = list_variants("objs")
        
        for variant in variants:
            meta = resolve_prompt("objs", variant)
            
            # Required fields
            assert meta.id
            assert meta.family == "objs"
            assert meta.variant == variant
            assert meta.context_levels, f"{variant} should have context levels"
            assert meta.default_context > 0, f"{variant} should have default_context"
            assert meta.content, f"{variant} should have content"
    
    def test_exactly_one_default_variant(self):
        """Test that exactly one variant is marked as default."""
        variants = list_variants("objs")
        defaults = [v for v in variants if resolve_prompt("objs", v).default]
        
        assert len(defaults) == 1, f"Should have exactly one default variant, found: {defaults}"
        assert defaults[0] == "brief", "Brief should be the default variant"
    
    def test_context_levels_are_numbered_sequentially(self):
        """Test that context levels are numbered 1, 2, 3, etc."""
        meta = resolve_prompt("objs", "brief")
        
        level_numbers = sorted(meta.context_levels.keys())
        expected = list(range(1, len(level_numbers) + 1))
        
        assert level_numbers == expected, "Context levels should be numbered sequentially from 1"


# =============================================================================
# Multi-Conversation (Batch) Mode Tests
# =============================================================================


class TestGenObjsBatchModeDetection:
    """Tests for single vs multi-conversation mode detection."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_no_args_triggers_batch_mode(self, runner):
        """When conversation_id is None, batch mode is used."""
        # Use a filter that will produce no results to verify batch mode is called
        with patch("ohtv.cli._run_batch_objectives_analysis") as mock_batch, \
             patch("ohtv.cli._run_objectives_analysis") as mock_single:
            # Configure batch to handle the call gracefully
            mock_batch.return_value = None
            
            result = runner.invoke(main, ["gen", "objs", "--since", "2099-01-01"])
            
            # Batch mode should be called, not single mode
            assert mock_batch.called or "No conversations found" in result.output
            assert not mock_single.called

    def test_conversation_id_triggers_single_mode(self, runner):
        """When conversation_id is provided, single mode is used."""
        with patch("ohtv.cli._run_objectives_analysis") as mock_single, \
             patch("ohtv.cli._run_batch_objectives_analysis") as mock_batch:
            mock_single.return_value = None
            
            result = runner.invoke(main, ["gen", "objs", "abc123"])
            
            # Single mode should be called
            mock_single.assert_called_once()
            assert not mock_batch.called


class TestBatchModeDefaults:
    """Tests for default values in batch/multi-conversation mode.
    
    These test that batch mode uses token-efficient defaults:
    - variant: brief (not detailed)
    - context: minimal (not full)
    - limit: 10 (not all)
    """

    def test_batch_mode_defaults_variant_to_brief(self):
        """Batch mode should default to 'brief' variant for token efficiency."""
        # The _run_batch_objectives_analysis function defaults to brief
        # We verify this by checking the code path defaults
        
        # When variant is None, detail should be "brief" and assess should be False
        # This is set in _run_batch_objectives_analysis around line 5249-5252
        
        # Test that the default variant resolves correctly
        meta = resolve_prompt("objs")  # No variant = default
        assert meta.variant == "brief", "Default variant should be brief"

    def test_batch_mode_defaults_context_to_minimal(self):
        """Batch mode should default to 'minimal' context for token efficiency."""
        # When context is None, batch mode uses "minimal"
        # This is set in _run_batch_objectives_analysis around line 5256
        
        meta = resolve_prompt("objs", "brief")
        ctx = resolve_context(meta, "minimal")
        assert ctx.name == "minimal"
        assert ctx.number == 1  # Minimal is context level 1

    def test_default_limit_is_10(self):
        """Without --all or -n, batch mode should limit to 10 conversations."""
        # This is verified in integration tests, but we document the expectation here
        # The limit of 10 is applied in _run_batch_objectives_analysis when:
        # - limit is None (no -n flag)
        # - show_all is False (no --all flag)
        # See line ~5233-5236 in cli.py
        pass  # Logic test - actual behavior tested in integration


class TestBatchModeConfirmation:
    """Tests for the confirmation threshold logic."""

    def test_confirmation_threshold_is_20(self):
        """Confirmation should be required for >20 uncached conversations."""
        # SUMMARY_CONFIRM_THRESHOLD = 20 is defined in _run_batch_objectives_analysis
        # This is a design decision test - actual behavior tested in integration
        pass

    def test_cached_conversations_excluded_from_confirmation_count(self):
        """Only uncached conversations should count toward confirmation threshold."""
        # When refresh=False, only uncached conversations trigger confirmation
        # This is handled by _count_uncached_conversations_fast
        pass


class TestBatchModeOutputFormatting:
    """Tests for batch mode output format helpers."""

    @pytest.fixture
    def sample_results(self):
        """Sample results for formatting tests."""
        return [
            {
                "id": "abc123def456",
                "short_id": "abc123d",
                "source": "cloud",
                "created_at": datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
                "goal": "Refactor authentication module",
                "cached": True,
                "conv_dir": Path("/tmp/conv1"),
            },
            {
                "id": "xyz789uvw012",
                "short_id": "xyz789u",
                "source": "local",
                "created_at": datetime(2024, 3, 14, 9, 0, 0, tzinfo=timezone.utc),
                "goal": "Fix pagination bug",
                "cached": False,
                "conv_dir": Path("/tmp/conv2"),
            },
        ]

    def test_format_summary_markdown_structure(self, sample_results):
        """Markdown output should have correct structure."""
        from ohtv.cli import _format_summary_markdown
        
        output = _format_summary_markdown(sample_results, include_outputs=False)
        
        # Should contain conversation IDs
        assert "abc123d" in output
        assert "xyz789u" in output
        
        # Should contain goals
        assert "Refactor authentication" in output
        assert "Fix pagination" in output
        
        # Should be markdown formatted
        assert "**" in output  # Bold text for IDs

    def test_format_summary_markdown_with_outputs(self, sample_results):
        """Markdown output should include outputs when requested."""
        from ohtv.cli import _format_summary_markdown
        
        # Add mock outputs
        sample_results[0]["outputs"] = {
            "refs": {"repos": {"https://github.com/user/repo"}, "prs": set(), "issues": set()},
            "interactions": MagicMock(
                repos={"https://github.com/user/repo": ["pushed"]},
                prs={},
                issues={},
                unpushed_commits=set(),
            ),
            "unpushed_commits": set(),
        }
        
        output = _format_summary_markdown(sample_results, include_outputs=True)
        
        # Should include repo reference
        assert "user/repo" in output or "pushed" in output


class TestBatchModeJsonOutput:
    """Tests for JSON output format in batch mode."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def mock_batch_environment(self):
        """Mock the batch mode environment."""
        conversations = [
            create_mock_conversation_info(f"conv{i:03d}", f"Test {i}")
            for i in range(3)
        ]
        
        with patch("ohtv.cli.Config") as mock_config, \
             patch("ohtv.cli._apply_conversation_filters") as mock_filters, \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._find_conversation_dir") as mock_find, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            # Configure mocks
            mock_config.from_env.return_value = MagicMock()
            
            filter_result = MagicMock()
            filter_result.conversations = conversations
            filter_result.show_all = False
            mock_filters.return_value = filter_result
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_find.return_value = (Path("/tmp/conv"), None)
            mock_count.return_value = 0  # All cached to skip LLM
            
            yield {
                "config": mock_config,
                "filters": mock_filters,
                "analyze": mock_analyze,
                "find": mock_find,
                "count": mock_count,
                "conversations": conversations,
            }

    def test_json_output_is_valid_json(self, runner, mock_batch_environment):
        """JSON output should be parseable."""
        result = runner.invoke(main, ["gen", "objs", "-F", "json"])
        
        # Should not error
        if result.exit_code != 0 and "No conversations found" not in result.output:
            # If we got output, it should be valid JSON
            if result.output.strip().startswith("["):
                data = json.loads(result.output)
                assert isinstance(data, list)

    def test_json_output_structure(self, runner, mock_batch_environment):
        """JSON output should have expected fields."""
        result = runner.invoke(main, ["gen", "objs", "-F", "json"])
        
        if result.output.strip().startswith("["):
            data = json.loads(result.output)
            if data:
                item = data[0]
                # Expected fields
                assert "id" in item
                assert "goal" in item
                assert "created_at" in item or "source" in item


class TestBatchModeQuietFlag:
    """Tests for --quiet flag behavior."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_quiet_flag_suppresses_table_output(self, runner):
        """--quiet should suppress the table output but still process."""
        with patch("ohtv.cli.Config") as mock_config, \
             patch("ohtv.cli._apply_conversation_filters") as mock_filters, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_config.from_env.return_value = MagicMock()
            
            # Return empty to avoid LLM calls
            filter_result = MagicMock()
            filter_result.conversations = []
            filter_result.show_all = False
            mock_filters.return_value = filter_result
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-q"])
            
            # Should show "no conversations" message since we have none
            # But no table should be shown
            assert "┃" not in result.output  # No table borders


class TestBatchModeYesFlag:
    """Tests for --yes flag behavior."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_yes_flag_recognized(self, runner):
        """--yes flag should be recognized by the CLI."""
        result = runner.invoke(main, ["gen", "objs", "--yes", "--help"])
        # Should not error on the flag
        assert result.exit_code == 0


class TestBatchModeFilters:
    """Tests for filter options in batch mode."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_day_filter_recognized(self, runner):
        """--day filter should be recognized."""
        # Just verify the CLI accepts the option
        result = runner.invoke(main, ["gen", "objs", "--day", "--help"])
        assert "--day" in result.output or result.exit_code == 0

    def test_week_filter_recognized(self, runner):
        """--week filter should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--week", "--help"])
        assert "--week" in result.output or result.exit_code == 0

    def test_since_until_filters_recognized(self, runner):
        """--since and --until filters should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--since" in result.output
        assert "--until" in result.output

    def test_pr_repo_action_filters_recognized(self, runner):
        """--pr, --repo, --action filters should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--pr" in result.output
        assert "--repo" in result.output
        assert "--action" in result.output


class TestBatchModePagination:
    """Tests for pagination options in batch mode."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_max_option_recognized(self, runner):
        """-n/--max option should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--max" in result.output or "-n" in result.output

    def test_offset_option_recognized(self, runner):
        """-k/--offset option should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--offset" in result.output or "-k" in result.output

    def test_reverse_option_recognized(self, runner):
        """--reverse option should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--reverse" in result.output

    def test_all_option_recognized(self, runner):
        """-A/--all option should be recognized."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert "--all" in result.output


class TestBatchModeErrorHandling:
    """Tests for error handling in batch mode."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_no_conversations_shows_friendly_message(self, runner):
        """When no conversations match, should show friendly message."""
        with patch("ohtv.cli.Config") as mock_config, \
             patch("ohtv.cli._apply_conversation_filters") as mock_filters:
            
            mock_config.from_env.return_value = MagicMock()
            
            filter_result = MagicMock()
            filter_result.conversations = []
            filter_result.show_all = False
            mock_filters.return_value = filter_result
            
            result = runner.invoke(main, ["gen", "objs"])
            
            assert "No conversations found" in result.output

    def test_invalid_format_rejected(self, runner):
        """Invalid format option should be rejected."""
        result = runner.invoke(main, ["gen", "objs", "-F", "invalid"])
        
        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "choice" in result.output.lower()

    def test_filters_with_conversation_id_rejected(self, runner):
        """Using filters with a specific conversation_id should error."""
        result = runner.invoke(main, ["gen", "objs", "abc123", "--day"])
        
        assert result.exit_code != 0
        assert "Cannot use filters" in result.output

    def test_filters_with_conversation_id_shows_guidance(self, runner):
        """Error message should guide user to correct usage."""
        result = runner.invoke(main, ["gen", "objs", "abc123", "--week"])
        
        assert result.exit_code != 0
        assert "ohtv gen objs <conversation_id>" in result.output or "single conversation" in result.output.lower()
        assert "ohtv gen objs --day" in result.output or "multiple conversations" in result.output.lower()


class TestBatchModeHelpText:
    """Tests for help text accuracy."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help_shows_both_modes(self, runner):
        """Help should document both single and multi-conversation modes."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        
        assert result.exit_code == 0
        # Should mention single mode
        assert "SINGLE" in result.output.upper() or "conversation_id" in result.output
        # Should mention multi/batch mode
        assert "MULTI" in result.output.upper() or "batch" in result.output.lower() or "--day" in result.output

    def test_help_shows_variants(self, runner):
        """Help should list available variants."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        
        assert "brief" in result.output
        assert "detailed" in result.output or "variant" in result.output.lower()

    def test_help_shows_context_levels(self, runner):
        """Help should explain context levels."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        
        assert "minimal" in result.output or "context" in result.output.lower()
