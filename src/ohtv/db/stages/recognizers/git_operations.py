"""Recognizers for git operations."""

import re
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# Patterns for git commands
GIT_COMMIT_PATTERN = re.compile(r"git\s+commit")
GIT_PUSH_PATTERN = re.compile(r"git\s+push")

# Pattern to extract commit message from git commit output
COMMIT_MSG_PATTERN = re.compile(r"\[.+?\]\s+(.+)")

# Pattern to extract branch/remote info from push output
PUSH_TARGET_PATTERN = re.compile(r"To\s+([^\s]+)")


def recognize_git_operations(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize git operations from terminal commands.
    
    Detects:
    - GIT_COMMIT: git commit commands
    - GIT_PUSH: git push commands
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
    
    # Check for git commit
    if GIT_COMMIT_PATTERN.search(command):
        # Only count successful commits
        if context.action_succeeded():
            output = context.get_observation_content()
            commit_msg = _extract_commit_message(output)
            
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.GIT_COMMIT,
                    target=None,  # Could extract working directory
                    metadata={
                        "commit_message": commit_msg,
                    } if commit_msg else None,
                    event_id=event.get("id"),
                )
            )
    
    # Check for git push
    if GIT_PUSH_PATTERN.search(command):
        if context.action_succeeded():
            output = context.get_observation_content()
            push_target = _extract_push_target(output)
            
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.GIT_PUSH,
                    target=push_target,
                    metadata=None,
                    event_id=event.get("id"),
                )
            )
    
    return actions


def _extract_commit_message(output: str) -> str | None:
    """Extract commit message from git commit output."""
    # Output format: [branch hash] commit message
    match = COMMIT_MSG_PATTERN.search(output)
    if match:
        return match.group(1).strip()
    return None


def _extract_push_target(output: str) -> str | None:
    """Extract push target (remote URL) from git push output."""
    match = PUSH_TARGET_PATTERN.search(output)
    if match:
        return match.group(1).strip()
    return None
