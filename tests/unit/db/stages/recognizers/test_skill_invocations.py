"""Tests for skill invocation recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.skill_invocations import recognize_skill_invocations


class TestRecognizeSkillInvocations:
    """Tests for skill invocation recognition."""
    
    @pytest.fixture
    def make_context(self):
        """Factory for creating recognizer context."""
        def _make(events, current_index=0):
            return RecognizerContext(
                conversation_id="test-conv",
                events=events,
                current_index=current_index,
            )
        return _make
    
    def test_recognizes_codereview_command(self, make_context):
        """Should recognize /codereview slash command."""
        event = {
            "id": "event-1",
            "kind": "MessageEvent",
            "role": "user",
            "content": [{"type": "text", "text": "Please review this PR /codereview"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_REVIEW
        assert actions[0].metadata["source"] == "skill"
        assert actions[0].metadata["skill"] == "codereview"
    
    def test_recognizes_codereview_roasted_command(self, make_context):
        """Should recognize /codereview-roasted slash command."""
        event = {
            "id": "event-2",
            "kind": "MessageEvent",
            "role": "user",
            "content": [{"type": "text", "text": "/codereview-roasted"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_REVIEW
        assert actions[0].metadata["skill"] == "codereview-roasted"
    
    def test_recognizes_codereview_at_start_of_message(self, make_context):
        """Should recognize /codereview at start of message."""
        event = {
            "id": "event-3",
            "kind": "MessageEvent",
            "role": "user",
            "content": [{"type": "text", "text": "/codereview this PR please"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_REVIEW
    
    def test_recognizes_codereview_on_new_line(self, make_context):
        """Should recognize /codereview on a new line."""
        event = {
            "id": "event-4",
            "kind": "MessageEvent",
            "role": "user",
            "content": [{"type": "text", "text": "Check this out\n/codereview"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 1
    
    def test_ignores_agent_messages(self, make_context):
        """Should not recognize slash commands in agent messages."""
        event = {
            "kind": "MessageEvent",
            "role": "assistant",
            "content": [{"type": "text", "text": "Use /codereview to review"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 0
    
    def test_ignores_non_message_events(self, make_context):
        """Should not recognize slash commands in non-message events."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "/codereview"},
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 0
    
    def test_ignores_codereview_without_slash(self, make_context):
        """Should not recognize 'codereview' without leading slash."""
        event = {
            "kind": "MessageEvent",
            "role": "user",
            "content": [{"type": "text", "text": "please do a codereview"}],
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 0
    
    def test_handles_string_content(self, make_context):
        """Should handle content as plain string."""
        event = {
            "id": "event-5",
            "kind": "MessageEvent",
            "role": "user",
            "content": "/codereview",
        }
        
        context = make_context([event])
        actions = recognize_skill_invocations(event, context)
        
        assert len(actions) == 1
