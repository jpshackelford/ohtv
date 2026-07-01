"""Tests for message extraction utilities."""

import pytest

from ohtv_utils.extraction.messages import (
    DEFAULT_OBSERVATION_TRUNCATE,
    extract_action_summary,
    extract_message_content,
    extract_observation_content,
)


class TestExtractMessageContent:
    """Tests for extract_message_content function."""

    def test_structured_content_list(self):
        """Extract text from structured content list."""
        event = {
            "llm_message": {
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "World"},
                ]
            }
        }
        assert extract_message_content(event) == "Hello\nWorld"

    def test_simple_string_content(self):
        """Extract text from simple string content."""
        event = {"llm_message": {"content": "Hello World"}}
        assert extract_message_content(event) == "Hello World"

    def test_fallback_to_top_level_content(self):
        """Fall back to top-level content field."""
        event = {"content": "Fallback content"}
        assert extract_message_content(event) == "Fallback content"

    def test_fallback_to_message_field(self):
        """Fall back to message field."""
        event = {"message": "Message field content"}
        assert extract_message_content(event) == "Message field content"

    def test_empty_content(self):
        """Return empty string for missing content."""
        event = {}
        assert extract_message_content(event) == ""

    def test_ignore_non_text_items(self):
        """Ignore non-text content items."""
        event = {
            "llm_message": {
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "image", "url": "http://example.com/img.png"},
                    {"type": "text", "text": "World"},
                ]
            }
        }
        assert extract_message_content(event) == "Hello\nWorld"

    def test_malformed_content_list(self):
        """Handle malformed content list gracefully."""
        event = {"llm_message": {"content": [None, "not a dict", {"type": "text"}]}}
        assert extract_message_content(event) == ""


class TestExtractActionSummary:
    """Tests for extract_action_summary function."""

    def test_agent_provided_summary(self):
        """Use agent-provided summary when available."""
        event = {
            "tool_name": "terminal",
            "summary": "List all files",
            "action": {"command": "ls -la"},
        }
        assert extract_action_summary(event) == "[Terminal] List all files"

    def test_terminal_action_fallback(self):
        """Extract terminal command when no summary."""
        event = {"tool_name": "terminal", "action": {"command": "git status"}}
        assert extract_action_summary(event) == "[Terminal] git status"

    def test_terminal_command_truncation(self):
        """Truncate long commands to 100 chars."""
        long_cmd = "a" * 150
        event = {"tool_name": "terminal", "action": {"command": long_cmd}}
        result = extract_action_summary(event)
        assert len(result) == len("[Terminal] ") + 100

    def test_file_editor_action(self):
        """Extract file editor command and path."""
        event = {
            "tool_name": "file_editor",
            "action": {"command": "view", "path": "/tmp/test.py"},
        }
        assert extract_action_summary(event) == "[Edit] view /tmp/test.py"

    def test_finish_action(self):
        """Extract finish message."""
        event = {
            "tool_name": "finish",
            "action": {"message": "Task completed successfully"},
        }
        assert extract_action_summary(event) == "[Finish] Task completed successfully"

    def test_finish_message_truncation(self):
        """Truncate long finish messages to 300 chars."""
        long_msg = "x" * 400
        event = {"tool_name": "finish", "action": {"message": long_msg}}
        result = extract_action_summary(event)
        assert len(result) == len("[Finish] ") + 300

    def test_unknown_tool(self):
        """Handle unknown tool names."""
        event = {"tool_name": "unknown_tool", "action": {}}
        assert extract_action_summary(event) == "[unknown_tool]"

    def test_include_command_flag(self):
        """Include full command when include_command=True."""
        event = {
            "tool_name": "terminal",
            "summary": "Check status",
            "action": {"command": "git status"},
        }
        result = extract_action_summary(event, include_command=True)
        assert result == "[Terminal] Check status\n  Command: git status"

    def test_include_command_without_summary(self):
        """Don't append command if no summary present."""
        event = {"tool_name": "terminal", "action": {"command": "ls"}}
        result = extract_action_summary(event, include_command=True)
        assert result == "[Terminal] ls"


class TestExtractObservationContent:
    """Tests for extract_observation_content function."""

    def test_string_content_with_exit_code(self):
        """Extract string content with exit code."""
        event = {"observation": {"content": "Command output", "exit_code": 0}}
        assert extract_observation_content(event) == "(exit=0) Command output"

    def test_string_content_without_exit_code(self):
        """Extract string content without exit code."""
        event = {"observation": {"content": "Plain output"}}
        assert extract_observation_content(event) == "Plain output"

    def test_structured_content_list(self):
        """Extract from structured content list."""
        event = {
            "observation": {
                "content": [
                    {"type": "text", "text": "Line 1"},
                    {"type": "text", "text": "Line 2"},
                ]
            }
        }
        assert extract_observation_content(event) == "Line 1\nLine 2"

    def test_truncation(self):
        """Truncate long content."""
        long_content = "x" * 1000
        event = {"observation": {"content": long_content}}
        result = extract_observation_content(event, max_length=100)
        assert result == "x" * 100 + "... [truncated]"

    def test_no_truncation_with_zero_max(self):
        """Don't truncate when max_length=0."""
        long_content = "x" * 1000
        event = {"observation": {"content": long_content}}
        result = extract_observation_content(event, max_length=0)
        assert result == long_content

    def test_default_truncation_length(self):
        """Use default truncation length."""
        long_content = "y" * 2000
        event = {"observation": {"content": long_content}}
        result = extract_observation_content(event)
        expected_len = DEFAULT_OBSERVATION_TRUNCATE + len("... [truncated]")
        assert len(result) == expected_len

    def test_exit_code_only(self):
        """Show exit code even without content."""
        event = {"observation": {"content": "", "exit_code": 1}}
        assert extract_observation_content(event) == "(exit=1)"

    def test_fallback_to_top_level_fields(self):
        """Fall back to top-level content/message."""
        event = {"content": "Top-level content"}
        assert extract_observation_content(event) == "Top-level content"

    def test_empty_observation(self):
        """Return empty string for missing observation."""
        event = {}
        assert extract_observation_content(event) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
