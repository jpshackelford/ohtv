"""Data models for the index database.

These models represent the entities tracked in our SQLite database.
The database is intentionally minimal - we only track what's needed
for labeling and searching conversations by their relationships to
external resources (repos, issues, PRs).

Design decisions:
- Conversation content stays on filesystem; DB only has ID and location
- Repositories store canonical upstream URL (the actual remote, not its upstream)
- FQN format: "owner/repo" for repos, "owner/repo#123" for issues/PRs
- Display names are human-friendly: "repo #123" for issues/PRs
- Link types: 'write' implies 'read', so only one link per relationship
"""

from dataclasses import dataclass
from enum import Enum


class LinkType(Enum):
    """Type of link between conversation and external resource.
    
    - READ: Conversation referenced or read from the resource
    - WRITE: Conversation wrote to the resource (implies read)
    
    If a conversation has WRITE access, don't also store READ.
    """
    READ = "read"
    WRITE = "write"


@dataclass
class Conversation:
    """A conversation tracked in the index.
    
    Attributes:
        id: Unique conversation identifier (from OpenHands)
        location: Path to conversation data on disk
    """
    id: str
    location: str


@dataclass
class Repository:
    """A git repository reference.
    
    Attributes:
        id: Auto-generated database ID
        canonical_url: Full upstream URL (e.g., https://github.com/owner/repo)
        fqn: Fully qualified name (e.g., owner/repo)
        short_name: Just the repo name (e.g., repo)
    
    Note: canonical_url should be the actual remote being worked on.
    If working on a fork, store the fork URL, not its upstream.
    """
    id: int | None
    canonical_url: str
    fqn: str
    short_name: str


@dataclass
class Issue:
    """A GitHub/GitLab/etc issue reference.
    
    Attributes:
        id: Auto-generated database ID
        url: Full URL to the issue
        fqn: Fully qualified name (e.g., owner/repo#123)
        display_name: Human-friendly display (e.g., repo #123)
    """
    id: int | None
    url: str
    fqn: str
    display_name: str


@dataclass
class PullRequest:
    """A GitHub PR / GitLab MR / etc reference.
    
    Attributes:
        id: Auto-generated database ID
        url: Full URL to the PR
        fqn: Fully qualified name (e.g., owner/repo#456)
        display_name: Human-friendly display (e.g., repo #456)
    """
    id: int | None
    url: str
    fqn: str
    display_name: str


@dataclass
class ConversationRepoLink:
    """Link between a conversation and a repository.
    
    Attributes:
        conversation_id: The conversation identifier
        repo_id: The repository database ID
        link_type: READ or WRITE (WRITE implies READ)
    """
    conversation_id: str
    repo_id: int
    link_type: LinkType


@dataclass
class ConversationIssueLink:
    """Link between a conversation and an issue.
    
    Attributes:
        conversation_id: The conversation identifier
        issue_id: The issue database ID
        link_type: READ or WRITE (WRITE implies READ)
    """
    conversation_id: str
    issue_id: int
    link_type: LinkType


@dataclass
class ConversationPRLink:
    """Link between a conversation and a pull request.
    
    Attributes:
        conversation_id: The conversation identifier
        pr_id: The pull request database ID
        link_type: READ or WRITE (WRITE implies READ)
    """
    conversation_id: str
    pr_id: int
    link_type: LinkType
