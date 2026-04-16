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
- Processing stage completion for incremental ingestion
"""

from ohtv.db.connection import get_connection, get_db_path
from ohtv.db.maintenance import ensure_db_ready, run_maintenance
from ohtv.db.migrations import migrate
from ohtv.db.models import (
    Conversation,
    LinkType,
    ProcessingStage,
    Reference,
    RefType,
    Repository,
)
from ohtv.db.scanner import ScanResult, scan_conversations
from ohtv.db.stores import (
    ConversationStore,
    LinkStore,
    ReferenceStore,
    RepoStore,
    StageStore,
)

__all__ = [
    # Connection
    "get_connection",
    "get_db_path",
    "migrate",
    "ensure_db_ready",
    "run_maintenance",
    # Scanner
    "scan_conversations",
    "ScanResult",
    # Models
    "Conversation",
    "LinkType",
    "ProcessingStage",
    "Reference",
    "RefType",
    "Repository",
    # Stores (data access)
    "ConversationStore",
    "LinkStore",
    "ReferenceStore",
    "RepoStore",
    "StageStore",
]
