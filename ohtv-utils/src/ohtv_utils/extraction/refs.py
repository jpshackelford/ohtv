"""URL parsing for repository and reference (issue/PR) URLs.

Supports GitHub, GitLab, and Bitbucket URL patterns. Returns plain dicts
for maximum flexibility - consumers can use their own model classes if desired.
"""

import re
from typing import Literal

# Type alias for ref types
RefType = Literal["issue", "pr"]


def parse_repo_url(url: str) -> dict[str, str] | None:
    """Parse a repository URL into structured components.

    Supports GitHub, GitLab (including nested groups), and Bitbucket URLs.
    Returns a dict with canonical_url, fqn (fully qualified name), and
    short_name.

    Args:
        url: Repository URL (e.g., "https://github.com/owner/repo")

    Returns:
        Dict with keys: canonical_url, fqn, short_name. Returns None if
        the URL doesn't match any known pattern.

    Example:
        >>> parse_repo_url("https://github.com/jpshackelford/ohtv")
        {'canonical_url': 'https://github.com/jpshackelford/ohtv',
         'fqn': 'jpshackelford/ohtv',
         'short_name': 'ohtv'}

        >>> parse_repo_url("https://gitlab.com/group/subgroup/repo")
        {'canonical_url': 'https://gitlab.com/group/subgroup/repo',
         'fqn': 'group/subgroup/repo',
         'short_name': 'repo'}
    """
    # Normalize URL
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    # GitHub pattern
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url)
    if match:
        owner, repo = match.groups()
        return {
            "canonical_url": f"https://github.com/{owner}/{repo}",
            "fqn": f"{owner}/{repo}",
            "short_name": repo,
        }

    # GitLab pattern (handles nested groups)
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)", url)
    if match:
        group_path, repo = match.groups()
        return {
            "canonical_url": f"https://gitlab.com/{group_path}/{repo}",
            "fqn": f"{group_path}/{repo}",
            "short_name": repo,
        }

    # Bitbucket pattern
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)", url)
    if match:
        owner, repo = match.groups()
        return {
            "canonical_url": f"https://bitbucket.org/{owner}/{repo}",
            "fqn": f"{owner}/{repo}",
            "short_name": repo,
        }

    return None


def parse_ref_url(url: str, ref_type: RefType) -> dict[str, str] | None:
    """Parse an issue or PR URL into structured components.

    Supports GitHub issues/PRs, GitLab issues/MRs, and Bitbucket PRs.
    Returns a dict with ref_type, url, fqn, and display_name.

    Args:
        url: Issue or PR URL (e.g., "https://github.com/owner/repo/pull/123")
        ref_type: Type of reference - either "issue" or "pr"

    Returns:
        Dict with keys: ref_type, url, fqn, display_name. Returns None if
        the URL doesn't match any known pattern.

    Example:
        >>> parse_ref_url("https://github.com/owner/repo/pull/123", "pr")
        {'ref_type': 'pr',
         'url': 'https://github.com/owner/repo/pull/123',
         'fqn': 'owner/repo#123',
         'display_name': 'repo #123'}

        >>> parse_ref_url("https://gitlab.com/group/repo/-/merge_requests/456", "pr")
        {'ref_type': 'pr',
         'url': 'https://gitlab.com/group/repo/-/merge_requests/456',
         'fqn': 'group/repo!456',
         'display_name': 'repo !456'}
    """
    # GitHub PR
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{owner}/{repo}#{number}",
            "display_name": f"{repo} #{number}",
        }

    # GitHub issue
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{owner}/{repo}#{number}",
            "display_name": f"{repo} #{number}",
        }

    # GitLab MR
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)/-/merge_requests/(\d+)", url)
    if match:
        group_path, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{group_path}/{repo}!{number}",
            "display_name": f"{repo} !{number}",
        }

    # GitLab issue
    match = re.match(r"https://gitlab\.com/(.+)/([^/]+)/-/issues/(\d+)", url)
    if match:
        group_path, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{group_path}/{repo}#{number}",
            "display_name": f"{repo} #{number}",
        }

    # Bitbucket PR
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{owner}/{repo}#{number}",
            "display_name": f"{repo} #{number}",
        }

    # Bitbucket issue (if supported in future)
    match = re.match(r"https://bitbucket\.org/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        owner, repo, number = match.groups()
        return {
            "ref_type": ref_type,
            "url": url,
            "fqn": f"{owner}/{repo}#{number}",
            "display_name": f"{repo} #{number}",
        }

    return None
