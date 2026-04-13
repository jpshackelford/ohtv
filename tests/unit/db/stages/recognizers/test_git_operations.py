"""Tests for git operation recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.git_operations import (
    recognize_git_operations,
    _extract_push_branch,
    _extract_repo_from_push_target,
    extract_working_directory,
    extract_checkout_branch,
    is_checkout_command,
    find_checkout_branch_for_path,
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


class TestExtractWorkingDirectory:
    """Tests for working directory extraction from commands."""
    
    def test_extracts_path_with_double_ampersand(self):
        """Should extract path from 'cd /path && git...' pattern."""
        command = "cd /workspace/project && git checkout main"
        assert extract_working_directory(command) == "/workspace/project"
    
    def test_extracts_path_with_semicolon(self):
        """Should extract path from 'cd /path; git...' pattern."""
        command = "cd /workspace/project ; git push"
        assert extract_working_directory(command) == "/workspace/project"
    
    def test_extracts_path_without_spaces(self):
        """Should extract path when no spaces around separator."""
        command = "cd /workspace/project&&git checkout feature"
        assert extract_working_directory(command) == "/workspace/project"
    
    def test_extracts_nested_path(self):
        """Should extract nested directory paths."""
        command = "cd /home/user/code/my-project && git status"
        assert extract_working_directory(command) == "/home/user/code/my-project"
    
    def test_returns_none_for_no_cd(self):
        """Should return None when no cd command."""
        command = "git push origin main"
        assert extract_working_directory(command) is None
    
    def test_returns_none_for_cd_only(self):
        """Should return None for cd without following command."""
        command = "cd /workspace/project"
        assert extract_working_directory(command) is None


class TestExtractCheckoutBranch:
    """Tests for branch extraction from checkout/switch commands."""
    
    def test_extracts_from_checkout_output(self):
        """Should extract branch from 'Switched to branch' output."""
        command = "git checkout feature/test"
        output = "Switched to branch 'feature/test'"
        assert extract_checkout_branch(command, output) == "feature/test"
    
    def test_extracts_from_new_branch_output(self):
        """Should extract branch from 'Switched to a new branch' output."""
        command = "git checkout -b feature/new"
        output = "Switched to a new branch 'feature/new'"
        assert extract_checkout_branch(command, output) == "feature/new"
    
    def test_extracts_from_switch_output(self):
        """Should extract branch from git switch output."""
        command = "git switch main"
        output = "Switched to branch 'main'"
        assert extract_checkout_branch(command, output) == "main"
    
    def test_extracts_from_switch_c_output(self):
        """Should extract branch from git switch -c output."""
        command = "git switch -c hotfix/urgent"
        output = "Switched to a new branch 'hotfix/urgent'"
        assert extract_checkout_branch(command, output) == "hotfix/urgent"
    
    def test_returns_none_for_detached_head(self):
        """Should return None for detached HEAD state."""
        command = "git checkout abc123"
        output = "Note: switching to 'abc123'.\n\nYou are in 'detached HEAD' state."
        assert extract_checkout_branch(command, output) is None
    
    def test_returns_none_for_head_is_now_at(self):
        """Should return None for 'HEAD is now at' output."""
        command = "git checkout abc123"
        output = "HEAD is now at abc123 Some commit message"
        assert extract_checkout_branch(command, output) is None
    
    def test_falls_back_to_command_parsing(self):
        """Should extract from command when output doesn't match pattern."""
        command = "git checkout feature/test"
        output = "Already on 'feature/test'"  # Different output format
        # Falls back to command parsing
        assert extract_checkout_branch(command, output) == "feature/test"
    
    def test_handles_branch_with_slash(self):
        """Should handle branch names with slashes."""
        command = "git checkout feature/add/button"
        output = "Switched to branch 'feature/add/button'"
        assert extract_checkout_branch(command, output) == "feature/add/button"


class TestIsCheckoutCommand:
    """Tests for checkout command detection."""
    
    def test_detects_git_checkout(self):
        """Should detect git checkout command."""
        assert is_checkout_command("git checkout main") is True
    
    def test_detects_git_checkout_b(self):
        """Should detect git checkout -b command."""
        assert is_checkout_command("git checkout -b feature") is True
    
    def test_detects_git_switch(self):
        """Should detect git switch command."""
        assert is_checkout_command("git switch main") is True
    
    def test_detects_git_switch_c(self):
        """Should detect git switch -c command."""
        assert is_checkout_command("git switch -c feature") is True
    
    def test_rejects_git_push(self):
        """Should not detect git push as checkout."""
        assert is_checkout_command("git push origin main") is False
    
    def test_rejects_git_commit(self):
        """Should not detect git commit as checkout."""
        assert is_checkout_command("git commit -m 'msg'") is False
    
    def test_handles_command_with_cd(self):
        """Should detect checkout in compound command."""
        assert is_checkout_command("cd /path && git checkout main") is True


class TestFindCheckoutBranchForPath:
    """Tests for finding checkout branch from event history."""
    
    def test_finds_checkout_for_matching_path(self):
        """Should find checkout branch for matching path."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature/test"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature/test'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
        ]
        
        branch = find_checkout_branch_for_path(events, 2, "/workspace/project")
        assert branch == "feature/test"
    
    def test_uses_most_recent_checkout(self):
        """Should use the most recent checkout for a path."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature-a"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature-a'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature-b"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature-b'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
        ]
        
        branch = find_checkout_branch_for_path(events, 4, "/workspace/project")
        assert branch == "feature-b"
    
    def test_tracks_repos_independently(self):
        """Should track different repos independently."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/frontend && git checkout ui-feature"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'ui-feature'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/backend && git checkout api-feature"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'api-feature'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/frontend && git push"},
            },
        ]
        
        # Should find ui-feature for frontend, not api-feature
        branch = find_checkout_branch_for_path(events, 4, "/workspace/frontend")
        assert branch == "ui-feature"
    
    def test_returns_none_for_no_checkout(self):
        """Should return None when no checkout found for path."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/other && git checkout main"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'main'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
        ]
        
        branch = find_checkout_branch_for_path(events, 2, "/workspace/project")
        assert branch is None
    
    def test_returns_none_for_detached_head(self):
        """Should return None when last checkout was detached HEAD."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature'"}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout abc123"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "You are in 'detached HEAD' state."}],
                },
            },
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
        ]
        
        branch = find_checkout_branch_for_path(events, 4, "/workspace/project")
        assert branch is None


class TestCheckoutInferenceInPush:
    """Integration tests for checkout inference during push recognition."""
    
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
    
    def test_infers_branch_from_checkout(self, make_context):
        """Should infer branch from prior checkout when push has no branch info."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature/test"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature/test'"}],
                },
            },
            {
                "id": "push-event",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Everything up-to-date"}],
                },
            },
        ]
        
        context = make_context(events, current_index=2)
        actions = recognize_git_operations(events[2], context)
        
        assert len(actions) == 1
        action = actions[0]
        assert action.action_type == ActionType.GIT_PUSH
        assert action.metadata is not None
        assert action.metadata.get("branch") == "feature/test"
        assert action.metadata.get("branch_inferred") is True
    
    def test_prefers_push_output_over_checkout(self, make_context):
        """Should prefer branch from push output over checkout inference."""
        events = [
            {
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git checkout feature/old"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "Switched to branch 'feature/old'"}],
                },
            },
            {
                "id": "push-event",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "cd /workspace/project && git push"},
            },
            {
                "kind": "ObservationEvent",
                "observation": {
                    "exit_code": 0,
                    "content": [{"type": "text", "text": "To https://github.com/owner/repo.git\n   abc..def  feature/new -> feature/new"}],
                },
            },
        ]
        
        context = make_context(events, current_index=2)
        actions = recognize_git_operations(events[2], context)
        
        assert len(actions) == 1
        action = actions[0]
        # Should use branch from push output, not checkout
        assert action.metadata.get("branch") == "feature/new"
        # Should NOT have branch_inferred flag
        assert action.metadata.get("branch_inferred") is None
