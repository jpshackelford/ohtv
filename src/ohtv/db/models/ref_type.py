"""Reference type enum for issues, PRs, branches, etc."""

from enum import Enum


class RefType(Enum):
    """Type of reference (issue, PR, branch, etc).
    
    Extensible for future reference types (discussions, commits, etc).
    """
    ISSUE = "issue"
    PR = "pr"
    BRANCH = "branch"
