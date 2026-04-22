"""Conversation filtering utilities using the database index.

Provides filtering by PR, issue, and repository references. Requires conversations
to be indexed first (via `ohtv db scan` and `ohtv db process refs`).
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ohtv.db import (
    LinkStore,
    LinkType,
    RefType,
    ReferenceStore,
    get_connection,
    get_db_path,
)


# URL patterns for detecting different input formats
PR_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)"
)

# Relative date pattern (e.g., "7d", "2w", "1m")
RELATIVE_DATE_PATTERN = re.compile(r"^(\d+)([dwm])$", re.IGNORECASE)


def parse_date_filter(value: str) -> datetime | None:
    """Parse a date filter value, supporting both absolute and relative formats.
    
    Supported formats:
    - Absolute: YYYY-MM-DD (e.g., "2026-04-15")
    - Relative days: Nd (e.g., "7d" = 7 days ago)
    - Relative weeks: Nw (e.g., "2w" = 2 weeks ago)
    - Relative months: Nm (e.g., "1m" = 1 month ago, approximated as 30 days)
    - Keywords: "today", "yesterday"
    
    Args:
        value: Date filter string
        
    Returns:
        datetime object in UTC, or None if parsing failed
    """
    value = value.strip().lower()
    now = datetime.now(timezone.utc)
    
    # Handle keywords
    if value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if value == "yesterday":
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Handle relative dates (7d, 2w, 1m)
    match = RELATIVE_DATE_PATTERN.match(value)
    if match:
        n = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "d":
            delta = timedelta(days=n)
        elif unit == "w":
            delta = timedelta(weeks=n)
        else:  # m
            delta = timedelta(days=n * 30)  # Approximate month
        return (now - delta).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Handle absolute date (YYYY-MM-DD)
    try:
        # Parse as date and convert to datetime at midnight UTC
        parts = value.split("-")
        if len(parts) == 3:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        pass
    
    return None


def normalize_ref_pattern(pattern: str) -> str:
    """Normalize a reference pattern for FQN search.
    
    Removes spaces around '#' to match FQN format (owner/repo#123).
    """
    # Remove spaces around #
    pattern = re.sub(r"\s*#\s*", "#", pattern)
    return pattern


def parse_pr_filter(value: str) -> tuple[str, str]:
    """Parse a PR filter value into search type and pattern.
    
    Args:
        value: User-provided PR filter (URL, FQN, or short name)
        
    Returns:
        Tuple of (search_type, pattern) where:
        - search_type: 'url' for exact URL match, 'fqn' for pattern search
        - pattern: The normalized search pattern
        
    Examples:
        >>> parse_pr_filter("https://github.com/owner/repo/pull/123")
        ('url', 'https://github.com/owner/repo/pull/123')
        >>> parse_pr_filter("owner/repo#123")
        ('fqn', 'owner/repo#123')
        >>> parse_pr_filter("repo #123")
        ('fqn', 'repo#123')
    """
    value = value.strip()
    
    # Check if it's a URL
    if "://" in value:
        return ("url", value)
    
    # Otherwise treat as FQN pattern (normalize spaces)
    return ("fqn", normalize_ref_pattern(value))


def search_refs_precise(
    conn,
    pattern: str,
    ref_type: RefType,
) -> list:
    """Search refs with precise number matching.
    
    Unlike the generic LIKE search, this ensures that searching for #10
    doesn't match #100, #101, etc. by matching the end of the FQN.
    
    Args:
        conn: Database connection
        pattern: Normalized FQN pattern (e.g., "repo#123" or "owner/repo#123")
        ref_type: Type of reference to search
        
    Returns:
        List of Reference objects matching the pattern exactly
    """
    from ohtv.db.models import Reference
    
    # Use LIKE with pattern anchored to end: %repo#123 matches owner/repo#123
    # but not owner/repo#1234
    cursor = conn.execute(
        "SELECT id, ref_type, url, fqn, display_name FROM refs WHERE fqn LIKE ? AND ref_type = ?",
        (f"%{pattern}", ref_type.value),
    )
    return [
        Reference(
            id=row["id"],
            ref_type=RefType(row["ref_type"]),
            url=row["url"],
            fqn=row["fqn"],
            display_name=row["display_name"],
        )
        for row in cursor.fetchall()
    ]


def find_matching_refs(
    pattern: str,
    ref_type: RefType = RefType.PR,
) -> list[tuple[int, str]]:
    """Find refs matching the given pattern.
    
    Args:
        pattern: Search pattern (URL or FQN pattern)
        ref_type: Type of reference to search (PR or ISSUE)
        
    Returns:
        List of (ref_id, display_name) tuples for matching refs
    """
    search_type, normalized = parse_pr_filter(pattern)
    
    with get_connection() as conn:
        ref_store = ReferenceStore(conn)
        
        if search_type == "url":
            ref = ref_store.get_by_url(normalized)
            if ref and ref.id is not None:
                return [(ref.id, ref.display_name)]
            return []
        else:
            # Precise FQN search (anchored to end to avoid #1 matching #10)
            refs = search_refs_precise(conn, normalized, ref_type)
            return [(r.id, r.display_name) for r in refs if r.id is not None]


def get_conversation_ids_for_pr(pr_filter: str) -> tuple[set[str], list[str]]:
    """Get conversation IDs linked to PRs matching the filter.
    
    Args:
        pr_filter: PR filter pattern (URL, FQN, or short name)
        
    Returns:
        Tuple of (conversation_ids, matched_pr_names):
        - conversation_ids: Set of conversation IDs linked to matching PRs
        - matched_pr_names: List of display names of matched PRs
    """
    matching_refs = find_matching_refs(pr_filter, RefType.PR)
    
    if not matching_refs:
        return set(), []
    
    conversation_ids: set[str] = set()
    matched_names: list[str] = []
    
    with get_connection() as conn:
        link_store = LinkStore(conn)
        
        for ref_id, display_name in matching_refs:
            matched_names.append(display_name)
            # Get all conversations linked to this PR
            links = link_store.get_conversations_for_ref(ref_id)
            for conv_id, _link_type in links:
                conversation_ids.add(conv_id)
    
    return conversation_ids, matched_names


def get_conversation_ids_for_issue(issue_filter: str) -> tuple[set[str], list[str]]:
    """Get conversation IDs linked to issues matching the filter.
    
    Args:
        issue_filter: Issue filter pattern (URL, FQN, or short name)
        
    Returns:
        Tuple of (conversation_ids, matched_issue_names):
        - conversation_ids: Set of conversation IDs linked to matching issues
        - matched_issue_names: List of display names of matched issues
    """
    matching_refs = find_matching_refs(issue_filter, RefType.ISSUE)
    
    if not matching_refs:
        return set(), []
    
    conversation_ids: set[str] = set()
    matched_names: list[str] = []
    
    with get_connection() as conn:
        link_store = LinkStore(conn)
        
        for ref_id, display_name in matching_refs:
            matched_names.append(display_name)
            links = link_store.get_conversations_for_ref(ref_id)
            for conv_id, _link_type in links:
                conversation_ids.add(conv_id)
    
    return conversation_ids, matched_names


def get_conversation_ids_for_repo(repo_filter: str) -> tuple[set[str], list[str]]:
    """Get conversation IDs linked to repositories matching the filter.
    
    Args:
        repo_filter: Repository filter pattern (URL, owner/repo, or repo name)
        
    Returns:
        Tuple of (conversation_ids, matched_repo_names):
        - conversation_ids: Set of conversation IDs linked to matching repos
        - matched_repo_names: List of FQN names of matched repos
    """
    from ohtv.db.stores import RepoStore
    
    repo_filter = repo_filter.strip()
    
    with get_connection() as conn:
        repo_store = RepoStore(conn)
        link_store = LinkStore(conn)
        
        # Check if it's a URL first
        if "://" in repo_filter:
            repo = repo_store.get_by_url(repo_filter)
            matching_repos = [repo] if repo else []
        else:
            # Search by name (FQN or short name)
            matching_repos = list(repo_store.search_by_name(repo_filter))
        
        if not matching_repos:
            return set(), []
        
        conversation_ids: set[str] = set()
        matched_names: list[str] = []
        
        for repo in matching_repos:
            if repo.id is not None:
                matched_names.append(repo.fqn)
                links = link_store.get_conversations_for_repo(repo.id)
                for conv_id, _link_type in links:
                    conversation_ids.add(conv_id)
        
        return conversation_ids, matched_names


def is_db_available() -> bool:
    """Check if the database exists and is initialized."""
    return get_db_path().exists()


# Action type aliases for more readable CLI usage
ACTION_ALIASES = {
    # Git aliases
    "pushed": "git-push",
    "push": "git-push",
    "committed": "git-commit",
    "commit": "git-commit",
    # PR aliases  
    "opened-pr": "open-pr",
    "create-pr": "open-pr",
    "merged": "merge-pr",
    "merge": "merge-pr",
    "closed-pr": "close-pr",
    "reviewed": "pr-review",
    "review": "pr-review",
    # Issue aliases
    "opened-issue": "open-issue",
    "create-issue": "open-issue",
    "closed-issue": "close-issue",
    # CI aliases
    "ci": "check-ci",
    "checks": "check-ci",
}


def normalize_action_type(action_str: str) -> str:
    """Normalize action type string, handling aliases."""
    action_str = action_str.lower().strip()
    return ACTION_ALIASES.get(action_str, action_str)


def get_valid_action_types() -> list[str]:
    """Get list of valid action type values."""
    from ohtv.db.models.action import ActionType
    return [at.value for at in ActionType]


def get_conversation_ids_for_action(
    action_filter: str,
    target_pattern: str | None = None,
) -> tuple[set[str], str]:
    """Get conversation IDs that have a specific action type.
    
    Args:
        action_filter: Action type (e.g., "git-push", "pushed", "open-pr")
        target_pattern: Optional pattern to match against action targets
        
    Returns:
        Tuple of (conversation_ids, normalized_action_type)
    """
    action_type = normalize_action_type(action_filter)
    valid_types = get_valid_action_types()
    
    if action_type not in valid_types:
        return set(), action_type
    
    with get_connection() as conn:
        if target_pattern:
            # Filter by action type AND target matching pattern
            cursor = conn.execute(
                """
                SELECT DISTINCT conversation_id 
                FROM actions 
                WHERE action_type = ? AND target LIKE ?
                """,
                (action_type, f"%{target_pattern}%"),
            )
        else:
            # Filter by action type only
            cursor = conn.execute(
                """
                SELECT DISTINCT conversation_id 
                FROM actions 
                WHERE action_type = ?
                """,
                (action_type,),
            )
        
        return {row[0] for row in cursor.fetchall()}, action_type


def get_conversation_ids_for_action_and_repo(
    action_filter: str,
    repo_filter: str,
) -> tuple[set[str], set[str], str, list[str]]:
    """Get conversation IDs matching both action and repo filters.
    
    This tries to do precise matching where possible:
    1. If action has target URLs, match action target against repo URL
    2. If action has no target, match conversations that have both:
       - The action type
       - A write link to the repo
       
    Args:
        action_filter: Action type (e.g., "git-push")
        repo_filter: Repo pattern (e.g., "OpenPaw" or "owner/repo")
        
    Returns:
        Tuple of (definite_matches, possible_matches, action_type, matched_repo_names)
        - definite_matches: Conversations where action target matched repo
        - possible_matches: Conversations with action AND write link to repo (ambiguous)
    """
    from ohtv.db.stores import RepoStore
    
    action_type = normalize_action_type(action_filter)
    valid_types = get_valid_action_types()
    
    if action_type not in valid_types:
        return set(), set(), action_type, []
    
    repo_filter = repo_filter.strip()
    
    with get_connection() as conn:
        repo_store = RepoStore(conn)
        link_store = LinkStore(conn)
        
        # Find matching repos
        if "://" in repo_filter:
            repo = repo_store.get_by_url(repo_filter)
            matching_repos = [repo] if repo else []
        else:
            matching_repos = list(repo_store.search_by_name(repo_filter))
        
        if not matching_repos:
            return set(), set(), action_type, []
        
        matched_repo_names = [r.fqn for r in matching_repos if r.id is not None]
        
        # Build patterns for matching action targets against repo URLs
        repo_url_patterns = []
        repo_ids = []
        for repo in matching_repos:
            if repo.id is not None:
                repo_ids.append(repo.id)
                # Extract URL pattern from canonical_url
                # e.g., "https://github.com/owner/repo" -> "github.com/owner/repo"
                url = repo.canonical_url
                if "://" in url:
                    url = url.split("://", 1)[1]
                repo_url_patterns.append(url)
        
        definite_matches: set[str] = set()
        possible_matches: set[str] = set()
        
        # Get conversations with this action type
        cursor = conn.execute(
            """
            SELECT conversation_id, target
            FROM actions 
            WHERE action_type = ?
            """,
            (action_type,),
        )
        
        action_convs_with_targets: dict[str, list[str]] = {}  # conv_id -> list of targets
        action_convs_without_targets: set[str] = set()
        
        for row in cursor.fetchall():
            conv_id = row[0]
            target = row[1]
            
            if target:
                if conv_id not in action_convs_with_targets:
                    action_convs_with_targets[conv_id] = []
                action_convs_with_targets[conv_id].append(target)
            else:
                action_convs_without_targets.add(conv_id)
        
        # Check conversations with targets - definite match if target matches repo
        for conv_id, targets in action_convs_with_targets.items():
            for target in targets:
                for pattern in repo_url_patterns:
                    if pattern in target:
                        definite_matches.add(conv_id)
                        break
                if conv_id in definite_matches:
                    break
        
        # Check conversations without targets - possible match if has write link to repo
        for conv_id in action_convs_without_targets:
            if conv_id in definite_matches:
                continue  # Already a definite match from another action
            
            # Check if this conversation has a write link to any matching repo
            for repo_id in repo_ids:
                links = link_store.get_conversations_for_repo(repo_id, LinkType.WRITE)
                conv_ids_with_write = {link[0] for link in links}
                if conv_id in conv_ids_with_write:
                    possible_matches.add(conv_id)
                    break
        
        return definite_matches, possible_matches, action_type, matched_repo_names


def normalize_conversation_id(conv_id: str) -> str:
    """Normalize conversation ID by removing dashes.
    
    The database stores IDs without dashes (directory names), but
    LocalSource may return IDs with dashes (from base_state.json).
    """
    return conv_id.replace("-", "")


def filter_conversations_by_ids(
    conversations: list,
    allowed_ids: set[str],
) -> list:
    """Filter conversation list to only include those with IDs in allowed set.
    
    Handles ID format differences by normalizing both sides (removing dashes).
    
    Args:
        conversations: List of ConversationInfo objects
        allowed_ids: Set of conversation IDs to include (may have any format)
        
    Returns:
        Filtered list containing only conversations with matching IDs
    """
    # Normalize allowed IDs for comparison
    normalized_allowed = {normalize_conversation_id(id) for id in allowed_ids}
    return [c for c in conversations if normalize_conversation_id(c.id) in normalized_allowed]
