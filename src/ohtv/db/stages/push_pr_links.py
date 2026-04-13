"""Push-to-PR linking stage - correlates git pushes with their PRs.

This stage uses temporal ordering to correctly link pushes to PRs:

1. Forward pass: Process actions in order, tracking "active PR" per branch
   - When OPEN_PR is seen, that PR becomes active for its branch
   - When GIT_PUSH is seen, link to currently active PR (if any)
   - Pushes before any PR on their branch are collected as "orphans"

2. Backward pass: Link orphan pushes to first subsequent PR on their branch
   - Pushes that occurred before PR creation are linked retrospectively

This runs after the 'actions' stage and requires that stage to be complete first.
"""

import sqlite3

from ohtv.db.models import Conversation, LinkType
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stores import ActionStore, LinkStore, ReferenceStore, StageStore


STAGE_NAME = "push_pr_links"


def process_push_pr_links(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Process push-to-PR linking for a single conversation.
    
    Uses temporal ordering to correctly link pushes to PRs:
    - Pushes after PR creation link to that PR
    - Pushes before PR creation link to the first subsequent PR on the same branch
    
    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    action_store = ActionStore(conn)
    ref_store = ReferenceStore(conn)
    link_store = LinkStore(conn)
    stage_store = StageStore(conn)
    
    # Get all actions for this conversation (already ordered by id = temporal order)
    all_actions = action_store.get_by_conversation(conversation.id)
    
    # Track active PR per branch (temporal state)
    branch_active_pr: dict[str, str] = {}  # branch_key → pr_url
    
    # Track orphan pushes (pushes before any PR on their branch)
    orphan_pushes: list[tuple[ConversationAction, str]] = []  # (action, branch_key)
    
    # Track all PRs we've seen for each branch (for backward linking)
    branch_first_pr: dict[str, str] = {}  # branch_key → first pr_url seen
    
    # Forward pass: process actions in temporal order
    for action in all_actions:
        if action.action_type == ActionType.OPEN_PR:
            branch_key = _get_pr_branch_key(action)
            if branch_key and action.target:
                # This PR becomes active for this branch
                branch_active_pr[branch_key] = action.target
                # Track first PR per branch for backward linking
                if branch_key not in branch_first_pr:
                    branch_first_pr[branch_key] = action.target
                    
        elif action.action_type == ActionType.GIT_PUSH:
            branch_key = _get_push_branch_key(action)
            if not branch_key:
                continue
            
            pr_url = branch_active_pr.get(branch_key)
            if pr_url:
                # Link to currently active PR
                _link_push_to_pr(pr_url, conversation.id, ref_store, link_store)
            else:
                # No active PR yet - save for backward pass
                orphan_pushes.append((action, branch_key))
    
    # Backward pass: link orphan pushes to first subsequent PR on their branch
    for push_action, branch_key in orphan_pushes:
        first_pr = branch_first_pr.get(branch_key)
        if first_pr:
            _link_push_to_pr(first_pr, conversation.id, ref_store, link_store)
    
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)


def _get_pr_branch_key(action: ConversationAction) -> str | None:
    """Extract branch key from an OPEN_PR action.
    
    Returns fully qualified key (owner/repo:branch) or None if insufficient metadata.
    """
    if not action.metadata:
        return None
    
    head_branch = action.metadata.get("head_branch")
    owner = action.metadata.get("owner")
    repo = action.metadata.get("repo")
    
    if not head_branch or not owner or not repo:
        return None
    
    return _make_branch_key(owner, repo, head_branch)


def _get_push_branch_key(action: ConversationAction) -> str | None:
    """Extract branch key from a GIT_PUSH action.
    
    Returns fully qualified key (owner/repo:branch) or None if insufficient metadata.
    """
    if not action.metadata:
        return None
    
    branch = action.metadata.get("branch")
    owner = action.metadata.get("owner")
    repo = action.metadata.get("repo")
    
    # Require full qualification to avoid cross-repo mismatches
    if not branch or not owner or not repo:
        return None
    
    return _make_branch_key(owner, repo, branch)


def _link_push_to_pr(
    pr_url: str,
    conversation_id: str,
    ref_store: ReferenceStore,
    link_store: LinkStore,
) -> None:
    """Link a push to a PR by marking the PR with a WRITE interaction."""
    ref = ref_store.get_by_url(pr_url)
    if ref:
        link_store.link_ref(conversation_id, ref.id, LinkType.WRITE)


def _make_branch_key(owner: str | None, repo: str | None, branch: str) -> str:
    """Create a lookup key for branch-to-PR mapping."""
    if owner and repo:
        return f"{owner}/{repo}:{branch}"
    return branch
