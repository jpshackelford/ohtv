"""Conversation model."""

from dataclasses import dataclass


@dataclass
class Conversation:
    """A conversation tracked in the index.
    
    Attributes:
        id: Unique conversation identifier (from OpenHands)
        location: Path to conversation data on disk
    """
    id: str
    location: str
