"""Action categorization constants for conversation interactions.

Defines which actions are considered "write" (modifying remote state) vs "read"
(only retrieving information). Used by both CLI display and database link typing.
"""

# Write actions modify state in the remote system
# Examples: pushing commits, creating PRs, commenting on issues
WRITE_ACTIONS: set[str] = {
    "pushed",
    "committed",
    "created",
    "commented",
    "reviewed",
    "merged",
    "closed",
}

# Read actions only retrieve/view information
# Note: 'cloned' is READ because cloning downloads but doesn't modify the remote
READ_ACTIONS: set[str] = {
    "cloned",
    "fetched",
    "pulled",
    "viewed",
    "browsed",
    "api_called",
}


def is_write_action(action: str) -> bool:
    """Check if an action is a write action."""
    return action in WRITE_ACTIONS


def is_read_action(action: str) -> bool:
    """Check if an action is a read action."""
    return action in READ_ACTIONS
