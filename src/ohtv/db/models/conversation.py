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
