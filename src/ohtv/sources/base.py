"""Abstract data source interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ConversationInfo:
    """Summary information about a conversation."""

    id: str
    title: str | None
    created_at: datetime | None
    updated_at: datetime | None
    event_count: int | None = None
    selected_repository: str | None = None
    source: str = "local"  # "local" or "cloud"
    dir_name: str | None = None  # Actual directory name (may differ from id)
    # Error tracking fields (populated lazily)
    error_count: int | None = None
    error_types: dict[str, int] | None = None  # ErrorType name -> count
    has_terminal_error: bool | None = None
    execution_status: str | None = None  # From base_state.json

    @property
    def duration(self) -> timedelta | None:
        """Calculate conversation duration."""
        if self.created_at and self.updated_at:
            return self.updated_at - self.created_at
        return None

    @property
    def short_id(self) -> str:
        """Get first 7 characters of ID for display."""
        return self.id[:7]

    @property
    def lookup_id(self) -> str:
        """Get the ID to use for directory lookup (dir_name if set, else id)."""
        return self.dir_name or self.id


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
