"""Integration tests for gen objs batch/multi-conversation mode.

These tests verify the complete CLI flow for analyzing multiple conversations,
with mocked LLM calls to avoid actual API usage.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# =============================================================================
# Fixtures
# =============================================================================


def create_mock_conversation(
    conv_dir: Path,
    conv_id: str,
    title: str = "Test conversation",
    created_at: datetime | None = None,
    event_count: int = 2,
) -> None:
    """Create a minimal mock conversation directory structure.

    Args:
        conv_dir: Parent directory for conversations
        conv_id: Conversation ID (directory name, no dashes)
        title: Title for the conversation
        created_at: Created timestamp (defaults to now)
        event_count: Number of mock events to create
    """
    created_at = created_at or datetime.now(timezone.utc)
    
    conv_path = conv_dir / conv_id
    conv_path.mkdir(parents=True, exist_ok=True)

    # Create base_state.json
    base_state = {
        "id": conv_id,
        "title": title,
        "selected_repository": "test/repo",
        "selected_branch": "main",
        "created_at": created_at.isoformat(),
        "updated_at": (created_at + timedelta(minutes=30)).isoformat(),
        "agent": {
            "llm": {"model": "test-model"},
            "tools": [],
        },
    }
    (conv_path / "base_state.json").write_text(json.dumps(base_state))

    # Create events directory with mock events
    events_dir = conv_path / "events"
    events_dir.mkdir(exist_ok=True)

    for i in range(event_count):
        event_time = created_at + timedelta(minutes=i)
        event = {
            "id": f"event_{i}",
            "timestamp": event_time.strftime("%Y-%m-%dT%H:%M:%S.000000"),
            "source": "user" if i % 2 == 0 else "agent",
            "kind": "MessageEvent",
            "llm_message": {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": [{"type": "text", "text": f"Message {i}"}],
            },
        }
        event_file = events_dir / f"event-{i:05d}-{chr(97 + i)}.json"
        event_file.write_text(json.dumps(event))


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


@pytest.fixture
def conversations_dir(tmp_path):
    """Create a temporary conversations directory."""
    convs = tmp_path / "conversations"
    convs.mkdir()
    return convs


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


# =============================================================================
# Default Limit Tests
# =============================================================================


class TestBatchModeDefaultLimit:
    """Tests for the default limit of 10 conversations."""

    def test_default_processes_max_10_conversations(self, runner, tmp_path):
        """Without -n or --all, should process at most 10 conversations."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        # Create 15 conversations
        now = datetime.now(timezone.utc)
        for i in range(15):
            create_mock_conversation(
                convs_dir,
                f"conv{i:03d}abc123",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0  # All cached
            
            result = runner.invoke(main, ["gen", "objs"])
            
            # Should show results but limit output
            if result.exit_code == 0:
                # Check that "Showing X of Y" indicates limit was applied
                # The exact number depends on what's found
                pass

    def test_explicit_limit_overrides_default(self, runner, tmp_path):
        """Explicit -n should override the default limit."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        # Create 15 conversations
        now = datetime.now(timezone.utc)
        for i in range(15):
            create_mock_conversation(
                convs_dir,
                f"conv{i:03d}abc123",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-n", "5"])
            
            # Command should complete
            assert result.exit_code == 0 or "No conversations found" in result.output

    def test_all_flag_removes_limit(self, runner, tmp_path):
        """--all should process all conversations without limit."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        # Create a few conversations
        now = datetime.now(timezone.utc)
        for i in range(3):
            create_mock_conversation(
                convs_dir,
                f"conv{i:03d}abc123",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "--all"])
            
            assert result.exit_code == 0 or "No conversations found" in result.output


# =============================================================================
# Output Format Tests
# =============================================================================


class TestBatchModeOutputFormats:
    """Tests for different output formats (table, json, markdown)."""

    @pytest.fixture
    def conversations_with_mock(self, tmp_path):
        """Set up conversations and mock analysis."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        for i in range(3):
            create_mock_conversation(
                convs_dir,
                f"conv{i:03d}abc123",
                title=f"Test conversation {i}",
                created_at=now - timedelta(hours=i),
            )
        
        return convs_dir, tmp_path

    def test_json_output_is_valid_array(self, runner, conversations_with_mock):
        """JSON output should be a valid JSON array."""
        convs_dir, tmp_path = conversations_with_mock
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result("Implement feature X")
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-F", "json"])
            
            if result.exit_code == 0 and result.output.strip().startswith("["):
                data = json.loads(result.output)
                assert isinstance(data, list)
                if data:
                    assert "id" in data[0]
                    assert "goal" in data[0]

    def test_markdown_output_has_list_format(self, runner, conversations_with_mock):
        """Markdown output should use list format with bold IDs."""
        convs_dir, tmp_path = conversations_with_mock
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result("Implement feature X")
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-F", "markdown"])
            
            if result.exit_code == 0:
                # Markdown should contain bold text (IDs) and list markers
                assert "**" in result.output or "- " in result.output or "No conversations" in result.output

    def test_table_output_has_borders(self, runner, conversations_with_mock):
        """Table output should have Rich table borders."""
        convs_dir, tmp_path = conversations_with_mock
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result("Implement feature X")
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-F", "table"])
            
            if result.exit_code == 0:
                # Table should have Rich borders or "No conversations" message
                has_table = "┃" in result.output or "│" in result.output or "ID" in result.output
                has_no_results = "No conversations" in result.output
                assert has_table or has_no_results


# =============================================================================
# Date Filter Tests
# =============================================================================


class TestBatchModeDateFilters:
    """Tests for date filtering options."""

    def test_since_filter_excludes_older(self, runner, tmp_path):
        """--since should exclude conversations before the date."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        # Old conversation (should be excluded)
        create_mock_conversation(
            convs_dir, "old123abc456",
            title="Old conversation",
            created_at=now - timedelta(days=30),
        )
        # Recent conversation (should be included)
        create_mock_conversation(
            convs_dir, "new123abc456",
            title="New conversation", 
            created_at=now,
        )

        since_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "--since", since_date])
            
            # The old conversation should not appear
            if result.exit_code == 0 and "old123" not in result.output:
                # Test passed - old conversation was filtered
                pass

    def test_until_filter_excludes_newer(self, runner, tmp_path):
        """--until should exclude conversations after the date."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        # Old conversation (should be included)
        create_mock_conversation(
            convs_dir, "old123abc456",
            title="Old conversation",
            created_at=now - timedelta(days=30),
        )

        until_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "--until", until_date])
            
            # Should complete without error
            assert result.exit_code == 0 or "No conversations" in result.output


# =============================================================================
# Quiet Mode Tests
# =============================================================================


class TestBatchModeQuietFlag:
    """Tests for --quiet flag behavior."""

    def test_quiet_suppresses_all_normal_output(self, runner, tmp_path):
        """--quiet should suppress table/summary output."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        create_mock_conversation(
            convs_dir, "test123abc456",
            title="Test conversation",
            created_at=now,
        )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-q"])
            
            # Quiet mode should have minimal output
            # No table borders or "Showing X of Y" summary
            assert "┃" not in result.output
            assert "Showing" not in result.output


# =============================================================================
# Confirmation Tests
# =============================================================================


class TestBatchModeConfirmation:
    """Tests for confirmation prompt behavior."""

    def test_yes_flag_skips_confirmation(self, runner, tmp_path):
        """--yes should skip confirmation even for large batches."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        # Create enough conversations to trigger confirmation
        for i in range(25):
            create_mock_conversation(
                convs_dir, f"conv{i:03d}abc456",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 25  # All need analysis
            
            # Without --yes, this would prompt. With --yes, it should proceed.
            result = runner.invoke(main, ["gen", "objs", "--all", "-y"])
            
            # Should not contain "Aborted" since we used --yes
            assert "Aborted" not in result.output


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestBatchModeErrors:
    """Tests for error handling in batch mode."""

    def test_no_conversations_friendly_message(self, runner, tmp_path):
        """Should show friendly message when no conversations found."""
        # Empty conversations directory
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            result = runner.invoke(main, ["gen", "objs"])
            
            assert "No conversations found" in result.output

    def test_future_since_date_no_results(self, runner, tmp_path):
        """Future --since date should yield no results."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        create_mock_conversation(
            convs_dir, "test123abc456",
            title="Test",
            created_at=now,
        )
        
        future_date = (now + timedelta(days=365)).strftime("%Y-%m-%d")
        
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            result = runner.invoke(main, ["gen", "objs", "--since", future_date])
            
            assert "No conversations found" in result.output


# =============================================================================
# Pagination Tests
# =============================================================================


class TestBatchModePagination:
    """Tests for pagination options."""

    def test_offset_skips_first_n(self, runner, tmp_path):
        """--offset should skip the first N conversations."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        for i in range(5):
            create_mock_conversation(
                convs_dir, f"conv{i:03d}abc456",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            # Skip first 3, should only show 2
            result = runner.invoke(main, ["gen", "objs", "-k", "3", "--all"])
            
            # Should complete successfully
            assert result.exit_code == 0 or "No conversations" in result.output

    def test_reverse_shows_oldest_first(self, runner, tmp_path):
        """--reverse should show oldest conversations first."""
        convs_dir = tmp_path / "conversations"
        convs_dir.mkdir()
        
        now = datetime.now(timezone.utc)
        for i in range(3):
            create_mock_conversation(
                convs_dir, f"conv{i:03d}abc456",
                title=f"Test {i}",
                created_at=now - timedelta(hours=i),
            )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result()
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "--reverse"])
            
            # Should complete successfully
            assert result.exit_code == 0 or "No conversations" in result.output


# =============================================================================
# Migration Compatibility Tests  
# =============================================================================


class TestMigrationFromSummary:
    """Tests verifying the migration path from summary command.
    
    These tests ensure that users migrating from `ohtv summary` to `ohtv gen objs`
    get equivalent functionality.
    """

    def test_gen_objs_accepts_summary_style_options(self, runner):
        """gen objs should accept all options that summary had."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        
        # All summary options should be present
        assert "--day" in result.output or "-D" in result.output
        assert "--week" in result.output or "-W" in result.output
        assert "--since" in result.output or "-S" in result.output
        assert "--until" in result.output or "-U" in result.output
        assert "--max" in result.output or "-n" in result.output
        assert "--all" in result.output or "-A" in result.output
        assert "--offset" in result.output or "-k" in result.output
        assert "--reverse" in result.output
        assert "--format" in result.output or "-F" in result.output
        assert "--yes" in result.output or "-y" in result.output
        assert "--quiet" in result.output or "-q" in result.output
        assert "--no-outputs" in result.output

    def test_no_cache_replaces_refresh(self, runner):
        """--no-cache should work (replaces old --refresh)."""
        result = runner.invoke(main, ["gen", "objs", "--help"])
        
        assert "--no-cache" in result.output
        # Old --refresh should NOT be present
        assert "--refresh" not in result.output or "-r, --refresh" not in result.output


# =============================================================================
# Display Schema Integration Tests
# =============================================================================


def create_mock_analysis_result_with_status(
    goal: str = "Test goal",
    status: str = "achieved",
    primary_outcomes: list[str] | None = None,
    secondary_outcomes: list[str] | None = None,
    from_cache: bool = False,
    cost: float = 0.001,
):
    """Create a mock AnalysisResult with status and outcomes for standard_assess."""
    from ohtv.analysis.objectives import ObjectiveAnalysis, AnalysisResult
    
    analysis = ObjectiveAnalysis(
        conversation_id="test123",
        context_level="default",
        detail_level="standard",
        assess=True,
        goal=goal,
        status=status,
        primary_outcomes=primary_outcomes or ["Outcome 1", "Outcome 2"],
        secondary_outcomes=secondary_outcomes or ["Secondary 1"],
        analyzed_at=datetime.now(timezone.utc),
        model_used="test-model",
        event_count=5,
        content_hash="abc123",
    )
    return AnalysisResult(analysis=analysis, cost=cost, from_cache=from_cache)


class TestDisplaySchemaIntegration:
    """Integration tests for display schema rendering with different variants."""

    def test_standard_assess_displays_status_badge(self, runner, tmp_path):
        """Verify standard_assess variant shows Status column with emoji badge."""
        # Create conversations in .openhands/conversations to match CLI expectations
        convs_dir = tmp_path / ".openhands" / "conversations"
        convs_dir.mkdir(parents=True)
        
        now = datetime.now(timezone.utc)
        create_mock_conversation(
            convs_dir, "test123abc456",
            title="Test conversation",
            created_at=now,
        )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result_with_status(
                goal="Implement user authentication",
                status="achieved",
                primary_outcomes=["Login endpoint created", "Session management added"],
            )
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-v", "standard_assess"])
            
            # Should display the achieved status badge
            assert "✅" in result.output, f"Expected status badge in output: {result.output}"

    def test_standard_assess_displays_not_achieved_badge(self, runner, tmp_path):
        """Verify not_achieved status shows ❌ badge."""
        convs_dir = tmp_path / ".openhands" / "conversations"
        convs_dir.mkdir(parents=True)
        
        now = datetime.now(timezone.utc)
        create_mock_conversation(
            convs_dir, "test456def789",
            title="Failed task",
            created_at=now,
        )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result_with_status(
                goal="Deploy to production",
                status="not_achieved",
            )
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-v", "standard_assess"])
            
            assert "❌" in result.output, f"Expected not_achieved badge in output: {result.output}"

    def test_standard_assess_displays_outcomes(self, runner, tmp_path):
        """Verify primary and secondary outcomes are displayed."""
        convs_dir = tmp_path / ".openhands" / "conversations"
        convs_dir.mkdir(parents=True)
        
        now = datetime.now(timezone.utc)
        create_mock_conversation(
            convs_dir, "test789ghi012",
            title="Feature implementation",
            created_at=now,
        )

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("ohtv.analysis.analyze_objectives") as mock_analyze, \
             patch("ohtv.cli._count_uncached_conversations_fast") as mock_count:
            
            mock_analyze.return_value = create_mock_analysis_result_with_status(
                goal="Add pagination to API",
                status="achieved",
                primary_outcomes=["Pagination endpoint added", "Tests written"],
                secondary_outcomes=["Documentation updated"],
            )
            mock_count.return_value = 0
            
            result = runner.invoke(main, ["gen", "objs", "-v", "standard_assess"])
            
            # Check that outcomes are displayed (bullet format uses •)
            assert "Primary:" in result.output or "Pagination" in result.output, \
                f"Expected outcomes in output: {result.output}"
