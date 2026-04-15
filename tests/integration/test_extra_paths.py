"""Integration tests for extra conversation paths feature.

These tests validate end-to-end CLI behavior when configuring additional
conversation search paths via environment variable.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ohtv.cli import main


def create_mock_conversation(
    conv_dir: Path,
    conv_id: str,
    title: str = "Test conversation",
    event_count: int = 2,
) -> None:
    """Create a minimal mock conversation directory structure.

    Args:
        conv_dir: Parent directory for conversations
        conv_id: Conversation ID (directory name, no dashes)
        title: Title for the conversation
        event_count: Number of mock events to create
    """
    conv_path = conv_dir / conv_id
    conv_path.mkdir(parents=True, exist_ok=True)

    # Create base_state.json
    base_state = {
        "id": conv_id,
        "title": title,
        "selected_repository": "test/repo",
        "selected_branch": "main",
        "created_at": "2026-04-01T10:00:00.000000Z",
        "updated_at": "2026-04-01T10:30:00.000000Z",
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
        event = {
            "id": f"event_{i}",
            "timestamp": f"2026-04-01T10:{i:02d}:00.000000",
            "source": "user" if i % 2 == 0 else "agent",
            "kind": "MessageEvent",
            "llm_message": {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": [{"type": "text", "text": f"Message {i}"}],
            },
        }
        event_file = events_dir / f"event-{i:05d}-{chr(97 + i)}.json"
        event_file.write_text(json.dumps(event))


class TestListWithExtraPaths:
    """Tests for `list` command with extra conversation paths."""

    def test_list_shows_conversations_from_extra_path(self, tmp_path):
        """Conversations from extra paths appear in list output."""
        # Create a mock conversation in an extra path
        extra_path = tmp_path / "my_experiments"
        extra_path.mkdir()
        create_mock_conversation(extra_path, "abc123def456", title="Extra path test")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                # Ensure default paths don't interfere
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A"])

        assert result.exit_code == 0
        # Verify the conversation appears
        assert "abc123" in result.output or "abc123d" in result.output
        assert "Extra path test" in result.output

    def test_list_shows_correct_source_name(self, tmp_path):
        """Source name is derived from directory basename, not 'local' or 'cloud'."""
        extra_path = tmp_path / "my_experiments"
        extra_path.mkdir()
        create_mock_conversation(extra_path, "aaa111bbb222", title="Source name test")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            # Use JSON format for precise verification of source name
            result = runner.invoke(main, ["list", "-A", "-F", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        # Source should be 'my_experiments'
        assert data[0]["source"] == "my_experiments"
        # Should NOT be 'local' or 'cloud'
        assert data[0]["source"] not in ("local", "cloud")

    def test_list_with_multiple_extra_paths(self, tmp_path):
        """Multiple extra paths are all searched."""
        # Create two extra paths with conversations
        path1 = tmp_path / "experiments"
        path1.mkdir()
        create_mock_conversation(path1, "exp111222333", title="Experiment 1")

        path2 = tmp_path / "archive"
        path2.mkdir()
        create_mock_conversation(path2, "arc444555666", title="Archive conv")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{path1}:{path2}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A"])

        assert result.exit_code == 0
        # Both conversations should appear
        assert "Experiment 1" in result.output
        assert "Archive conv" in result.output

    def test_list_json_format_includes_extra_path_source(self, tmp_path):
        """JSON output includes correct source name for extra path conversations."""
        extra_path = tmp_path / "test_data"
        extra_path.mkdir()
        create_mock_conversation(extra_path, "json111222333", title="JSON test")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A", "-F", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # JSON output is a list of conversations directly
        assert isinstance(data, list)

        # Find our conversation
        conv = next(
            (c for c in data if "json111" in c.get("id", "")),
            None,
        )
        assert conv is not None
        assert conv["source"] == "test_data"


class TestShowWithExtraPaths:
    """Tests for `show` command with extra conversation paths."""

    def test_show_finds_conversation_in_extra_path(self, tmp_path):
        """Show command can find and display a conversation from an extra path."""
        extra_path = tmp_path / "experiments"
        extra_path.mkdir()
        create_mock_conversation(
            extra_path,
            "show111222333",
            title="Show test conversation",
            event_count=3,
        )

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            # Use stats-only mode for simpler verification
            result = runner.invoke(main, ["show", "show111222333", "-S"])

        assert result.exit_code == 0
        assert "Show test conversation" in result.output or "show111" in result.output

    def test_show_with_dashed_id(self, tmp_path):
        """Show command finds conversation using ID with dashes."""
        extra_path = tmp_path / "experiments"
        extra_path.mkdir()
        # Directory name without dashes
        create_mock_conversation(extra_path, "abcd1234efgh5678", title="Dashed ID test")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            # Use dashed ID format (like what's displayed in list)
            result = runner.invoke(main, ["show", "abcd1234-efgh-5678", "-S"])

        assert result.exit_code == 0

    def test_show_displays_events_from_extra_path(self, tmp_path):
        """Show command displays event content from extra path conversations."""
        extra_path = tmp_path / "experiments"
        extra_path.mkdir()
        create_mock_conversation(
            extra_path,
            "events11223344",
            title="Events test",
            event_count=4,
        )

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            # Show with user messages
            result = runner.invoke(main, ["show", "events11223344", "-u"])

        assert result.exit_code == 0
        # Should show message content
        assert "Message" in result.output

    def test_show_not_found_error(self, tmp_path):
        """Show command returns error for non-existent conversation."""
        extra_path = tmp_path / "experiments"
        extra_path.mkdir()

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": str(extra_path),
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["show", "nonexistent123456"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestSourceNameCollisions:
    """Tests for source name collision handling in actual CLI output."""

    def test_collision_handling_in_list_output(self, tmp_path):
        """Source names with collisions get numeric suffixes in CLI output."""
        # Create two paths with the same basename
        path1 = tmp_path / "dir1" / "experiments"
        path1.mkdir(parents=True)
        create_mock_conversation(path1, "coll111222333", title="First experiments")

        path2 = tmp_path / "dir2" / "experiments"
        path2.mkdir(parents=True)
        create_mock_conversation(path2, "coll444555666", title="Second experiments")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{path1}:{path2}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            # Use JSON for precise verification
            result = runner.invoke(main, ["list", "-A", "-F", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Both conversations should appear
        assert len(data) == 2
        sources = {c["source"] for c in data}
        # Source names should show collision handling
        # First path: 'experiments', second path: 'experiments_1'
        assert "experiments" in sources
        assert "experiments_1" in sources

    def test_collision_handling_in_json_output(self, tmp_path):
        """JSON output shows unique source names for colliding paths."""
        path1 = tmp_path / "a" / "data"
        path1.mkdir(parents=True)
        create_mock_conversation(path1, "json111aaaaaa", title="Data 1")

        path2 = tmp_path / "b" / "data"
        path2.mkdir(parents=True)
        create_mock_conversation(path2, "json222bbbbbb", title="Data 2")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{path1}:{path2}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A", "-F", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # JSON output is a list of conversations directly
        assert isinstance(data, list)

        sources = {c["source"] for c in data}
        # Should have 'data' and 'data_1' (or similar unique names)
        assert len(sources) == 2
        assert "data" in sources
        assert "data_1" in sources

    def test_mixed_case_and_separator_normalization(self, tmp_path):
        """Source names are normalized (lowercase, underscores) for collision detection."""
        path1 = tmp_path / "dir1" / "My-Data"
        path1.mkdir(parents=True)
        create_mock_conversation(path1, "norm111222333", title="Conv 1")

        path2 = tmp_path / "dir2" / "my data"
        path2.mkdir(parents=True)
        create_mock_conversation(path2, "norm444555666", title="Conv 2")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{path1}:{path2}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A", "-F", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # JSON output is a list of conversations directly
        assert isinstance(data, list)

        sources = {c["source"] for c in data}
        # Both normalize to 'my_data', so second should be 'my_data_1'
        assert "my_data" in sources
        assert "my_data_1" in sources


class TestExtraPathEdgeCases:
    """Tests for edge cases with extra conversation paths."""

    def test_nonexistent_path_is_skipped(self, tmp_path):
        """Non-existent paths are skipped without error."""
        # Create one valid path
        valid_path = tmp_path / "valid"
        valid_path.mkdir()
        create_mock_conversation(valid_path, "valid1112223", title="Valid conv")

        # Reference a non-existent path
        nonexistent = tmp_path / "does_not_exist"

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{valid_path}:{nonexistent}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A"])

        # Should succeed despite non-existent path
        assert result.exit_code == 0
        assert "Valid conv" in result.output

    def test_empty_extra_path_list(self, tmp_path):
        """Empty extra paths configuration works correctly."""
        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": "",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A"])

        # Should succeed with empty extra paths
        assert result.exit_code == 0

    def test_path_is_file_not_directory(self, tmp_path):
        """File paths (not directories) are skipped."""
        # Create a file instead of directory
        fake_file = tmp_path / "not_a_dir"
        fake_file.write_text("not a directory")

        # Create a valid path too
        valid_path = tmp_path / "valid"
        valid_path.mkdir()
        create_mock_conversation(valid_path, "validfile123", title="Valid conv")

        runner = CliRunner()
        with patch.dict(
            os.environ,
            {
                "OHTV_EXTRA_CONVERSATION_PATHS": f"{fake_file}:{valid_path}",
                "HOME": str(tmp_path / "fake_home"),
            },
        ):
            result = runner.invoke(main, ["list", "-A"])

        # Should succeed with file path skipped
        assert result.exit_code == 0
        assert "Valid conv" in result.output
