"""Tests for ohtv.analysis.objectives module."""

from ohtv.analysis.objectives import (
    extract_action_summary,
    build_transcript,
    _has_action_events,
)


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

    def test_numeric_context_string_not_recognized(self):
        """Regression test: numeric string "3" was not recognized as "full".
        
        This documents the bug where -c 3 was passed through as "3" instead
        of being converted to "full", causing actions to be silently dropped.
        The fix is in _normalize_context_level() in cli.py.
        
        See: https://github.com/jpshackelford/ohtv/issues/61
        """
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "test"}]},
            },
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "ls"},
            },
        ]
        # Bug behavior: "3" is NOT recognized, falls through to minimal-like behavior
        result_numeric = build_transcript(events, context="3")
        # Expected behavior with "full": actions are captured
        result_full = build_transcript(events, context="full")
        
        # With the bug, "3" would return 0-1 items (only user message)
        # but "full" correctly returns 2 items (user message + action)
        assert len(result_numeric) < len(result_full), (
            "Regression: numeric string '3' should not be recognized by "
            "_legacy_build_transcript - CLI must normalize before calling"
        )


class TestHasActionEvents:
    """Tests for _has_action_events helper function."""

    def test_returns_true_when_actions_exist(self):
        """Should return True when agent ActionEvents exist."""
        events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "file_editor"},
        ]
        assert _has_action_events(events) is True

    def test_returns_false_when_no_actions(self):
        """Should return False when no ActionEvents exist."""
        events = [
            {"source": "user", "kind": "MessageEvent"},
            {"source": "agent", "kind": "MessageEvent"},
        ]
        assert _has_action_events(events) is False

    def test_returns_false_for_empty_events(self):
        """Should return False for empty event list."""
        assert _has_action_events([]) is False

    def test_ignores_user_action_events(self):
        """Should ignore ActionEvents from user (only agent actions count)."""
        events = [
            {"source": "user", "kind": "ActionEvent", "tool_name": "terminal"},
        ]
        assert _has_action_events(events) is False

    def test_requires_both_source_and_kind(self):
        """Should only match when both source=agent AND kind=ActionEvent."""
        events = [
            {"source": "agent", "kind": "MessageEvent"},  # Wrong kind
            {"source": "user", "kind": "ActionEvent"},    # Wrong source
            {"source": "agent"},                           # Missing kind
            {"kind": "ActionEvent"},                       # Missing source
        ]
        assert _has_action_events(events) is False


class TestContextAutoPromotion:
    """Tests for automatic context level promotion in analyze_objectives.
    
    Worker conversations (orchestrator-spawned) have no user messages but do
    have meaningful actions. The analyze_objectives function should auto-promote
    the context level when the transcript is empty but actions exist.
    """

    def test_minimal_yields_empty_for_worker_conversation(self):
        """Minimal context yields no content for conversations without user messages."""
        # Worker conversation: only agent actions, no user messages
        events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git status"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "file_editor", "action": {"command": "view", "path": "/test.py"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "finish", "action": {"message": "Done"}},
        ]
        # Minimal context only extracts user messages
        result_minimal = build_transcript(events, context="minimal")
        assert len(result_minimal) == 0, "Minimal context should yield 0 items for worker conversations"
        
        # Default context extracts finish action
        result_default = build_transcript(events, context="default")
        assert len(result_default) == 1, "Default context should yield 1 item (finish action)"
        
        # Full context extracts all actions
        result_full = build_transcript(events, context="full")
        assert len(result_full) == 3, "Full context should yield 3 items (all actions)"

    def test_default_yields_finish_only_for_worker(self):
        """Default context extracts only finish action for worker conversations."""
        events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "ls"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "pwd"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "finish", "action": {"message": "Complete"}},
        ]
        result = build_transcript(events, context="default")
        assert len(result) == 1
        assert result[0]["role"] == "action"
        assert "Complete" in result[0]["text"]

    def test_full_context_captures_all_actions(self):
        """Full context captures all action summaries."""
        events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git status"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "file_editor", "action": {"command": "view", "path": "/test.py"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "python test.py"}},
        ]
        result = build_transcript(events, context="full")
        assert len(result) == 3
        
    def test_worker_without_finish_needs_full_context(self):
        """Worker conversations without finish action need full context."""
        # Some worker conversations may not complete with a finish action
        events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git push"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "echo done"}},
        ]
        # Minimal: empty
        assert len(build_transcript(events, context="minimal")) == 0
        # Default: empty (no finish)
        assert len(build_transcript(events, context="default")) == 0
        # Full: captures all
        assert len(build_transcript(events, context="full")) == 2


class TestAnalyzeObjectivesAutoPromotion:
    """Tests for auto-promotion logic in analyze_objectives.
    
    Worker conversations (orchestrator-spawned) have no user messages but do
    have meaningful actions. The analyze_objectives function should auto-promote
    the context level when the transcript is empty but actions exist.
    
    Note: Full integration tests with LLM calls are in tests/integration/.
    These unit tests verify the preconditions for auto-promotion.
    """

    def test_promotion_should_trigger_when_minimal_empty_with_actions(self):
        """Verify conditions that trigger auto-promotion.
        
        When context=minimal produces empty transcript AND actions exist,
        the auto-promotion logic should kick in.
        """
        # Worker conversation: only agent actions, no user messages
        worker_events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git status"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "finish", "action": {"message": "Done"}},
        ]
        
        # Minimal context produces empty transcript
        minimal_transcript = build_transcript(worker_events, context="minimal")
        assert len(minimal_transcript) == 0, "Minimal should be empty for worker conv"
        
        # But actions exist
        assert _has_action_events(worker_events), "Should detect agent actions"
        
        # Therefore auto-promotion should trigger (tested via integration tests)

    def test_promotion_stops_at_default_when_finish_exists(self):
        """Verify that default context captures finish action.
        
        If default context produces content (finish action), promotion can stop there.
        """
        worker_events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git status"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "finish", "action": {"message": "Done"}},
        ]
        
        # Default context captures finish
        default_transcript = build_transcript(worker_events, context="default")
        assert len(default_transcript) == 1, "Default should capture finish action"
        assert "Done" in default_transcript[0]["text"]

    def test_promotion_to_full_when_no_finish(self):
        """Verify that full context is needed when no finish action.
        
        Some worker conversations don't complete with finish - they need full context.
        """
        worker_events = [
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git push"}},
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "echo done"}},
        ]
        
        # Both minimal and default are empty
        assert len(build_transcript(worker_events, context="minimal")) == 0
        assert len(build_transcript(worker_events, context="default")) == 0
        
        # Only full captures content
        full_transcript = build_transcript(worker_events, context="full")
        assert len(full_transcript) == 2, "Full should capture all actions"

    def test_no_promotion_when_user_messages_exist(self):
        """Normal conversations with user messages don't need promotion.
        
        If minimal context already produces content (user messages),
        no auto-promotion is needed.
        """
        normal_events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "Fix the bug"}]},
            },
            {"source": "agent", "kind": "ActionEvent", "tool_name": "terminal", "action": {"command": "git status"}},
        ]
        
        # Minimal context captures user message
        minimal_transcript = build_transcript(normal_events, context="minimal")
        assert len(minimal_transcript) == 1, "Minimal should capture user message"
        assert minimal_transcript[0]["role"] == "user"
        
        # No promotion needed since we have content

    def test_no_promotion_when_no_actions(self):
        """Conversations with only messages (no actions) don't benefit from promotion.
        
        Even if minimal is empty, if there are no ActionEvents, 
        promotion to default/full won't help.
        """
        message_only_events = [
            {"source": "agent", "kind": "MessageEvent", "content": "Thinking..."},
        ]
        
        # No actions to capture
        assert not _has_action_events(message_only_events)
        
        # Promotion wouldn't help - all contexts would be empty for action extraction
