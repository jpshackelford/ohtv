"""Repository model for git repositories."""

from dataclasses import dataclass


@dataclass
class Repository:
    """A git repository reference.
    
    Attributes:
        id: Auto-generated database ID
        canonical_url: Full upstream URL (e.g., https://github.com/owner/repo)
        fqn: Fully qualified name (e.g., owner/repo)
        short_name: Just the repo name (e.g., repo)
    
    Note: canonical_url should be the actual remote being worked on.
    If working on a fork, store the fork URL, not its upstream.
    """
    id: int | None
    canonical_url: str
    fqn: str
    short_name: str
