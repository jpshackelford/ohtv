"""Tests for ohtv.analysis.transcript module."""

import pytest

from ohtv.analysis.transcript import (
    extract_content,
    extract_message_content,
    extract_action_summary,
    build_transcript_from_context,
    format_transcript,
)
from ohtv.prompts.metadata import ContextLevel, EventFilter


class TestExtractMessageContent:
    """Tests for extract_message_content function."""

    def test_extracts_from_llm_message_content_list(self):
        """Test extraction from standard llm_message.content format."""
        event = {
            "llm_message": {
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "World"},
                ]
            }
        }
        result = extract_message_content(event)
        assert result == "Hello\nWorld"

    def test_extracts_from_string_content(self):
        """Test extraction when content is a string."""
        event = {"llm_message": {"content": "Simple message"}}
        result = extract_message_content(event)
        assert result == "Simple message"

    def test_fallback_to_content_field(self):
        """Test fallback to top-level content field."""
        event = {"content": "Fallback content"}
        result = extract_message_content(event)
        assert result == "Fallback content"

    def test_fallback_to_message_field(self):
        """Test fallback to message field."""
        event = {"message": "Message field"}
        result = extract_message_content(event)
        assert result == "Message field"

    def test_empty_content(self):
        """Test handling of empty content."""
        event = {}
        result = extract_message_content(event)
        assert result == ""


class TestExtractActionSummary:
    """Tests for extract_action_summary function."""

    def test_terminal_action(self):
        """Test terminal action summary."""
        event = {
            "tool_name": "terminal",
            "action": {"command": "git status"},
        }
        result = extract_action_summary(event)
        assert result == "[Terminal] git status"

    def test_terminal_truncates_long_command(self):
        """Test that long terminal commands are truncated."""
        long_cmd = "x" * 150
        event = {
            "tool_name": "terminal",
            "action": {"command": long_cmd},
        }
        result = extract_action_summary(event)
        assert len(result) == len("[Terminal] ") + 100
        assert result.startswith("[Terminal] xxx")

    def test_file_editor_action(self):
        """Test file editor action summary."""
        event = {
            "tool_name": "file_editor",
            "action": {"command": "str_replace", "path": "/src/main.py"},
        }
        result = extract_action_summary(event)
        assert result == "[Edit] str_replace /src/main.py"

    def test_finish_action(self):
        """Test finish action summary."""
        event = {
            "tool_name": "finish",
            "action": {"message": "Task completed successfully"},
        }
        result = extract_action_summary(event)
        assert result == "[Finish] Task completed successfully"

    def test_finish_truncates_long_message(self):
        """Test that long finish messages are truncated."""
        long_msg = "x" * 400
        event = {
            "tool_name": "finish",
            "action": {"message": long_msg},
        }
        result = extract_action_summary(event)
        assert len(result) == len("[Finish] ") + 300

    def test_unknown_tool(self):
        """Test unknown tool action summary."""
        event = {
            "tool_name": "custom_tool",
            "action": {"foo": "bar"},
        }
        result = extract_action_summary(event)
        assert result == "[custom_tool]"

    def test_handles_none_action(self):
        """Test handling of None action field."""
        event = {"tool_name": "terminal", "action": None}
        result = extract_action_summary(event)
        assert result == "[Terminal] "

    def test_handles_missing_action(self):
        """Test handling of missing action field."""
        event = {"tool_name": "terminal"}
        result = extract_action_summary(event)
        assert result == "[Terminal] "


class TestExtractContent:
    """Tests for extract_content function."""

    def test_message_event_extraction(self):
        """Test content extraction from MessageEvent."""
        event = {
            "kind": "MessageEvent",
            "llm_message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        result = extract_content(event)
        assert result == "Hello"

    def test_action_event_extraction(self):
        """Test content extraction from ActionEvent."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "ls"},
        }
        result = extract_content(event)
        assert result == "[Terminal] ls"

    def test_truncation_without_limit(self):
        """Test that no truncation occurs when max_length is 0."""
        long_text = "x" * 2000
        event = {
            "kind": "MessageEvent",
            "llm_message": {"content": long_text},
        }
        result = extract_content(event, max_length=0)
        assert len(result) == 2000
        assert not result.endswith("... [truncated]")

    def test_truncation_with_limit(self):
        """Test that truncation occurs when content exceeds max_length."""
        long_text = "x" * 2000
        event = {
            "kind": "MessageEvent",
            "llm_message": {"content": long_text},
        }
        result = extract_content(event, max_length=100)
        assert len(result) == 100 + len("... [truncated]")
        assert result.endswith("... [truncated]")

    def test_no_truncation_when_below_limit(self):
        """Test that no truncation occurs when content is below max_length."""
        short_text = "Short text"
        event = {
            "kind": "MessageEvent",
            "llm_message": {"content": short_text},
        }
        result = extract_content(event, max_length=100)
        assert result == short_text
        assert not result.endswith("... [truncated]")


class TestBuildTranscriptFromContext:
    """Tests for build_transcript_from_context function."""

    def test_includes_matching_events(self):
        """Test that events matching include filters are included."""
        context = ContextLevel(
            number=1,
            name="minimal",
            include=[EventFilter(source="user", kind="MessageEvent")],
        )
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": "Hello"},
            },
            {
                "source": "agent",
                "kind": "MessageEvent",
                "llm_message": {"content": "Hi"},
            },
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["text"] == "Hello"

    def test_excludes_non_matching_events(self):
        """Test that events not matching include filters are excluded."""
        context = ContextLevel(
            number=1,
            name="minimal",
            include=[EventFilter(source="user", kind="MessageEvent")],
        )
        events = [
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            }
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 0

    def test_exclude_filter_removes_matching_events(self):
        """Test that exclude filters remove otherwise matching events."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],  # Match all
            exclude=[EventFilter(source="agent", kind="MessageEvent")],
        )
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": "User message"},
            },
            {
                "source": "agent",
                "kind": "MessageEvent",
                "llm_message": {"content": "Agent message"},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "finish",
                "action": {"message": "Done"},
            },
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "action"

    def test_applies_truncation(self):
        """Test that truncation is applied based on context.truncate."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],
            truncate=10,
        )
        long_text = "x" * 100
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": long_text},
            }
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 1
        assert result[0]["text"].endswith("... [truncated]")
        assert len(result[0]["text"]) == 10 + len("... [truncated]")

    def test_role_mapping_for_messages(self):
        """Test that MessageEvent roles are mapped correctly."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],
        )
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": "User"},
            },
            {
                "source": "agent",
                "kind": "MessageEvent",
                "llm_message": {"content": "Agent"},
            },
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_role_mapping_for_actions(self):
        """Test that ActionEvent role is mapped correctly."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],
        )
        events = [
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            }
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 1
        assert result[0]["role"] == "action"

    def test_skips_empty_content(self):
        """Test that events with empty content are skipped."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],
        )
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": ""},
            }
        ]
        result = build_transcript_from_context(events, context)
        assert len(result) == 0

    def test_multiple_include_filters_or_logic(self):
        """Test that multiple include filters use OR logic."""
        context = ContextLevel(
            number=1,
            name="test",
            include=[
                EventFilter(source="user", kind="MessageEvent"),
                EventFilter(source="agent", kind="ActionEvent", tool="finish"),
            ],
        )
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": "User message"},
            },
            {
                "source": "agent",
                "kind": "MessageEvent",
                "llm_message": {"content": "Agent message"},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "finish",
                "action": {"message": "Done"},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            },
        ]
        result = build_transcript_from_context(events, context)
        # Should include: user message, finish action (but not agent message or terminal action)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "action"


class TestFormatTranscript:
    """Tests for format_transcript function."""

    def test_formats_single_item(self):
        """Test formatting of a single transcript item."""
        items = [{"role": "user", "text": "Hello"}]
        result = format_transcript(items)
        assert result == "[USER]: Hello"

    def test_formats_multiple_items(self):
        """Test formatting of multiple transcript items."""
        items = [
            {"role": "user", "text": "Hello"},
            {"role": "assistant", "text": "Hi there"},
            {"role": "action", "text": "[Finish] Done"},
        ]
        result = format_transcript(items)
        expected = "[USER]: Hello\n\n[ASSISTANT]: Hi there\n\n[ACTION]: [Finish] Done"
        assert result == expected

    def test_uppercases_roles(self):
        """Test that roles are uppercased."""
        items = [{"role": "user", "text": "Test"}]
        result = format_transcript(items)
        assert result.startswith("[USER]:")

    def test_empty_items(self):
        """Test formatting of empty items list."""
        items = []
        result = format_transcript(items)
        assert result == ""
