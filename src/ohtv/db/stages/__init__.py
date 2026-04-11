"""Processing stages for conversation ingestion.

Each stage is a module that processes conversations and stores results in the DB.
Stages are tracked independently, allowing incremental processing.
"""

from ohtv.db.stages.refs import process_refs

# Registry of available stages
STAGES = {
    "refs": process_refs,
}

__all__ = [
    "STAGES",
    "process_refs",
]
