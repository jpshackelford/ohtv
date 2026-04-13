"""Action model for tracking conversation activities."""

from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    """Types of actions that can be taken in a conversation.
    
    Categories:
    - Code/File edits: EDIT_CODE, EDIT_DOCS, EDIT_OTHER
    - Git operations: GIT_COMMIT, GIT_PUSH
    - GitHub/GitLab PR/MR: OPEN_PR, PR_COMMENT, PR_REVIEW, PR_EDIT, FIX_PR, MERGE_PR, CHECK_CI
    - GitHub/GitLab Issues: OPEN_ISSUE, ISSUE_COMMENT, ISSUE_EDIT, CLOSE_ISSUE
    - Notion: READ_NOTION, WRITE_NOTION
    - Research: WEB_RESEARCH, STUDY_CODE
    """
    # File editing actions
    EDIT_CODE = "edit-code"
    EDIT_DOCS = "edit-docs"
    EDIT_OTHER = "edit-other"
    
    # Git operations
    GIT_COMMIT = "git-commit"
    GIT_PUSH = "git-push"
    
    # Pull/Merge Request actions
    OPEN_PR = "open-pr"
    PR_COMMENT = "pr-comment"
    PR_REVIEW = "pr-review"
    PR_EDIT = "pr-edit"          # Edit PR title/description
    FIX_PR = "fix-pr"            # Push fixes to existing PR
    MERGE_PR = "merge-pr"        # Merge PR into target branch
    CLOSE_PR = "close-pr"        # Close PR without merging
    CHECK_CI = "check-ci"
    
    # Issue actions
    OPEN_ISSUE = "open-issue"
    ISSUE_COMMENT = "issue-comment"
    ISSUE_EDIT = "issue-edit"    # Edit issue title/description
    CLOSE_ISSUE = "close-issue"  # Close an issue
    
    # Notion actions
    READ_NOTION = "read-notion"    # Read pages/databases from Notion
    WRITE_NOTION = "write-notion"  # Create/update pages in Notion
    
    # Research/Study actions
    WEB_RESEARCH = "web-research"
    STUDY_CODE = "study-code"


@dataclass
class ConversationAction:
    """An action taken during a conversation.
    
    Attributes:
        id: Database ID (None for new actions)
        conversation_id: The conversation this action belongs to
        action_type: Type of action (from ActionType enum)
        target: What was acted upon (file path, URL, etc.)
        metadata: JSON-serializable dict with action-specific details
        event_id: ID of the event that triggered this action
    """
    id: int | None
    conversation_id: str
    action_type: ActionType
    target: str | None = None
    metadata: dict | None = None
    event_id: str | None = None
