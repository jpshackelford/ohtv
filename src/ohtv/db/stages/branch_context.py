"""Branch context processor - tracks branches worked on in a conversation.

This processor:
1. Walks events in temporal order
2. Tracks branch transitions (from git checkout/switch commands)
3. Creates branch refs for branches that were pushed to
4. Links conversations to branches with appropriate link types

This provides:
- Branch refs visible in `ohtv refs` output
- Foundation for push-to-PR correlation
- Temporal branch state for other processors
"""

import re
import sqlite3
from typing import Sequence

from ohtv.db.models import Conversation, LinkType, Reference, RefType
from ohtv.db.models.action import ActionType
from ohtv.db.stores import ActionStore, LinkStore, ReferenceStore, StageStore


STAGE_NAME = "branch_context"

# Patterns for git checkout/switch commands
# git checkout <branch>
# git checkout -b <branch>
# git switch <branch>
# git switch -c <branch>
GIT_CHECKOUT_PATTERN = re.compile(
    r"git\s+(?:checkout|switch)\s+(?:-[bc]\s+)?([^\s;&|]+)"
)

# Pattern to extract branch from "git checkout -b <branch> <start-point>"
GIT_CHECKOUT_NEW_BRANCH = re.compile(
    r"git\s+checkout\s+-b\s+([^\s;&|]+)"
)


def process_branch_context(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Process branch context for a conversation.
    
    Walks events in temporal order to:
    1. Track current branch from checkout/switch commands
    2. Create branch refs for pushed branches
    3. Link conversation to branches
    
    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    action_store = ActionStore(conn)
    ref_store = ReferenceStore(conn)
    link_store = LinkStore(conn)
    stage_store = StageStore(conn)
    
    # Get all actions ordered by id (which preserves temporal order)
    all_actions = action_store.get_by_conversation(conversation.id)
    
    # Track branches we've seen pushes to (with full qualification)
    # Key: (owner, repo, branch) -> list of event_ids
    branch_pushes: dict[tuple[str, str, str], list[str]] = {}
    
    # Track branch transitions for future use
    # This could be stored in a separate table if needed
    branch_timeline: list[dict] = []
    
    # Process actions in order
    for action in all_actions:
        if action.action_type == ActionType.GIT_PUSH:
            _process_push(action, branch_pushes, branch_timeline)
    
    # Create branch refs and link to conversation
    for (owner, repo, branch), event_ids in branch_pushes.items():
        # Create or get the branch ref
        branch_url = f"https://github.com/{owner}/{repo}/tree/{branch}"
        branch_fqn = f"{owner}/{repo}:{branch}"
        branch_display = f"{repo}:{branch}"
        
        ref = Reference(
            id=None,
            ref_type=RefType.BRANCH,
            url=branch_url,
            fqn=branch_fqn,
            display_name=branch_display,
        )
        ref_id = ref_store.upsert(ref)
        
        # Link conversation to branch with WRITE (we pushed to it)
        link_store.link_ref(conversation.id, ref_id, LinkType.WRITE)
    
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)


def _process_push(
    action,
    branch_pushes: dict[tuple[str, str, str], list[str]],
    branch_timeline: list[dict],
) -> None:
    """Process a GIT_PUSH action to extract branch info.
    
    Args:
        action: The GIT_PUSH action
        branch_pushes: Dict to accumulate branch -> event_ids
        branch_timeline: List to accumulate branch events for timeline
    """
    if not action.metadata:
        return
    
    owner = action.metadata.get("owner")
    repo = action.metadata.get("repo")
    branch = action.metadata.get("branch")
    
    # Require full qualification
    if not owner or not repo or not branch:
        return
    
    key = (owner, repo, branch)
    if key not in branch_pushes:
        branch_pushes[key] = []
    branch_pushes[key].append(action.event_id)
    
    # Record in timeline
    branch_timeline.append({
        "event_id": action.event_id,
        "action": "push",
        "owner": owner,
        "repo": repo,
        "branch": branch,
    })


def get_branch_timeline(
    conn: sqlite3.Connection,
    conversation_id: str,
) -> Sequence[dict]:
    """Get the branch timeline for a conversation.
    
    Returns a list of branch events in temporal order, useful for
    understanding what branches were worked on and when.
    
    Note: This currently reconstructs from actions. In the future,
    we could cache this in a dedicated table.
    """
    action_store = ActionStore(conn)
    actions = action_store.get_by_conversation(conversation_id)
    
    timeline = []
    for action in actions:
        if action.action_type == ActionType.GIT_PUSH and action.metadata:
            owner = action.metadata.get("owner")
            repo = action.metadata.get("repo")
            branch = action.metadata.get("branch")
            if owner and repo and branch:
                timeline.append({
                    "event_id": action.event_id,
                    "action": "push",
                    "owner": owner,
                    "repo": repo, 
                    "branch": branch,
                })
    
    return timeline
