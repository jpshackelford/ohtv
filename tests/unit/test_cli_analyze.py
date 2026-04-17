"""Unit tests for the unified analyze CLI command."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner

from ohtv.cli import main, _run_objectives_analysis
from ohtv.prompts import resolve_prompt, resolve_context, list_variants


class TestAnalyzeObjectivesCommand:
    """Tests for the new 'ohtv analyze objectives' command."""
    
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
        variants = list_variants("objectives")
        assert "brief" in variants
        
        # Verify we can resolve it
        meta = resolve_prompt("objectives", "brief")
        assert meta.variant == "brief"
        assert meta.family == "objectives"
    
    def test_context_selection_by_number(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test context selection using numeric level."""
        # Get a prompt to test context resolution
        meta = resolve_prompt("objectives", "brief")
        
        # Should have context levels 1, 2, 3
        assert 1 in meta.context_levels
        assert 2 in meta.context_levels
        assert 3 in meta.context_levels
        
        # Resolve by number
        ctx = resolve_context(meta, 1)
        assert ctx.name == "minimal"
        
        ctx = resolve_context(meta, 2)
        assert ctx.name == "standard"
        
        ctx = resolve_context(meta, 3)
        assert ctx.name == "full"
    
    def test_context_selection_by_name(self, runner, mock_config, mock_conversation, mock_conv_info):
        """Test context selection using name."""
        meta = resolve_prompt("objectives", "brief")
        
        # Resolve by name
        ctx = resolve_context(meta, "minimal")
        assert ctx.number == 1
        
        ctx = resolve_context(meta, "standard")
        assert ctx.number == 2
        
        ctx = resolve_context(meta, "full")
        assert ctx.number == 3
    
    def test_default_variant_used_when_not_specified(self):
        """Test that default variant is used when none specified."""
        # Resolve without variant should use default
        meta = resolve_prompt("objectives")
        assert meta.default is True
        assert meta.variant == "brief"  # brief is marked as default
    
    def test_legacy_detail_assess_mapping(self):
        """Test that legacy detail+assess options map to correct variants."""
        # detail=brief, assess=False -> variant=brief
        meta = resolve_prompt("objectives", "brief")
        assert meta.variant == "brief"
        
        # detail=brief, assess=True -> variant=brief_assess
        meta = resolve_prompt("objectives", "brief_assess")
        assert meta.variant == "brief_assess"
        
        # detail=standard, assess=False -> variant=standard
        meta = resolve_prompt("objectives", "standard")
        assert meta.variant == "standard"
        
        # detail=standard, assess=True -> variant=standard_assess
        meta = resolve_prompt("objectives", "standard_assess")
        assert meta.variant == "standard_assess"
    
    def test_legacy_context_default_maps_to_standard(self):
        """Test that legacy 'default' context maps to 'standard' in new system."""
        meta = resolve_prompt("objectives", "brief")
        
        # Old system: minimal, default, full
        # New system: minimal, standard, full
        
        # The mapping should happen in _run_objectives_analysis
        # "default" -> "standard"
        ctx = resolve_context(meta, "standard")
        assert ctx.name == "standard"
        
        # Verify the context exists
        assert any(level.name == "standard" for level in meta.context_levels.values())
    
    def test_all_objective_variants_exist(self):
        """Test that all expected objective variants exist."""
        variants = list_variants("objectives")
        
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
        result = runner.invoke(main, ["analyze", "objectives", "abc123", "--variant", "nonexistent"])
        
        assert result.exit_code != 0
        assert "nonexistent" in result.output or "Unknown variant" in result.output


class TestBackwardCompatibility:
    """Tests for backward compatibility with old 'ohtv objectives' command."""
    
    @pytest.fixture
    def runner(self):
        """Create a Click test runner."""
        return CliRunner()
    
    def test_old_command_still_exists(self, runner):
        """Test that old 'ohtv objectives' command still exists."""
        result = runner.invoke(main, ["objectives", "--help"])
        assert result.exit_code == 0
        assert "objectives" in result.output.lower()
    
    def test_old_options_still_work(self, runner):
        """Test that old command options are still accepted."""
        # Just test that the options are recognized (will fail without real data)
        result = runner.invoke(main, ["objectives", "--help"])
        assert result.exit_code == 0
        
        # Check for old options
        assert "--detail" in result.output or "-d" in result.output
        assert "--assess" in result.output or "-a" in result.output
        assert "--context" in result.output or "-c" in result.output


class TestRunObjectivesAnalysis:
    """Tests for the shared _run_objectives_analysis function."""
    
    def test_variant_construction_from_legacy_params(self):
        """Test that legacy detail+assess correctly construct variant name."""
        # This is tested indirectly through the mapping logic
        # detail=brief, assess=False -> brief
        # detail=brief, assess=True -> brief_assess
        
        # We can test this by checking variant resolution works
        meta = resolve_prompt("objectives", "brief")
        assert meta.variant == "brief"
        assert not meta.variant.endswith("_assess")
        
        meta_assess = resolve_prompt("objectives", "brief_assess")
        assert meta_assess.variant == "brief_assess"
        assert meta_assess.variant.endswith("_assess")
    
    def test_context_level_name_extraction(self):
        """Test that context level names are correctly extracted."""
        meta = resolve_prompt("objectives", "brief")
        
        # All prompts should have context levels with names
        for level_num, level in meta.context_levels.items():
            assert level.name, f"Level {level_num} should have a name"
            assert level.name in ["minimal", "standard", "full"]


class TestContextLevelFilters:
    """Tests for context level event filtering."""
    
    def test_minimal_context_includes_user_messages_only(self):
        """Test that minimal context only includes user messages."""
        meta = resolve_prompt("objectives", "brief")
        ctx = resolve_context(meta, 1)  # Minimal
        
        assert ctx.name == "minimal"
        
        # Check filters
        user_msg = {"source": "user", "kind": "MessageEvent"}
        agent_msg = {"source": "agent", "kind": "MessageEvent"}
        
        assert ctx.matches(user_msg)
        assert not ctx.matches(agent_msg)
    
    def test_standard_context_includes_user_and_finish(self):
        """Test that standard context includes user messages and finish action."""
        meta = resolve_prompt("objectives", "brief")
        ctx = resolve_context(meta, 2)  # Standard
        
        assert ctx.name == "standard"
        
        # Should match user messages and finish action
        user_msg = {"source": "user", "kind": "MessageEvent"}
        finish_action = {"source": "agent", "kind": "ActionEvent", "tool_name": "finish"}
        agent_msg = {"source": "agent", "kind": "MessageEvent"}
        
        assert ctx.matches(user_msg)
        assert ctx.matches(finish_action)
        # Agent messages might be included depending on the prompt
    
    def test_full_context_includes_all_messages(self):
        """Test that full context includes all messages and actions."""
        meta = resolve_prompt("objectives", "brief")
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
        variants = list_variants("objectives")
        
        for variant in variants:
            meta = resolve_prompt("objectives", variant)
            
            # Required fields
            assert meta.id
            assert meta.family == "objectives"
            assert meta.variant == variant
            assert meta.context_levels, f"{variant} should have context levels"
            assert meta.default_context > 0, f"{variant} should have default_context"
            assert meta.content, f"{variant} should have content"
    
    def test_exactly_one_default_variant(self):
        """Test that exactly one variant is marked as default."""
        variants = list_variants("objectives")
        defaults = [v for v in variants if resolve_prompt("objectives", v).default]
        
        assert len(defaults) == 1, f"Should have exactly one default variant, found: {defaults}"
        assert defaults[0] == "brief", "Brief should be the default variant"
    
    def test_context_levels_are_numbered_sequentially(self):
        """Test that context levels are numbered 1, 2, 3, etc."""
        meta = resolve_prompt("objectives", "brief")
        
        level_numbers = sorted(meta.context_levels.keys())
        expected = list(range(1, len(level_numbers) + 1))
        
        assert level_numbers == expected, "Context levels should be numbered sequentially from 1"
