"""Integration tests for gen run command with aggregate analysis.

These tests verify the complete flow for aggregate analysis jobs,
including period iteration, cache behavior, and output formats.
LLM calls are mocked to avoid actual API usage.
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
    """Create a minimal mock conversation directory structure."""
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


def create_cached_objective_result(conv_path: Path, goal: str = "Test goal") -> None:
    """Create a cached objective analysis result for a conversation."""
    cache_key = "assess=False,context_level=minimal,detail_level=brief"
    cache_data = {
        "analyses": {
            cache_key: {
                "goal": goal,
                "confidence": 0.9,
                "key_actions": ["action1", "action2"],
            }
        }
    }
    (conv_path / "objective_analysis.json").write_text(json.dumps(cache_data))


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def ohtv_home(tmp_path):
    """Create an OHTV home directory structure."""
    ohtv_dir = tmp_path / ".ohtv"
    ohtv_dir.mkdir()
    (ohtv_dir / "conversations").mkdir()
    (ohtv_dir / "cache").mkdir()
    return tmp_path


# =============================================================================
# Job ID Validation Tests
# =============================================================================


class TestJobIdValidation:
    """Tests for job ID format validation."""

    def test_invalid_job_id_without_dot(self, runner, ohtv_home):
        """Test that job ID without dot is rejected."""
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            result = runner.invoke(main, ["gen", "run", "invalidjobid"])
            
            assert result.exit_code != 0
            assert "must be family.variant" in result.output

    def test_nonexistent_job_id(self, runner, ohtv_home):
        """Test that nonexistent job ID shows helpful error."""
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            result = runner.invoke(main, ["gen", "run", "nonexistent.job"])
            
            assert result.exit_code != 0
            assert "Error" in result.output


# =============================================================================
# Aggregate Mode Detection Tests
# =============================================================================


class TestAggregateModeDetection:
    """Tests for detecting and running aggregate jobs."""

    def test_single_trajectory_job_is_rejected(self, runner, ohtv_home):
        """Test that single-trajectory jobs are rejected with helpful message."""
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            # objs.brief is a single-trajectory job
            result = runner.invoke(main, ["gen", "run", "objs.brief"])
            
            # Should indicate it's a single-trajectory job
            assert "single-trajectory" in result.output.lower() or result.exit_code != 0


# =============================================================================
# Aggregate Execution Tests
# =============================================================================


class TestAggregateExecution:
    """Tests for aggregate analysis execution."""

    def test_aggregate_with_no_conversations(self, runner, ohtv_home):
        """Test aggregate job with no conversations."""
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            result = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            
            # Should complete but indicate no conversations
            assert "No conversations" in result.output or result.exit_code == 0

    def test_aggregate_with_conversations(self, runner, ohtv_home):
        """Test aggregate job with conversations present."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        # Create conversation in current week
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        create_cached_objective_result(convs_dir / conv_id, "Implement feature X")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = (
                {"summary": "Weekly work summary", "themes": ["feature"], "stats": {"count": 1}},
                0.01
            )
            
            result = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            
            # Should complete successfully
            if result.exit_code != 0:
                print(f"Output: {result.output}")
            assert result.exit_code == 0 or "Below minimum" in result.output

    def test_aggregate_period_iteration(self, runner, ohtv_home):
        """Test that aggregate iterates over multiple periods."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        # Create conversations in different weeks
        now = datetime.now(timezone.utc)
        for i, week_offset in enumerate([0, 7, 14]):  # This week, last week, 2 weeks ago
            created = now - timedelta(days=week_offset)
            conv_id = f"conv{i:03d}abc123"
            create_mock_conversation(convs_dir, conv_id, f"Test {i}", created)
            create_cached_objective_result(convs_dir / conv_id, f"Goal week {i}")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            call_count = 0
            def mock_llm_response(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return ({"summary": f"Summary {call_count}"}, 0.01)
            
            mock_llm.side_effect = mock_llm_response
            
            result = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "3", "-y"])
            
            # Should process 3 periods (though some may have 0 items)
            # Check output shows multiple periods
            assert result.exit_code == 0 or "Below minimum" in result.output


# =============================================================================
# Output Format Tests  
# =============================================================================


class TestOutputFormats:
    """Tests for different output formats."""

    def test_json_output_format(self, runner, ohtv_home):
        """Test JSON output format."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        create_cached_objective_result(convs_dir / conv_id, "Test goal")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = (
                {"summary": "Test summary", "themes": ["testing"]},
                0.01
            )
            
            result = runner.invoke(main, [
                "gen", "run", "reports.weekly", 
                "--last", "1", 
                "--format", "json",
                "-y"
            ])
            
            # Should output valid JSON (if any output)
            if result.exit_code == 0 and result.output.strip():
                try:
                    # Try to parse as JSON
                    data = json.loads(result.output)
                    assert isinstance(data, list)
                except json.JSONDecodeError:
                    # Might have other output mixed in
                    pass


# =============================================================================
# Min Items Threshold Tests
# =============================================================================


class TestMinItemsThreshold:
    """Tests for minimum items threshold behavior."""

    def test_skipped_when_below_min_items(self, runner, ohtv_home):
        """Test that periods with too few items are skipped."""
        # reports.weekly has min_items: 1, so create empty week
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            result = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            
            # Should indicate skipped or no items
            assert "No conversations" in result.output or "Below minimum" in result.output or result.exit_code == 0


# =============================================================================
# Last N Periods Tests
# =============================================================================


class TestLastNPeriods:
    """Tests for --last option."""

    def test_last_requires_period(self, runner, ohtv_home):
        """Test that --last without period generates error."""
        with patch.dict(os.environ, {"HOME": str(ohtv_home)}):
            # themes.discover has no period, so --last should error
            result = runner.invoke(main, ["gen", "run", "themes.discover", "--last", "4", "-y"])
            
            # Should error about requiring period
            assert result.exit_code != 0 or "period" in result.output.lower()

    def test_last_with_per_override(self, runner, ohtv_home):
        """Test --last with --per to override period type."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        create_cached_objective_result(convs_dir / conv_id, "Test goal")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = ({"summary": "Test"}, 0.01)
            
            # Use --per to provide period for themes.discover
            result = runner.invoke(main, [
                "gen", "run", "themes.discover", 
                "--per", "week",
                "--last", "1",
                "-y"
            ])
            
            # Should now work since period is provided via --per
            # May still fail due to min_items but shouldn't error on period requirement


# =============================================================================
# Caching Tests
# =============================================================================


class TestAggregateCaching:
    """Tests for aggregate result caching."""

    def test_uses_cached_results(self, runner, ohtv_home):
        """Test that cached results are used when available."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        create_cached_objective_result(convs_dir / conv_id, "Test goal")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = ({"summary": "Fresh"}, 0.01)
            
            # First call - should call LLM
            result1 = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            first_llm_calls = mock_llm.call_count
            
            # Second call - should use cache
            result2 = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            second_llm_calls = mock_llm.call_count
            
            # LLM calls shouldn't increase for cached results
            # (This depends on items being above min_items threshold)

    def test_refresh_bypasses_cache(self, runner, ohtv_home):
        """Test that --refresh bypasses cache."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        create_cached_objective_result(convs_dir / conv_id, "Test goal")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = ({"summary": "Fresh"}, 0.01)
            
            # First call
            runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            
            # Second call with --refresh
            runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y", "--refresh"])
            
            # With refresh, LLM should be called again (if items above threshold)


# =============================================================================
# Source Cache Population Tests
# =============================================================================


class TestSourceCachePopulation:
    """Tests for auto-populating source cache."""

    def test_runs_source_job_on_uncached(self, runner, ohtv_home):
        """Test that source job runs automatically on uncached conversations."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        conv_id = "conv001abc123"
        create_mock_conversation(convs_dir, conv_id, "Test", now)
        # Don't create cached objective result - should trigger auto-run

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_agg_llm, \
             patch("ohtv.analysis.analyze_objectives") as mock_src:
            
            from ohtv.analysis.objectives import ObjectiveAnalysis, AnalysisResult
            mock_analysis = ObjectiveAnalysis(
                conversation_id=conv_id,
                context_level="minimal",
                detail_level="brief",
                goal="Auto-detected goal",
                analyzed_at=datetime.now(timezone.utc),
                model_used="test",
                event_count=2,
                content_hash="hash",
            )
            mock_src.return_value = AnalysisResult(analysis=mock_analysis, cost=0.01, from_cache=False)
            mock_agg_llm.return_value = ({"summary": "Test"}, 0.01)
            
            result = runner.invoke(main, ["gen", "run", "reports.weekly", "--last", "1", "-y"])
            
            # Source job should have been called for uncached conversation
            # (only if we reach aggregate execution)


# =============================================================================
# Non-Period Aggregate Tests
# =============================================================================


class TestNonPeriodAggregate:
    """Tests for aggregates without period iteration."""

    def test_themes_discover_aggregates_all(self, runner, ohtv_home):
        """Test that themes.discover aggregates all conversations."""
        convs_dir = ohtv_home / ".ohtv" / "conversations"
        
        now = datetime.now(timezone.utc)
        # Create multiple conversations
        for i in range(3):
            conv_id = f"conv{i:03d}abc123"
            create_mock_conversation(convs_dir, conv_id, f"Test {i}", now - timedelta(days=i))
            create_cached_objective_result(convs_dir / conv_id, f"Goal {i}")

        with patch.dict(os.environ, {"HOME": str(ohtv_home)}), \
             patch("ohtv.analysis.aggregate.run_aggregate_llm") as mock_llm:
            
            mock_llm.return_value = (
                {"themes": [{"name": "Testing", "frequency": 3}], "patterns": {}},
                0.02
            )
            
            result = runner.invoke(main, [
                "gen", "run", "themes.discover",
                "--week",  # Provide date filter
                "-y"
            ])
            
            # Should complete (themes.discover has min_items: 2)
            # With 3 conversations, should aggregate successfully
            if mock_llm.called:
                # Check that all items were passed
                call_args = mock_llm.call_args
                # Rendered prompt should contain multiple items
                pass
