"""Push-to-PR linking stage - correlates git pushes with their PRs.

This stage:
1. Builds a map of branch -> PR URL from OPEN_PR actions
2. For each GIT_PUSH action with branch info, finds the corresponding PR
3. Updates conversation_refs to mark the PR as having a "pushed" interaction

This runs after the 'actions' stage and requires that stage to be complete first.
"""

import json
import sqlite3

from ohtv.db.models import Conversation, LinkType
from ohtv.db.models.action import ActionType
from ohtv.db.stores import ActionStore, LinkStore, ReferenceStore, StageStore


STAGE_NAME = "push_pr_links"


def process_push_pr_links(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Process push-to-PR linking for a single conversation.
    
    Correlates GIT_PUSH actions with OPEN_PR actions based on matching
    branch and repository information. When a push is found that matches
    a PR's head branch, marks the PR as having a write interaction.
    
    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    action_store = ActionStore(conn)
    ref_store = ReferenceStore(conn)
    link_store = LinkStore(conn)
    stage_store = StageStore(conn)
    
    # Get all actions for this conversation
    all_actions = action_store.get_by_conversation(conversation.id)
    
    # Build branch -> PR mappings from OPEN_PR actions
    branch_to_pr = _build_branch_pr_map(all_actions)
    
    if not branch_to_pr:
        # No PR with branch info, nothing to correlate
        stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)
        return
    
    # Find GIT_PUSH actions with branch info
    push_actions = [a for a in all_actions if a.action_type == ActionType.GIT_PUSH]
    
    # For each push, check if it matches a PR's branch
    for push in push_actions:
        if not push.metadata:
            continue
        
        push_branch = push.metadata.get("branch")
        push_owner = push.metadata.get("owner")
        push_repo = push.metadata.get("repo")
        
        # Require full qualification (owner/repo/branch) to avoid cross-repo mismatches
        if not push_branch or not push_owner or not push_repo:
            continue
        
        # Build a key for this push
        push_key = _make_branch_key(push_owner, push_repo, push_branch)
        
        # Check if this branch has an associated PR
        pr_url = branch_to_pr.get(push_key)
        
        if pr_url:
            # Mark this PR as having a write interaction
            ref = ref_store.get_by_url(pr_url)
            if ref:
                link_store.link_ref(conversation.id, ref.id, LinkType.WRITE)
    
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)


def _build_branch_pr_map(actions: list) -> dict[str, str]:
    """Build a map of branch (key) -> PR URL from OPEN_PR actions.
    
    Returns a dict where keys are "owner/repo:branch" (fully qualified).
    Only includes PRs with complete metadata to avoid cross-repo mismatches.
    """
    branch_to_pr = {}
    
    for action in actions:
        if action.action_type != ActionType.OPEN_PR:
            continue
        
        if not action.metadata or not action.target:
            continue
        
        head_branch = action.metadata.get("head_branch")
        owner = action.metadata.get("owner")
        repo = action.metadata.get("repo")
        pr_url = action.target
        
        # Require full qualification to avoid ambiguity
        if not head_branch or not owner or not repo:
            continue
        
        full_key = _make_branch_key(owner, repo, head_branch)
        branch_to_pr[full_key] = pr_url
    
    return branch_to_pr


def _make_branch_key(owner: str | None, repo: str | None, branch: str) -> str:
    """Create a lookup key for branch-to-PR mapping."""
    if owner and repo:
        return f"{owner}/{repo}:{branch}"
    return branch
