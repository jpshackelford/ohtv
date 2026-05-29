"""Conversation model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Conversation:
    """A conversation tracked in the index.
    
    Attributes:
        id: Unique conversation identifier (from OpenHands)
        location: Path to conversation data on disk
        registered_at: When the conversation was first discovered (ISO timestamp)
        events_mtime: Unix timestamp of events directory (for fast change detection)
        event_count: Number of events in the conversation
        title: Conversation title (from base_state or first user message)
        created_at: When the conversation started (UTC)
        updated_at: When the conversation was last updated (UTC)
        selected_repository: Repository selected for this conversation
        source: Source identifier ('local', 'cloud', or custom name)
        summary: Brief summary of conversation goal/objective (for RAG)
        labels: Cloud-sourced labels/tags (key=value pairs from API)
        parent_conversation_id: For sub-conversations spawned by agent
            delegation, the id of the parent conversation (normalized
            / dashless, matching how ``id`` is stored). NULL for root
            conversations and for local CLI conversations.
            Populated by ``ohtv sync`` from the cloud listing payload
            (Issue #108).
        root_conversation_id: The top of the parent chain for this
            conversation (normalized / dashless). For roots this
            equals ``id``; for subs it walks
            ``parent_conversation_id`` to the top. Populated at write
            time by ``ConversationStore.upsert`` /
            ``record_cloud_download``. NULL only on rows written by
            pre-#122 code that haven't been re-scanned yet — the
            scanner / sync paths backfill on next pass; the
            migration also backfills existing rows.
            See AGENTS.md item #32 for the policy ("the root is the
            unit of 'what the user did'"). Issue #122.
    """
    id: str
    location: str
    registered_at: datetime | None = None
    events_mtime: float | None = None
    event_count: int = 0
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    selected_repository: str | None = None
    source: str | None = None
    summary: str | None = None
    labels: dict[str, str] | None = None
    parent_conversation_id: str | None = None
    root_conversation_id: str | None = None
