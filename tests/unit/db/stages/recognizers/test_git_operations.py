"""Tests for git operation recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.git_operations import recognize_git_operations


class TestRecognizeGitOperations:
    """Tests for git operation recognition."""
    
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
    
    def test_recognizes_git_commit(self, make_context):
        """Should recognize successful git commit."""
        action_event = {
            "id": "event-1",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git commit -m 'Add feature'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "[main abc1234] Add feature"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.GIT_COMMIT
    
    def test_ignores_failed_git_commit(self, make_context):
        """Should not recognize failed git commit."""
        action_event = {
            "id": "event-2",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git commit -m 'Add feature'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 1,
                "content": [{"type": "text", "text": "nothing to commit"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 0
    
    def test_recognizes_git_push(self, make_context):
        """Should recognize successful git push."""
        action_event = {
            "id": "event-3",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git push origin main",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "To https://github.com/owner/repo.git\n   abc123..def456  main -> main"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.GIT_PUSH
        assert actions[0].target == "https://github.com/owner/repo.git"
    
    def test_ignores_failed_git_push(self, make_context):
        """Should not recognize failed git push."""
        action_event = {
            "id": "event-4",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git push origin main",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 1,
                "content": [{"type": "text", "text": "error: failed to push"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 0
    
    def test_ignores_non_terminal_events(self, make_context):
        """Should not recognize non-terminal tools."""
        action_event = {
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {"command": "view", "path": "/path"},
        }
        
        context = make_context([action_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 0
    
    def test_recognizes_both_commit_and_push_in_chain(self, make_context):
        """Should recognize commit and push separately in chain command."""
        action_event = {
            "id": "event-5",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git commit -m 'msg' && git push origin main",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "[main abc] msg\nTo https://github.com/owner/repo.git"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        # Should recognize both commit and push
        assert len(actions) == 2
        action_types = {a.action_type for a in actions}
        assert ActionType.GIT_COMMIT in action_types
        assert ActionType.GIT_PUSH in action_types
