"""Contribution detection stage.

Walks the (already-processed) ``actions`` for a conversation and records
the conversation's contributions to PRs in two tables created by
migration 016:

- ``change_refs`` rows (one per ``(repo, pr_number)``) are upserted via
  :class:`ContributionsStore`. Multiple conversations contributing to the
  same PR share a single ``change_refs`` row (many-to-many).
- ``conversation_contributions`` rows link the conversation to each
  change with a ``contribution_type`` of ``created``, ``pushed``, or
  ``merged``.

Mapping from action → contribution:

- ``OPEN_PR``  → ``contribution_type="created"``
- ``MERGE_PR`` → ``contribution_type="merged"``
- ``GIT_PUSH`` to a branch with an active PR → ``contribution_type="pushed"``

Push-to-PR correlation mirrors the temporal logic in
:mod:`ohtv.db.stages.push_pr_links`: a forward pass tracks the active PR
per branch while iterating actions in temporal order, and a backward
pass attaches "orphan" pushes (those that occurred before any PR on
their branch) to the first subsequent PR opened on the same branch.

This stage runs after ``actions``. It is idempotent: contributions are
fully recomputed from the current actions on each run, so growing
conversations and prompt-revised action recognizers both Just Work
without leaving stale rows behind. ``change_refs`` rows themselves are
left in place because they are shared across conversations.

The stage is also written to be generic enough that issue #79
(direct-push-to-main detection) can add a sibling stage which records
``contribution_type="pushed"`` against a ``direct_push`` ``change_ref``
without any refactoring here.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass

from ohtv.db.models import Conversation, Repository
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stores import (
    ActionStore,
    ContributionsStore,
    LinkStore,
    RepoStore,
    StageStore,
)

log = logging.getLogger("ohtv")

STAGE_NAME = "contributions"


# GitHub/GitLab/Bitbucket PR URL patterns. We accept the same hosts as the
# refs stage so contribution detection stays in sync with repo recognition.
# Each entry is ``(pattern, host)`` so we can preserve the originating
# platform when building canonical repository URLs.
_PR_URL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"), "github.com"),
    (re.compile(r"https://gitlab\.com/(.+)/([^/]+)/-/merge_requests/(\d+)"), "gitlab.com"),
    (re.compile(r"https://bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)"), "bitbucket.org"),
]

# Default branches that indicate a "direct push" (a push that lands changes
# without going through a PR). Comparison is case-sensitive: virtually all
# real-world projects use lowercase ``main`` / ``master``, and matching
# lowercase only avoids spurious hits on unrelated branches that happen to
# share a case-insensitive prefix.
_DIRECT_PUSH_BRANCHES: frozenset[str] = frozenset({"main", "master"})


@dataclass(frozen=True)
class _PrIdent:
    """Identifying tuple for a PR detected on an action.

    ``host`` is the platform domain (``github.com``, ``gitlab.com``, or
    ``bitbucket.org``) and is used to construct the correct canonical
    repository URL. It defaults to ``github.com`` for the metadata
    fallback path, which is the only platform recognizers currently
    populate.
    """

    owner: str
    repo: str
    pr_number: int
    host: str = "github.com"


def process_contributions(
    conn: sqlite3.Connection, conversation: Conversation
) -> None:
    """Detect PR contributions for a conversation and persist them.

    Reads recognized actions from the database (the ``actions`` stage
    must have run first), derives ``created``/``merged``/``pushed``
    contributions, and writes them to ``conversation_contributions``,
    creating ``change_refs`` and ``repositories`` rows as needed.

    Args:
        conn: Database connection.
        conversation: The conversation to process.
    """
    action_store = ActionStore(conn)
    repo_store = RepoStore(conn)
    link_store = LinkStore(conn)
    contributions_store = ContributionsStore(conn)
    stage_store = StageStore(conn)

    # Reprocessing-safe: blow away this conversation's prior contributions
    # before re-deriving them. We never touch change_refs themselves, since
    # they may be referenced by other contributors.
    contributions_store.delete_contributions_for_conversation(conversation.id)

    # Actions are returned in temporal order (by id ASC) - see ActionStore.
    actions = action_store.get_by_conversation(conversation.id)

    # Forward-pass state for push-to-PR correlation. Mirrors push_pr_links.
    active_pr_per_branch: dict[str, int] = {}      # branch_key → change_ref_id
    first_pr_per_branch: dict[str, int] = {}       # branch_key → change_ref_id
    orphan_push_branches: set[str] = set()         # branch_keys awaiting backward pass

    # Fallback map for MERGE_PR actions that lack repo metadata: remember
    # which (owner, repo, host) was attached to each PR number we created
    # in this conversation, so a follow-up merge keeps the right platform.
    seen_pr_repo: dict[int, tuple[str, str, str]] = {}  # pr_number → (owner, repo, host)

    for action in actions:
        if action.action_type == ActionType.OPEN_PR:
            _handle_open_pr(
                action,
                conversation.id,
                repo_store,
                contributions_store,
                active_pr_per_branch,
                first_pr_per_branch,
                seen_pr_repo,
            )
        elif action.action_type == ActionType.MERGE_PR:
            _handle_merge_pr(
                action,
                conversation.id,
                repo_store,
                contributions_store,
                link_store,
                seen_pr_repo,
            )
        elif action.action_type == ActionType.GIT_PUSH:
            _handle_git_push(
                action,
                conversation.id,
                repo_store,
                contributions_store,
                active_pr_per_branch,
                orphan_push_branches,
            )

    # Backward pass: pushes that happened before any PR on their branch
    # link to the first PR subsequently opened on that branch (matches
    # push_pr_links semantics for the WRITE ref link).
    for branch_key in orphan_push_branches:
        change_ref_id = first_pr_per_branch.get(branch_key)
        if change_ref_id is not None:
            contributions_store.record_contribution(
                conversation.id, change_ref_id, "pushed"
            )

    stage_store.mark_complete(
        conversation.id, STAGE_NAME, conversation.event_count
    )

    log.debug(
        "contributions %s: %d action(s) scanned, %d active PR branch(es), "
        "%d orphan push(es)",
        conversation.id[:8],
        len(actions),
        len(active_pr_per_branch),
        len(orphan_push_branches),
    )


# ---------------------------------------------------------------------------
# Per-action handlers
# ---------------------------------------------------------------------------


def _handle_open_pr(
    action: ConversationAction,
    conversation_id: str,
    repo_store: RepoStore,
    contributions_store: ContributionsStore,
    active_pr_per_branch: dict[str, int],
    first_pr_per_branch: dict[str, int],
    seen_pr_repo: dict[int, tuple[str, str, str]],
) -> None:
    """Record a 'created' contribution for an OPEN_PR action.

    Updates the branch → change_ref maps so subsequent pushes on the
    same branch can be attributed to this PR.
    """
    ident = _identify_pr(action)
    if ident is None:
        log.debug(
            "OPEN_PR action %s in conversation %s has no parseable PR "
            "identity; skipping contribution",
            action.id,
            conversation_id[:8],
        )
        return

    repo_id = _upsert_repo_for(repo_store, ident)
    branch = _branch_from_metadata(action)
    change_ref_id = contributions_store.get_or_create_pr_change_ref(
        repo_id, ident.pr_number, branch=branch
    )
    contributions_store.record_contribution(
        conversation_id, change_ref_id, "created"
    )

    seen_pr_repo[ident.pr_number] = (ident.owner, ident.repo, ident.host)
    branch_key = _branch_key(ident.owner, ident.repo, branch)
    if branch_key is not None:
        active_pr_per_branch[branch_key] = change_ref_id
        first_pr_per_branch.setdefault(branch_key, change_ref_id)


def _handle_merge_pr(
    action: ConversationAction,
    conversation_id: str,
    repo_store: RepoStore,
    contributions_store: ContributionsStore,
    link_store: LinkStore,
    seen_pr_repo: dict[int, tuple[str, str, str]],
) -> None:
    """Record a 'merged' contribution for a MERGE_PR action.

    The recognizer does not currently attach repo info to MERGE_PR
    metadata - ``target`` is usually just the PR number from the
    command. We fall back through:

      1. A PR URL parsed from ``target`` (when the user merged by URL).
      2. ``metadata.owner`` / ``metadata.repo`` (future-proofing).
      3. The (pr_number → repo) map populated by earlier OPEN_PR
         actions in the same conversation.
      4. A single repository linked to this conversation via
         ``conversation_repos`` (only used if exactly one - we refuse to
         guess across multiple repos).

    If none of those resolve, the action is logged at DEBUG and
    skipped: better to miss a contribution than to attribute it to the
    wrong repo.
    """
    ident = _identify_pr(action)
    if ident is None:
        # Fall back to the PRs we have already seen in this conversation.
        pr_number = _pr_number_from_target(action.target)
        if pr_number is None:
            log.debug(
                "MERGE_PR action %s in conversation %s has no PR number; skipping",
                action.id,
                conversation_id[:8],
            )
            return
        owner_repo_host = seen_pr_repo.get(pr_number)
        if owner_repo_host is None:
            owner_repo_host = _single_repo_for_conversation(
                conversation_id, repo_store, link_store
            )
        if owner_repo_host is None:
            log.debug(
                "MERGE_PR action %s in conversation %s could not resolve a "
                "repo for PR #%d; skipping contribution",
                action.id,
                conversation_id[:8],
                pr_number,
            )
            return
        owner, repo, host = owner_repo_host
        ident = _PrIdent(
            owner=owner, repo=repo, pr_number=pr_number, host=host
        )

    repo_id = _upsert_repo_for(repo_store, ident)
    change_ref_id = contributions_store.get_or_create_pr_change_ref(
        repo_id, ident.pr_number
    )
    contributions_store.record_contribution(
        conversation_id, change_ref_id, "merged"
    )


def _handle_git_push(
    action: ConversationAction,
    conversation_id: str,
    repo_store: RepoStore,
    contributions_store: ContributionsStore,
    active_pr_per_branch: dict[str, int],
    orphan_push_branches: set[str],
) -> None:
    """Attribute a GIT_PUSH action to a contribution.

    Two paths:

    1. **Direct push to main/master**: if the remote branch is ``main`` or
       ``master`` and we have a commit range from the push output, create
       (or reuse) a ``direct_push`` ``change_ref`` with ``status="merged"``
       and record a ``pushed`` contribution. Direct pushes never participate
       in the PR-link backward pass because they have already landed.
    2. **Push to feature branch**: link to the active PR on that branch
       (forward pass) or queue as an orphan for the backward pass.
    """
    if not action.metadata:
        return
    branch = action.metadata.get("branch")
    owner = action.metadata.get("owner")
    repo = action.metadata.get("repo")
    if not branch or not owner or not repo:
        # Conservative: don't guess across repos.
        return

    # --- Direct push to main/master ---------------------------------------
    # Prefer the remote branch (what was actually updated on the server) but
    # fall back to the local branch name, which the recognizer records as
    # ``branch`` for backwards compatibility.
    remote_branch = action.metadata.get("remote_branch") or branch
    commit_range = action.metadata.get("commit_range")
    if remote_branch in _DIRECT_PUSH_BRANCHES and commit_range:
        # The push-target recognizer currently only emits owner/repo for
        # github.com, so we hard-code the host here. If/when GitLab and
        # Bitbucket push targets are recognized, ``_extract_repo_from_push_target``
        # should grow a ``host`` field and this call should consume it.
        repo_id = repo_store.upsert(
            Repository(
                id=None,
                canonical_url=f"https://github.com/{owner}/{repo}",
                fqn=f"{owner}/{repo}",
                short_name=repo,
            )
        )
        change_ref_id = contributions_store.get_or_create_direct_push_change_ref(
            repo_id,
            commit_range,
            branch=remote_branch,
            status="merged",
        )
        contributions_store.record_contribution(
            conversation_id, change_ref_id, "pushed"
        )
        return

    # --- Push to feature branch (existing PR-link path) -------------------
    branch_key = _branch_key(owner, repo, branch)
    if branch_key is None:
        return

    change_ref_id = active_pr_per_branch.get(branch_key)
    if change_ref_id is not None:
        contributions_store.record_contribution(
            conversation_id, change_ref_id, "pushed"
        )
    else:
        orphan_push_branches.add(branch_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identify_pr(action: ConversationAction) -> _PrIdent | None:
    """Return ``(owner, repo, pr_number)`` for a PR action, if derivable.

    Looks first at ``target`` (which is the canonical PR URL for
    ``OPEN_PR``) and falls back to ``metadata.owner`` / ``metadata.repo``
    combined with a number extracted from ``target``. Returns ``None``
    if no triple can be assembled.
    """
    target = action.target
    if target:
        for pattern, host in _PR_URL_PATTERNS:
            match = pattern.search(target)
            if match:
                owner, repo, num = match.group(1), match.group(2), match.group(3)
                try:
                    return _PrIdent(
                        owner=owner, repo=repo, pr_number=int(num), host=host
                    )
                except ValueError:
                    pass  # extremely unlikely - regex matches \d+

    metadata = action.metadata or {}
    owner = metadata.get("owner")
    repo = metadata.get("repo")
    pr_number = _pr_number_from_target(target)
    if owner and repo and pr_number is not None:
        return _PrIdent(owner=owner, repo=repo, pr_number=pr_number)
    return None


def _pr_number_from_target(target: str | None) -> int | None:
    """Best-effort PR number extraction from an action's ``target``.

    ``target`` for ``MERGE_PR`` is typically just a stringified number
    (from ``gh pr merge 123``); for ``OPEN_PR`` it is a full URL. We
    handle both shapes and return ``None`` if neither matches.
    """
    if not target:
        return None
    for pattern, _host in _PR_URL_PATTERNS:
        match = pattern.search(target)
        if match:
            try:
                return int(match.group(3))
            except ValueError:
                return None
    # Bare digits, e.g. "123"
    if target.isdigit():
        try:
            return int(target)
        except ValueError:
            return None
    return None


def _branch_from_metadata(action: ConversationAction) -> str | None:
    """Pull a head branch name from an OPEN_PR action's metadata."""
    if not action.metadata:
        return None
    branch = action.metadata.get("head_branch")
    return branch if isinstance(branch, str) and branch else None


def _branch_key(owner: str | None, repo: str | None, branch: str | None) -> str | None:
    """Build the ``owner/repo:branch`` key used for push correlation.

    Returns ``None`` unless all three components are present - we
    deliberately refuse partial matches to avoid cross-repo confusion.
    """
    if not owner or not repo or not branch:
        return None
    return f"{owner}/{repo}:{branch}"


def _upsert_repo_for(repo_store: RepoStore, ident: _PrIdent) -> int:
    """Upsert a Repository row from a PR identity and return its ID.

    The canonical URL is built from ``ident.host`` so GitHub, GitLab,
    and Bitbucket PRs each round-trip into the correct upstream URL.
    Mirrors the platform handling in :mod:`ohtv.db.stages.refs`.
    """
    repo = Repository(
        id=None,
        canonical_url=f"https://{ident.host}/{ident.owner}/{ident.repo}",
        fqn=f"{ident.owner}/{ident.repo}",
        short_name=ident.repo,
    )
    return repo_store.upsert(repo)


def _single_repo_for_conversation(
    conversation_id: str,
    repo_store: RepoStore,
    link_store: LinkStore,
) -> tuple[str, str, str] | None:
    """If exactly one repo is linked to a conversation, return its ``(owner, repo, host)``.

    Used as a last-resort fallback for MERGE_PR actions that have no
    repo info of their own. Refuses to choose if there are zero or
    multiple linked repos. ``host`` is parsed from the linked
    repository's ``canonical_url`` so the platform is preserved across
    the fallback path.
    """
    linked = link_store.get_repos_for_conversation(conversation_id)
    if len(linked) != 1:
        return None
    repo_id, _link_type = linked[0]
    repo = repo_store.get_by_id(repo_id)
    if repo is None or "/" not in repo.fqn:
        return None
    owner, _, name = repo.fqn.partition("/")
    if not owner or not name:
        return None
    host = _host_from_canonical_url(repo.canonical_url)
    return owner, name, host


def _host_from_canonical_url(canonical_url: str | None) -> str:
    """Extract the host (e.g. ``github.com``) from a canonical repo URL.

    Defaults to ``github.com`` if the URL is missing or unparseable, to
    match the historical assumption in this stage.
    """
    if canonical_url:
        match = re.match(r"https?://([^/]+)/", canonical_url)
        if match:
            return match.group(1)
    return "github.com"
