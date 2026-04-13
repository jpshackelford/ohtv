"""Processing stages for conversation ingestion.

Each stage is a module that processes conversations and stores results in the DB.
Stages are tracked independently, allowing incremental processing.
"""

from ohtv.db.stages.actions import process_actions
from ohtv.db.stages.refs import process_refs

# Registry of available stages
STAGES = {
    "refs": process_refs,
    "actions": process_actions,
}

__all__ = [
    "STAGES",
    "process_actions",
    "process_refs",
]
