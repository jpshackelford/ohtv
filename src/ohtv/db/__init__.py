"""Database module for ohtv indexing.

This module provides SQLite-based indexing for conversation metadata,
specifically for tracking relationships between conversations and external
references like repositories, issues, and pull requests.

The database is intentionally minimal - conversation content remains on the
filesystem. The DB only tracks:
- Conversation identifiers and their disk locations
- Repositories (canonical URLs, FQN, short names)
- Issues and PRs (URLs, FQN, display names)
- Links between conversations and these entities (read vs write access)
"""

from ohtv.db.connection import get_connection, get_db_path
from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, Issue, LinkType, PullRequest, Repository
from ohtv.db.repository import (
    ConversationRepository,
    IssueRepository,
    LinkRepository,
    PRRepository,
    RepoRepository,
)

__all__ = [
    # Connection
    "get_connection",
    "get_db_path",
    "migrate",
    # Models
    "Conversation",
    "Repository",
    "Issue",
    "PullRequest",
    "LinkType",
    # Repositories (data access)
    "ConversationRepository",
    "RepoRepository",
    "IssueRepository",
    "PRRepository",
    "LinkRepository",
]
