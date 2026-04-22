"""Processing stages for conversation ingestion.

Each stage is a module that processes conversations and stores results in the DB.
Stages are tracked independently, allowing incremental processing.

Stage ordering:
1. refs - Extract repo/issue/PR references from URLs
2. actions - Recognize actions (file edits, git ops, PRs, etc.)
3. branch_context - Track branches and create branch refs (requires actions)
4. push_pr_links - Correlate pushes with PRs (requires actions, branch_context)
5. summaries - Extract summaries from objective analysis cache
"""

from ohtv.db.stages.actions import process_actions
from ohtv.db.stages.branch_context import process_branch_context
from ohtv.db.stages.push_pr_links import process_push_pr_links
from ohtv.db.stages.refs import process_refs
from ohtv.db.stages.summaries import process_summaries

# Registry of available stages
# Order matters for dependencies
STAGES = {
    "refs": process_refs,
    "actions": process_actions,
    "branch_context": process_branch_context,
    "push_pr_links": process_push_pr_links,
    "summaries": process_summaries,
}

__all__ = [
    "STAGES",
    "process_actions",
    "process_branch_context",
    "process_push_pr_links",
    "process_refs",
    "process_summaries",
]
