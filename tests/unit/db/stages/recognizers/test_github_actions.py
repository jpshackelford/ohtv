"""Tests for GitHub/GitLab action recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.github_actions import recognize_github_actions


class TestRecognizeGitHubActions:
    """Tests for GitHub action recognition."""
    
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
    
    def test_recognizes_pr_create(self, make_context):
        """Should recognize gh pr create."""
        action_event = {
            "id": "event-1",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr create --title 'Fix bug' --body 'Details'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "https://github.com/owner/repo/pull/123"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.OPEN_PR
        assert actions[0].target == "https://github.com/owner/repo/pull/123"
    
    def test_recognizes_pr_comment(self, make_context):
        """Should recognize gh pr comment."""
        action_event = {
            "id": "event-2",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr comment 123 --body 'LGTM'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Comment added"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_COMMENT
        assert actions[0].target == "123"
    
    def test_recognizes_pr_review(self, make_context):
        """Should recognize gh pr review."""
        action_event = {
            "id": "event-3",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr review 123 --approve",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Review submitted"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_REVIEW
    
    def test_recognizes_pr_edit(self, make_context):
        """Should recognize gh pr edit."""
        action_event = {
            "id": "event-4",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr edit 123 --title 'New title'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "PR updated"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PR_EDIT
    
    def test_recognizes_pr_checks(self, make_context):
        """Should recognize gh pr checks."""
        action_event = {
            "id": "event-5",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr checks 123",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "All checks passed"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.CHECK_CI
    
    def test_recognizes_gh_run_commands(self, make_context):
        """Should recognize gh run commands."""
        for run_cmd in ["gh run list", "gh run view 123", "gh run watch 456"]:
            action_event = {
                "id": "event-6",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": run_cmd}
            }
            obs_event = {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "output"}],
                }
            }
            
            context = make_context([action_event, obs_event])
            actions = recognize_github_actions(action_event, context)
            
            assert len(actions) == 1
            assert actions[0].action_type == ActionType.CHECK_CI
    
    def test_recognizes_issue_create(self, make_context):
        """Should recognize gh issue create."""
        action_event = {
            "id": "event-7",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh issue create --title 'Bug report' --body 'Details'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "https://github.com/owner/repo/issues/456"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.OPEN_ISSUE
        assert actions[0].target == "https://github.com/owner/repo/issues/456"
    
    def test_recognizes_issue_comment(self, make_context):
        """Should recognize gh issue comment."""
        action_event = {
            "id": "event-8",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh issue comment 456 --body 'Thanks!'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Comment added"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.ISSUE_COMMENT
    
    def test_recognizes_issue_edit(self, make_context):
        """Should recognize gh issue edit."""
        action_event = {
            "id": "event-9",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh issue edit 456 --title 'Updated title'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Issue updated"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.ISSUE_EDIT
    
    def test_ignores_failed_commands(self, make_context):
        """Should not recognize failed commands (except check-ci)."""
        action_event = {
            "id": "event-10",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr create --title 'Fix'",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 1,
                "content": [{"type": "text", "text": "Error creating PR"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 0
    
    def test_ignores_non_terminal_actions(self, make_context):
        """Should not recognize non-terminal tools."""
        action_event = {
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {"command": "view", "path": "/path"},
        }
        
        context = make_context([action_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 0
    
    def test_recognizes_pr_merge(self, make_context):
        """Should recognize gh pr merge."""
        action_event = {
            "id": "event-11",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr merge 123 --squash",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Merged pull request #123"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.MERGE_PR
        assert actions[0].target == "123"
    
    def test_recognizes_pr_close(self, make_context):
        """Should recognize gh pr close."""
        action_event = {
            "id": "event-12",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh pr close 456",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Closed pull request #456"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.CLOSE_PR
    
    def test_recognizes_issue_close(self, make_context):
        """Should recognize gh issue close."""
        action_event = {
            "id": "event-13",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "gh issue close 789",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Closed issue #789"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_github_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.CLOSE_ISSUE
