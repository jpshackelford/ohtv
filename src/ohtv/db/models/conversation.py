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
    """
    id: str
    location: str
    registered_at: datetime | None = None
    events_mtime: float | None = None
    event_count: int = 0
