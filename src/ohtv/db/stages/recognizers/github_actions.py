"""Recognizers for GitHub/GitLab actions (PRs, issues, CI)."""

import re
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# Patterns for GitHub CLI commands
GH_PR_CREATE = re.compile(r"gh\s+pr\s+create")
GH_PR_COMMENT = re.compile(r"gh\s+pr\s+comment")
GH_PR_REVIEW = re.compile(r"gh\s+pr\s+review")
GH_PR_EDIT = re.compile(r"gh\s+pr\s+edit")
GH_PR_MERGE = re.compile(r"gh\s+pr\s+merge")
GH_PR_CLOSE = re.compile(r"gh\s+pr\s+close")
GH_PR_CHECKS = re.compile(r"gh\s+pr\s+checks")
GH_RUN = re.compile(r"gh\s+run\s+(list|view|watch)")

GH_ISSUE_CREATE = re.compile(r"gh\s+issue\s+create")
GH_ISSUE_COMMENT = re.compile(r"gh\s+issue\s+comment")
GH_ISSUE_EDIT = re.compile(r"gh\s+issue\s+edit")
GH_ISSUE_CLOSE = re.compile(r"gh\s+issue\s+close")

# URL extraction patterns
PR_URL_PATTERN = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
ISSUE_URL_PATTERN = re.compile(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)")

# Pattern to extract head branch from gh pr create output
# Matches: "Creating pull request for feature-branch into main in owner/repo"
PR_CREATE_BRANCH_PATTERN = re.compile(
    r"Creating (?:draft )?pull request for\s+([^\s]+)\s+into\s+[^\s]+\s+in\s+([^/\s]+)/([^\s]+)"
)

# GitLab patterns
GL_MR_CREATE = re.compile(r"glab\s+mr\s+create")
GL_MR_COMMENT = re.compile(r"glab\s+mr\s+comment")
GL_MR_EDIT = re.compile(r"glab\s+mr\s+edit")
GL_MR_MERGE = re.compile(r"glab\s+mr\s+merge")
GL_MR_CLOSE = re.compile(r"glab\s+mr\s+close")
GL_ISSUE_CREATE = re.compile(r"glab\s+issue\s+create")
GL_ISSUE_COMMENT = re.compile(r"glab\s+issue\s+comment")
GL_ISSUE_EDIT = re.compile(r"glab\s+issue\s+edit")
GL_ISSUE_CLOSE = re.compile(r"glab\s+issue\s+close")


def recognize_github_actions(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize GitHub/GitLab actions from terminal commands.
    
    Detects:
    - OPEN_PR: gh pr create / glab mr create
    - PR_COMMENT: gh pr comment / glab mr comment
    - PR_REVIEW: gh pr review
    - PR_EDIT: gh pr edit (title/description changes)
    - MERGE_PR: gh pr merge / glab mr merge (merge into target branch)
    - CLOSE_PR: gh pr close / glab mr close (close without merging)
    - CHECK_CI: gh pr checks / gh run commands
    - OPEN_ISSUE: gh issue create / glab issue create
    - ISSUE_COMMENT: gh issue comment / glab issue comment
    - ISSUE_EDIT: gh issue edit / glab issue edit
    - CLOSE_ISSUE: gh issue close / glab issue close
    """
    if event.get("kind") != "ActionEvent":
        return []
    
    tool_name = event.get("tool_name", "")
    if tool_name != "terminal":
        return []
    
    action = event.get("action", {})
    if not isinstance(action, dict):
        return []
    
    command = action.get("command", "")
    if not command:
        return []
    
    actions = []
    
    # --- PR/MR Actions ---
    
    # Create PR
    if GH_PR_CREATE.search(command) or GL_MR_CREATE.search(command):
        if context.action_succeeded():
            output = context.get_observation_content()
            pr_url = _extract_pr_url(output)
            branch_info = _extract_pr_create_branch(output)
            
            metadata = {"source": "github" if "gh " in command else "gitlab"}
            if branch_info:
                metadata["head_branch"] = branch_info["branch"]
                metadata["owner"] = branch_info["owner"]
                metadata["repo"] = branch_info["repo"]
            
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.OPEN_PR,
                    target=pr_url,
                    metadata=metadata,
                    event_id=event.get("id"),
                )
            )
    
    # PR Comment
    if GH_PR_COMMENT.search(command) or GL_MR_COMMENT.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.PR_COMMENT,
                    target=_extract_pr_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # PR Review
    if GH_PR_REVIEW.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.PR_REVIEW,
                    target=_extract_pr_number_from_command(command),
                    metadata=None,
                    event_id=event.get("id"),
                )
            )
    
    # PR Edit
    if GH_PR_EDIT.search(command) or GL_MR_EDIT.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.PR_EDIT,
                    target=_extract_pr_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # PR Merge
    if GH_PR_MERGE.search(command) or GL_MR_MERGE.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.MERGE_PR,
                    target=_extract_pr_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # PR Close (without merge)
    if GH_PR_CLOSE.search(command) or GL_MR_CLOSE.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.CLOSE_PR,
                    target=_extract_pr_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # Check CI
    if GH_PR_CHECKS.search(command) or GH_RUN.search(command):
        actions.append(
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.CHECK_CI,
                target=_extract_pr_number_from_command(command),
                metadata=None,
                event_id=event.get("id"),
            )
        )
    
    # --- Issue Actions ---
    
    # Create Issue
    if GH_ISSUE_CREATE.search(command) or GL_ISSUE_CREATE.search(command):
        if context.action_succeeded():
            output = context.get_observation_content()
            issue_url = _extract_issue_url(output)
            
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.OPEN_ISSUE,
                    target=issue_url,
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # Issue Comment
    if GH_ISSUE_COMMENT.search(command) or GL_ISSUE_COMMENT.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.ISSUE_COMMENT,
                    target=_extract_issue_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # Issue Edit
    if GH_ISSUE_EDIT.search(command) or GL_ISSUE_EDIT.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.ISSUE_EDIT,
                    target=_extract_issue_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    # Issue Close
    if GH_ISSUE_CLOSE.search(command) or GL_ISSUE_CLOSE.search(command):
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.CLOSE_ISSUE,
                    target=_extract_issue_number_from_command(command),
                    metadata={"source": "github" if "gh " in command else "gitlab"},
                    event_id=event.get("id"),
                )
            )
    
    return actions


def _extract_pr_url(output: str) -> str | None:
    """Extract PR URL from command output."""
    match = PR_URL_PATTERN.search(output)
    if match:
        return match.group(0)
    return None


def _extract_pr_create_branch(output: str) -> dict | None:
    """Extract head branch and repo info from gh pr create output.
    
    Parses output like: "Creating pull request for feature-branch into main in owner/repo"
    Returns dict with branch, owner, repo or None if not found.
    """
    # Strip ANSI escape codes (color formatting from gh CLI)
    clean_output = _strip_ansi(output)
    match = PR_CREATE_BRANCH_PATTERN.search(clean_output)
    if match:
        return {
            "branch": match.group(1),
            "owner": match.group(2),
            "repo": match.group(3),
        }
    return None


# Pattern to match ANSI escape sequences
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE.sub('', text)


def _extract_issue_url(output: str) -> str | None:
    """Extract issue URL from command output."""
    match = ISSUE_URL_PATTERN.search(output)
    if match:
        return match.group(0)
    return None


def _extract_pr_number_from_command(command: str) -> str | None:
    """Extract PR number from a gh pr command."""
    # Look for a number in the command
    match = re.search(r"\s(\d+)(?:\s|$)", command)
    if match:
        return match.group(1)
    return None


def _extract_issue_number_from_command(command: str) -> str | None:
    """Extract issue number from a gh issue command."""
    match = re.search(r"\s(\d+)(?:\s|$)", command)
    if match:
        return match.group(1)
    return None
