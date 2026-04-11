"""Database module for ohtv indexing.

This module provides SQLite-based indexing for conversation metadata,
specifically for tracking relationships between conversations and external
references like repositories, issues, and pull requests.

The database is intentionally minimal - conversation content remains on the
filesystem. The DB only tracks:
- Conversation identifiers and their disk locations
- Repositories (canonical URLs, FQN, short names)
- References (issues, PRs, etc.) with type discriminator
- Links between conversations and these entities (read vs write access)
"""

from ohtv.db.connection import get_connection, get_db_path
from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, LinkType, Reference, RefType, Repository
from ohtv.db.stores import (
    ConversationStore,
    LinkStore,
    ReferenceStore,
    RepoStore,
)

__all__ = [
    # Connection
    "get_connection",
    "get_db_path",
    "migrate",
    # Models
    "Conversation",
    "Repository",
    "Reference",
    "RefType",
    "LinkType",
    # Stores (data access)
    "ConversationStore",
    "RepoStore",
    "ReferenceStore",
    "LinkStore",
]
