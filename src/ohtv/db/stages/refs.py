"""Refs processing stage - extracts and stores repository/issue/PR references.

This stage:
1. Extracts git URLs (repos, issues, PRs) from conversation events
2. Detects interactions (pushed, created, commented, etc.)
3. Stores results in the database with appropriate link types
"""

import re
import sqlite3
from pathlib import Path

from ohtv.db.models import Conversation, LinkType, Reference, RefType, Repository
from ohtv.db.stores import (
    LinkStore,
    ReferenceStore,
    RepoStore,
    StageStore,
)


STAGE_NAME = "refs"


def process_refs(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Process refs for a single conversation and store in DB.
    
    Extracts repositories, issues, and PRs from conversation events,
    detects what actions were taken on them, and stores the relationships
    in the database.
    
    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    conv_dir = Path(conversation.location)
    
    # Import extraction functions from CLI (they're the source of truth)
    # This avoids duplicating the complex regex logic
    from ohtv.cli import (
        _extract_refs_from_conversation,
        _detect_interactions_from_conversation,
    )
    
    # Extract refs from events
    refs = _extract_refs_from_conversation(conv_dir)
    
    # Detect interactions
    interactions = _detect_interactions_from_conversation(conv_dir, refs)
    
    # Store results
    repo_store = RepoStore(conn)
    ref_store = ReferenceStore(conn)
    link_store = LinkStore(conn)
    stage_store = StageStore(conn)
    
    # Process repositories - only those with detected interactions
    # This filters out incidental mentions (URLs in error messages, user pastes, etc.)
    for repo_url in refs["repos"]:
        repo_interactions = interactions.repos.get(repo_url, set())
        if not repo_interactions:
            continue  # Skip repos with no detected interactions
        
        repo = _parse_repo_url(repo_url)
        if repo:
            repo_id = repo_store.upsert(repo)
            link_type = _determine_link_type(repo_interactions)
            link_store.link_repo(conversation.id, repo_id, link_type)
    
    # Process PRs
    for pr_url in refs["prs"]:
        ref = _parse_ref_url(pr_url, RefType.PR)
        if ref:
            ref_id = ref_store.upsert(ref)
            
            pr_interactions = interactions.prs.get(pr_url, set())
            link_type = _determine_link_type(pr_interactions)
            
            link_store.link_ref(conversation.id, ref_id, link_type)
    
    # Process issues
    for issue_url in refs["issues"]:
        ref = _parse_ref_url(issue_url, RefType.ISSUE)
        if ref:
            ref_id = ref_store.upsert(ref)
            
            issue_interactions = interactions.issues.get(issue_url, set())
            link_type = _determine_link_type(issue_interactions)
            
            link_store.link_ref(conversation.id, ref_id, link_type)
    
    # Mark stage complete
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)


def _parse_repo_url(url: str) -> Repository | None:
    """Parse a repository URL into a Repository model.
    
    Returns Repository or None if unparseable.
    """
    # Normalize URL
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    
    # GitHub pattern
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url)
    if match:
        owner, repo = match.groups()
        return Repository(
            id=None,
            canonical_url=f"https://github.com/{owner}/{repo}",
            fqn=f"{owner}/{repo}",
            short_name=repo,
        )
    
    # GitLab pattern (handles nested groups)
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)", url)
    if match:
        group_path, repo = match.groups()
        return Repository(
            id=None,
            canonical_url=f"https://gitlab.com/{group_path}/{repo}",
            fqn=f"{group_path}/{repo}",
            short_name=repo,
        )
    
    # Bitbucket pattern
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)", url)
    if match:
        owner, repo = match.groups()
        return Repository(
            id=None,
            canonical_url=f"https://bitbucket.org/{owner}/{repo}",
            fqn=f"{owner}/{repo}",
            short_name=repo,
        )
    
    return None


def _parse_ref_url(url: str, ref_type: RefType) -> Reference | None:
    """Parse an issue/PR URL into a Reference model.
    
    Returns Reference or None if unparseable.
    """
    # GitHub PR
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{owner}/{repo}#{number}",
            display_name=f"{repo} #{number}",
        )
    
    # GitHub issue
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{owner}/{repo}#{number}",
            display_name=f"{repo} #{number}",
        )
    
    # GitLab MR
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)/-/merge_requests/(\d+)", url)
    if match:
        group_path, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{group_path}/{repo}!{number}",
            display_name=f"{repo} !{number}",
        )
    
    # GitLab issue
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)/-/issues/(\d+)", url)
    if match:
        group_path, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{group_path}/{repo}#{number}",
            display_name=f"{repo} #{number}",
        )
    
    # Bitbucket PR
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{owner}/{repo}#{number}",
            display_name=f"{repo} #{number}",
        )
    
    # Bitbucket issue
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return Reference(
            id=None,
            ref_type=ref_type,
            url=url,
            fqn=f"{owner}/{repo}#{number}",
            display_name=f"{repo} #{number}",
        )
    
    return None


def _determine_link_type(interactions: set[str]) -> LinkType:
    """Determine link type based on detected interactions.
    
    Write interactions: pushed, committed, created, commented, reviewed, merged, closed
    Read interactions: cloned, fetched, pulled, viewed, browsed, api_called
    
    Note: 'cloned' is READ because cloning is research/setup, not modification.
    Actual changes require commit + push.
    """
    write_actions = {"pushed", "committed", "created", "commented", "reviewed", "merged", "closed"}
    # read_actions = {"cloned", "fetched", "pulled", "viewed", "browsed", "api_called"}
    
    if interactions & write_actions:
        return LinkType.WRITE
    return LinkType.READ
