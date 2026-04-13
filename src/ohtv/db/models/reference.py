"""Reference model for issues, PRs, etc."""

from dataclasses import dataclass

from ohtv.db.models.ref_type import RefType


@dataclass
class Reference:
    """A reference to an issue, PR, or similar numbered item.
    
    Unified model for issues, PRs, and potentially other reference types.
    
    Attributes:
        id: Auto-generated database ID
        ref_type: Type of reference (issue, pr, etc)
        url: Full URL to the reference
        fqn: Fully qualified name (e.g., owner/repo#123)
        display_name: Human-friendly display (e.g., repo #123)
    """
    id: int | None
    ref_type: RefType
    url: str
    fqn: str
    display_name: str
