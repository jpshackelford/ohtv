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

# Pattern to extract branch from push output
# Matches lines like:
#   abc123..def456  branch-name -> branch-name
#   * [new branch]  branch-name -> branch-name
PUSH_BRANCH_PATTERN = re.compile(
    r"(?:[a-f0-9.]+|\*\s+\[new branch\])\s+([^\s]+)\s+->\s+([^\s]+)"
)

# Pattern to extract branch from git push command
# Matches: git push origin branch-name, git push -u origin branch-name
PUSH_COMMAND_BRANCH_PATTERN = re.compile(
    r"git\s+push\s+(?:-[a-z]+\s+)*(?:\w+)\s+([^\s;|&]+)"
)

# =============================================================================
# Checkout/Switch tracking patterns
# =============================================================================

# Pattern to extract working directory from cd command
# Matches: cd /path && ..., cd /path; ..., cd /path&&...
CD_PATH_PATTERN = re.compile(
    r"cd\s+([^\s;&|]+)\s*(?:&&|;|\|\|)"
)

# Patterns for git checkout/switch commands
# git checkout <branch>
# git checkout -b <branch> [start-point]
# git switch <branch>
# git switch -c <branch> [start-point]
GIT_CHECKOUT_PATTERN = re.compile(r"git\s+checkout(?:\s|$)")
GIT_SWITCH_PATTERN = re.compile(r"git\s+switch(?:\s|$)")

# Extract branch from checkout command
# git checkout <branch>
# git checkout -b <new-branch> [start-point]
CHECKOUT_BRANCH_PATTERN = re.compile(
    r"git\s+checkout\s+(?:-b\s+)?([^\s;&|]+)"
)

# Extract branch from switch command  
# git switch <branch>
# git switch -c <new-branch> [start-point]
SWITCH_BRANCH_PATTERN = re.compile(
    r"git\s+switch\s+(?:-c\s+)?([^\s;&|]+)"
)

# Pattern to detect detached HEAD from checkout output
DETACHED_HEAD_PATTERN = re.compile(
    r"detached HEAD|HEAD is now at"
)

# Pattern to extract branch from checkout/switch output
# "Switched to branch 'branch-name'"
# "Switched to a new branch 'branch-name'"
SWITCHED_TO_BRANCH_PATTERN = re.compile(
    r"Switched to (?:a new )?branch ['\"]?([^'\"]+)['\"]?"
)


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
            branch = _extract_push_branch(command, output)
            repo_info = _extract_repo_from_push_target(push_target)
            
            # If no branch found from push, try to infer from prior checkout
            inferred_from_checkout = False
            if not branch:
                working_dir = extract_working_directory(command)
                if working_dir:
                    branch = find_checkout_branch_for_path(
                        context.events,
                        context.current_index,
                        working_dir,
                    )
                    if branch:
                        inferred_from_checkout = True
            
            metadata = {}
            if branch:
                metadata["branch"] = branch
            if repo_info:
                metadata["owner"] = repo_info["owner"]
                metadata["repo"] = repo_info["repo"]
            if inferred_from_checkout:
                metadata["branch_inferred"] = True
            
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.GIT_PUSH,
                    target=push_target,
                    metadata=metadata if metadata else None,
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


def _extract_push_branch(command: str, output: str) -> str | None:
    """Extract branch name from git push command or output.
    
    Tries to extract from output first (most reliable), then from command.
    Output format: abc123..def456  branch-name -> branch-name
    """
    # First try to extract from output (more reliable)
    match = PUSH_BRANCH_PATTERN.search(output)
    if match:
        # Return the local branch name (first group)
        return match.group(1).strip()
    
    # Fall back to command parsing
    match = PUSH_COMMAND_BRANCH_PATTERN.search(command)
    if match:
        return match.group(1).strip()
    
    return None


def _extract_repo_from_push_target(push_target: str | None) -> dict | None:
    """Extract owner and repo from a push target URL.
    
    Handles both HTTPS and SSH formats:
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    """
    if not push_target:
        return None
    
    # HTTPS format: https://github.com/owner/repo.git
    https_match = re.search(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$",
        push_target
    )
    if https_match:
        return {"owner": https_match.group(1), "repo": https_match.group(2)}
    
    # SSH format: git@github.com:owner/repo.git
    ssh_match = re.search(
        r"git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$",
        push_target
    )
    if ssh_match:
        return {"owner": ssh_match.group(1), "repo": ssh_match.group(2)}
    
    return None


# =============================================================================
# Checkout tracking helper functions
# =============================================================================


def extract_working_directory(command: str) -> str | None:
    """Extract working directory from a command with cd prefix.
    
    Handles patterns like:
    - "cd /path && git checkout..."
    - "cd /path; git push"
    - "cd /path&&git checkout..."
    
    Args:
        command: The full terminal command
        
    Returns:
        The working directory path, or None if not found
    """
    match = CD_PATH_PATTERN.search(command)
    if match:
        return match.group(1).strip()
    return None


def extract_checkout_branch(command: str, output: str) -> str | None:
    """Extract branch name from git checkout/switch command and output.
    
    Prefers output parsing (more reliable) over command parsing.
    Returns None for detached HEAD state.
    
    Args:
        command: The git checkout/switch command
        output: The command output
        
    Returns:
        Branch name, or None if not found or detached HEAD
    """
    # Check for detached HEAD first
    if DETACHED_HEAD_PATTERN.search(output):
        return None
    
    # Try to extract from output (most reliable)
    output_match = SWITCHED_TO_BRANCH_PATTERN.search(output)
    if output_match:
        return output_match.group(1).strip()
    
    # Fall back to command parsing
    if GIT_CHECKOUT_PATTERN.search(command):
        cmd_match = CHECKOUT_BRANCH_PATTERN.search(command)
        if cmd_match:
            branch = cmd_match.group(1).strip()
            # Filter out flags that might have been captured
            if not branch.startswith("-"):
                return branch
    
    if GIT_SWITCH_PATTERN.search(command):
        cmd_match = SWITCH_BRANCH_PATTERN.search(command)
        if cmd_match:
            branch = cmd_match.group(1).strip()
            if not branch.startswith("-"):
                return branch
    
    return None


def is_checkout_command(command: str) -> bool:
    """Check if a command contains git checkout or git switch."""
    return bool(GIT_CHECKOUT_PATTERN.search(command) or GIT_SWITCH_PATTERN.search(command))


def find_checkout_branch_for_path(
    events: list[dict],
    current_index: int,
    target_path: str,
) -> str | None:
    """Find the most recent checkout branch for a given repo path.
    
    Searches backward through events to find the last checkout/switch
    command that affected the given path.
    
    Args:
        events: List of all events in the conversation
        current_index: Index of the current event (search backward from here)
        target_path: The working directory path to match
        
    Returns:
        The branch name from the most recent checkout, or None
    """
    # Search backward through events
    for i in range(current_index - 1, -1, -1):
        event = events[i]
        
        # Only look at terminal action events
        if event.get("kind") != "ActionEvent":
            continue
        if event.get("tool_name") != "terminal":
            continue
        
        action = event.get("action", {})
        if not isinstance(action, dict):
            continue
        
        command = action.get("command", "")
        if not command:
            continue
        
        # Check if this is a checkout/switch command
        if not is_checkout_command(command):
            continue
        
        # Extract the working directory
        event_path = extract_working_directory(command)
        if event_path != target_path:
            continue
        
        # Found a checkout for this path - extract the branch
        # Need to find the observation for this event
        output = _get_observation_for_event(events, i)
        if output is None:
            continue
        
        branch = extract_checkout_branch(command, output)
        if branch is not None:
            return branch
        
        # If we found a checkout but got None (detached HEAD), return None
        # to indicate no current branch
        return None
    
    return None


def _get_observation_for_event(events: list[dict], action_index: int) -> str | None:
    """Get the observation content following an action event.
    
    Args:
        events: List of all events
        action_index: Index of the action event
        
    Returns:
        The observation content text, or None if not found
    """
    # Look for the next observation event
    for i in range(action_index + 1, len(events)):
        event = events[i]
        if event.get("kind") == "ObservationEvent":
            obs = event.get("observation", {})
            content = obs.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        return item.get("text", "")
            elif isinstance(content, str):
                return content
            break
        # If we hit another action, stop looking
        if event.get("kind") == "ActionEvent":
            break
    return None
