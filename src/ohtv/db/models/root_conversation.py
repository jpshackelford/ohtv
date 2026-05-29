"""RootConversation model — a conversation tree grouped by its root.

Issue #122. ``RootConversation`` is the projection produced by
``ConversationStore.list_roots`` and the ``conversations_by_root``
SQL view. It rolls subtree rows onto the root so downstream commands
(reports, list, RAG) can aggregate at the "what the user did" grain
without coordinating per-call group-bys.

Display fields (``title``, ``source``, ``selected_repository``,
``labels``, ``location``) come from the root's own row — subs are
implementation detail. Time fields span the subtree:
``created_at = MIN`` over the tree, ``updated_at = MAX`` over the
tree. Quantitative fields aggregate: ``event_count = SUM`` over the
tree; ``conversation_count`` and ``sub_count`` are the new fields
that tell callers how big the tree is.

This is a *read-only* projection; there is no ``upsert``. To mutate
a root, mutate its underlying ``conversations`` row.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RootConversation:
    """A conversation tree rolled up onto its root row.

    Attributes:
        id: The root's id (normalized / dashless). Equals
            ``conversations.root_conversation_id`` for every row in
            the tree.
        title: Root's title.
        source: Root's source identifier ('local', 'cloud', ...).
        selected_repository: Root's selected_repository value.
        labels: Root's labels dict (parsed from JSON).
        location: Root's filesystem location.
        created_at: Earliest ``created_at`` over the subtree.
        updated_at: Latest ``updated_at`` over the subtree.
        event_count: Sum of ``event_count`` over the subtree.
        conversation_count: Number of rows in the tree (≥ 1).
        sub_count: ``conversation_count - 1``; 0 when this is a
            standalone root.
    """

    id: str
    title: str | None = None
    source: str | None = None
    selected_repository: str | None = None
    labels: dict[str, str] | None = None
    location: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    event_count: int = 0
    conversation_count: int = 1
    sub_count: int = 0
