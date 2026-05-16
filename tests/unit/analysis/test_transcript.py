"""Tests for ohtv.analysis.transcript module."""

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
        """Test terminal action summary without agent-provided summary."""
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
        """Test file editor action summary without agent-provided summary."""
        event = {
            "tool_name": "file_editor",
            "action": {"command": "str_replace", "path": "/src/main.py"},
        }
        result = extract_action_summary(event)
        assert result == "[Edit] str_replace /src/main.py"

    def test_finish_action(self):
        """Test finish action summary without agent-provided summary."""
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
        """Test unknown tool action summary without agent-provided summary."""
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

    # Tests for agent-provided summary field (Issue #58)

    def test_prefers_agent_provided_summary(self):
        """Test that agent-provided summary is preferred over raw command."""
        event = {
            "tool_name": "terminal",
            "summary": "Check git status",
            "action": {"command": "cd /workspace && git status"},
        }
        result = extract_action_summary(event)
        assert "Check git status" in result
        assert "cd /workspace" not in result
        assert result == "[Terminal] Check git status"

    def test_summary_with_file_editor(self):
        """Test that agent-provided summary works for file_editor actions."""
        event = {
            "tool_name": "file_editor",
            "summary": "Add error handling to main function",
            "action": {"command": "str_replace", "path": "/src/main.py"},
        }
        result = extract_action_summary(event)
        assert result == "[File_Editor] Add error handling to main function"
        assert "str_replace" not in result

    def test_summary_with_finish(self):
        """Test that agent-provided summary works for finish actions."""
        event = {
            "tool_name": "finish",
            "summary": "Completed PR review with fixes",
            "action": {
                "message": "I have completed the review and fixed all issues..."
            },
        }
        result = extract_action_summary(event)
        assert result == "[Finish] Completed PR review with fixes"
        assert "review and fixed" not in result

    def test_summary_with_custom_tool(self):
        """Test that agent-provided summary works for unknown tools."""
        event = {
            "tool_name": "browser_click",
            "summary": "Click submit button",
            "action": {"index": 5},
        }
        result = extract_action_summary(event)
        assert result == "[Browser_Click] Click submit button"

    def test_include_command_with_summary(self):
        """Test include_command appends full command when summary exists."""
        event = {
            "tool_name": "terminal",
            "summary": "Check git status",
            "action": {"command": "cd /workspace && git status"},
        }
        result = extract_action_summary(event, include_command=True)
        assert "Check git status" in result
        assert "cd /workspace && git status" in result
        assert (
            result
            == "[Terminal] Check git status\n  Command: cd /workspace && git status"
        )

    def test_include_command_without_summary(self):
        """Test include_command has no effect when no summary exists."""
        event = {
            "tool_name": "terminal",
            "action": {"command": "git status"},
        }
        result = extract_action_summary(event, include_command=True)
        # Should just return normal fallback - no command appended
        assert result == "[Terminal] git status"
        assert "Command:" not in result

    def test_include_command_only_for_terminal(self):
        """Test include_command only appends command for terminal actions."""
        event = {
            "tool_name": "file_editor",
            "summary": "View config file",
            "action": {"command": "view", "path": "/etc/config.yaml"},
        }
        result = extract_action_summary(event, include_command=True)
        # Should not include Command: line for non-terminal
        assert result == "[File_Editor] View config file"
        assert "Command:" not in result

    def test_include_command_empty_command(self):
        """Test include_command handles empty command gracefully."""
        event = {
            "tool_name": "terminal",
            "summary": "Prepare terminal",
            "action": {"command": ""},
        }
        result = extract_action_summary(event, include_command=True)
        assert result == "[Terminal] Prepare terminal"
        assert "Command:" not in result

    def test_fallback_when_no_summary(self):
        """Test fallback behavior when no summary field exists."""
        event = {
            "tool_name": "terminal",
            "action": {"command": "ls -la"},
        }
        result = extract_action_summary(event)
        assert result == "[Terminal] ls -la"

    def test_fallback_when_summary_is_none(self):
        """Test fallback when summary is explicitly None."""
        event = {
            "tool_name": "terminal",
            "summary": None,
            "action": {"command": "ls -la"},
        }
        result = extract_action_summary(event)
        assert result == "[Terminal] ls -la"

    def test_fallback_when_summary_is_empty(self):
        """Test fallback when summary is empty string."""
        event = {
            "tool_name": "terminal",
            "summary": "",
            "action": {"command": "ls -la"},
        }
        result = extract_action_summary(event)
        # Empty string is falsy, so should fallback
        assert result == "[Terminal] ls -la"


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
        """Test content extraction from ActionEvent without summary."""
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

    # Tests for include_command behavior based on max_length (Issue #58)

    def test_action_with_summary_no_truncation(self):
        """Test that full context (max_length=0) includes command with summary."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "summary": "Check git status",
            "action": {"command": "cd /workspace && git status"},
        }
        result = extract_content(event, max_length=0)
        assert "Check git status" in result
        assert "cd /workspace && git status" in result

    def test_action_with_summary_with_truncation(self):
        """Test that truncated context (max_length>0) excludes command."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "summary": "Check git status",
            "action": {"command": "cd /workspace && git status"},
        }
        result = extract_content(event, max_length=500)
        assert "Check git status" in result
        assert "cd /workspace" not in result

    def test_action_without_summary_no_truncation(self):
        """Test fallback behavior without summary in full context mode."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "ls -la"},
        }
        result = extract_content(event, max_length=0)
        assert result == "[Terminal] ls -la"
        # No "Command:" line because no summary exists
        assert "Command:" not in result


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
