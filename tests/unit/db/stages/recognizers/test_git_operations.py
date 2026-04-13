"""Tests for git operation recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.git_operations import (
    recognize_git_operations,
    _extract_push_branch,
    _extract_repo_from_push_target,
)


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
    
    def test_git_push_extracts_branch_and_repo_info(self, make_context):
        """Should extract branch and repo info from git push output."""
        action_event = {
            "id": "event-6",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git push",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "To https://github.com/OpenHands/software-agent-sdk.git\n   4e29d538..2a8b3429  feature/my-branch -> feature/my-branch"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 1
        action = actions[0]
        assert action.action_type == ActionType.GIT_PUSH
        assert action.target == "https://github.com/OpenHands/software-agent-sdk.git"
        assert action.metadata is not None
        assert action.metadata.get("branch") == "feature/my-branch"
        assert action.metadata.get("owner") == "OpenHands"
        assert action.metadata.get("repo") == "software-agent-sdk"
    
    def test_git_push_extracts_branch_from_new_branch_output(self, make_context):
        """Should extract branch from 'new branch' push output."""
        action_event = {
            "id": "event-7",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "git push -u origin my-new-branch",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{
                    "type": "text",
                    "text": "To https://github.com/owner/repo.git\n * [new branch]      my-new-branch -> my-new-branch"
                }],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_git_operations(action_event, context)
        
        assert len(actions) == 1
        action = actions[0]
        assert action.metadata is not None
        assert action.metadata.get("branch") == "my-new-branch"


class TestExtractPushBranch:
    """Tests for branch extraction from git push."""
    
    def test_extracts_branch_from_update_output(self):
        """Should extract branch from standard push update output."""
        output = "   abc123..def456  main -> main"
        branch = _extract_push_branch("git push", output)
        assert branch == "main"
    
    def test_extracts_branch_from_new_branch_output(self):
        """Should extract branch from new branch creation output."""
        output = " * [new branch]      feature/test -> feature/test"
        branch = _extract_push_branch("git push", output)
        assert branch == "feature/test"
    
    def test_extracts_branch_from_command_fallback(self):
        """Should extract branch from command when output doesn't match."""
        command = "git push origin feature/my-branch"
        output = "Everything up-to-date"  # No branch info in output
        branch = _extract_push_branch(command, output)
        assert branch == "feature/my-branch"
    
    def test_extracts_branch_with_flags(self):
        """Should extract branch from command with flags."""
        command = "git push -u origin my-branch"
        output = "Something without branch info"
        branch = _extract_push_branch(command, output)
        assert branch == "my-branch"
    
    def test_returns_none_for_no_branch(self):
        """Should return None when no branch can be extracted."""
        branch = _extract_push_branch("git push", "")
        assert branch is None


class TestExtractRepoFromPushTarget:
    """Tests for repo extraction from push target URL."""
    
    def test_extracts_from_https_url(self):
        """Should extract owner/repo from HTTPS URL."""
        url = "https://github.com/OpenHands/software-agent-sdk.git"
        result = _extract_repo_from_push_target(url)
        assert result == {"owner": "OpenHands", "repo": "software-agent-sdk"}
    
    def test_extracts_from_https_url_without_git(self):
        """Should extract from HTTPS URL without .git suffix."""
        url = "https://github.com/owner/repo"
        result = _extract_repo_from_push_target(url)
        assert result == {"owner": "owner", "repo": "repo"}
    
    def test_extracts_from_ssh_url(self):
        """Should extract owner/repo from SSH URL."""
        url = "git@github.com:owner/repo.git"
        result = _extract_repo_from_push_target(url)
        assert result == {"owner": "owner", "repo": "repo"}
    
    def test_returns_none_for_none_input(self):
        """Should return None for None input."""
        assert _extract_repo_from_push_target(None) is None
    
    def test_returns_none_for_non_github_url(self):
        """Should return None for non-GitHub URLs."""
        url = "https://gitlab.com/owner/repo.git"
        assert _extract_repo_from_push_target(url) is None
