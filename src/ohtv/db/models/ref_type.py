"""Reference type enum for issues, PRs, etc."""

from enum import Enum


class RefType(Enum):
    """Type of reference (issue, PR, etc).
    
    Extensible for future reference types (discussions, commits, etc).
    """
    ISSUE = "issue"
    PR = "pr"
