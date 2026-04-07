"""Abstract data source interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ConversationInfo:
    """Summary information about a conversation."""

    id: str
    title: str | None
    created_at: datetime | None
    updated_at: datetime | None
    event_count: int | None = None
    selected_repository: str | None = None


@dataclass
class Event:
    """A conversation event."""

    id: str
    timestamp: datetime
    source: str  # "user", "agent", "environment"
    kind: str  # "MessageEvent", "ActionEvent", etc.
    data: dict  # Full event data


class DataSource(ABC):
    """Abstract interface for conversation data sources."""

    @abstractmethod
    def list_conversations(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConversationInfo]:
        """List available conversations."""

    @abstractmethod
    def get_conversation(self, conversation_id: str) -> ConversationInfo | None:
        """Get a single conversation by ID."""

    @abstractmethod
    def get_events(
        self,
        conversation_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Event]:
        """Get events for a conversation."""
