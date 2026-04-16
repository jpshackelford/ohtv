"""Tests for ohtv.analysis.objectives module."""

import pytest

from ohtv.analysis.objectives import extract_action_summary, build_transcript


class TestExtractActionSummary:
    """Tests for extract_action_summary function."""

    def test_handles_none_action(self):
        """Action can be explicitly None in some event formats."""
        event = {"tool_name": "file_editor", "action": None}
        result = extract_action_summary(event)
        assert result == "[Edit]  "

    def test_handles_missing_action(self):
        """Action key may be missing entirely."""
        event = {"tool_name": "terminal"}
        result = extract_action_summary(event)
        assert result == "[Terminal] "

    def test_terminal_action(self):
        event = {
            "tool_name": "terminal",
            "action": {"command": "git status"},
        }
        result = extract_action_summary(event)
        assert result == "[Terminal] git status"

    def test_terminal_truncates_long_command(self):
        long_cmd = "x" * 150
        event = {
            "tool_name": "terminal",
            "action": {"command": long_cmd},
        }
        result = extract_action_summary(event)
        assert len(result) == len("[Terminal] ") + 100

    def test_file_editor_action(self):
        event = {
            "tool_name": "file_editor",
            "action": {"command": "str_replace", "path": "/src/main.py"},
        }
        result = extract_action_summary(event)
        assert result == "[Edit] str_replace /src/main.py"

    def test_finish_action(self):
        event = {
            "tool_name": "finish",
            "action": {"message": "Task completed successfully"},
        }
        result = extract_action_summary(event)
        assert result == "[Finish] Task completed successfully"

    def test_unknown_tool(self):
        event = {
            "tool_name": "some_custom_tool",
            "action": {"foo": "bar"},
        }
        result = extract_action_summary(event)
        assert result == "[some_custom_tool]"


class TestBuildTranscript:
    """Tests for build_transcript function."""

    def test_handles_action_with_none_action_field(self):
        """Events with action=None should not crash transcript building."""
        events = [
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "file_editor",
                "action": None,
            }
        ]
        # Should not raise AttributeError
        result = build_transcript(events, context="full")
        assert len(result) == 1
        assert result[0]["role"] == "action"

    def test_minimal_context_excludes_actions(self):
        """Minimal context only includes user messages."""
        events = [
            # User message with llm_message.content format (actual event structure)
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "Hello"}]},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            },
        ]
        result = build_transcript(events, context="minimal")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["text"] == "Hello"

    def test_full_context_includes_actions(self):
        """Full context includes all actions."""
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "Hello"}]},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            },
        ]
        result = build_transcript(events, context="full")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "action"
