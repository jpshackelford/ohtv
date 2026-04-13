"""Processing stage model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ProcessingStage:
    """Record of a completed processing stage for a conversation.
    
    Attributes:
        conversation_id: The conversation this stage was run on
        stage: Name of the processing stage (e.g., 'refs', 'objectives')
        completed_at: When this stage completed (ISO timestamp)
        event_count: Number of events when this stage completed (checkpoint)
    """
    conversation_id: str
    stage: str
    completed_at: datetime
    event_count: int
