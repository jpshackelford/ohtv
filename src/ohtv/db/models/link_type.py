"""Link type enum for conversation-entity relationships."""

from enum import Enum


class LinkType(Enum):
    """Type of link between conversation and external resource.
    
    - READ: Conversation referenced or read from the resource
    - WRITE: Conversation wrote to the resource (implies read)
    
    If a conversation has WRITE access, don't also store READ.
    """
    READ = "read"
    WRITE = "write"
