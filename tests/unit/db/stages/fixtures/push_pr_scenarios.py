"""Test fixtures for push-to-PR linking scenarios.

These fixtures represent sanitized versions of real-world patterns observed
in OpenHands conversations. They can be used to test the push_pr_links
processor and to construct new test scenarios.

Each scenario includes:
- Description of the pattern
- Sequence of actions (in temporal order)
- Expected linking behavior
"""

from ohtv.db.models.action import ActionType, ConversationAction


def make_push_action(
    id: int,
    event_id: str,
    conversation_id: str,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> ConversationAction:
    """Helper to create a GIT_PUSH action with metadata."""
    target = f"https://github.com/{owner}/{repo}.git" if owner and repo else None
    metadata = {}
    if branch:
        metadata["branch"] = branch
    if owner:
        metadata["owner"] = owner
    if repo:
        metadata["repo"] = repo
    
    return ConversationAction(
        id=id,
        conversation_id=conversation_id,
        action_type=ActionType.GIT_PUSH,
        target=target,
        metadata=metadata if metadata else None,
        event_id=event_id,
    )


def make_pr_action(
    id: int,
    event_id: str,
    conversation_id: str,
    pr_number: int,
    owner: str | None = None,
    repo: str | None = None,
    head_branch: str | None = None,
) -> ConversationAction:
    """Helper to create an OPEN_PR action with metadata."""
    target = f"https://github.com/{owner}/{repo}/pull/{pr_number}" if owner and repo else None
    metadata = {"source": "github"}
    if head_branch:
        metadata["head_branch"] = head_branch
    if owner:
        metadata["owner"] = owner
    if repo:
        metadata["repo"] = repo
    
    return ConversationAction(
        id=id,
        conversation_id=conversation_id,
        action_type=ActionType.OPEN_PR,
        target=target,
        metadata=metadata,
        event_id=event_id,
    )


# =============================================================================
# SCENARIO 1: Simple single-branch workflow
# =============================================================================
# Pattern: One branch, one PR, multiple pushes
# This is the most common pattern - agent works on a feature branch,
# pushes commits, creates PR, then pushes more updates.

SCENARIO_SIMPLE_SINGLE_BRANCH = {
    "description": "Single branch with one PR and multiple pushes",
    "conversation_id": "conv-simple-001",
    "actions": [
        # Initial push to feature branch
        make_push_action(
            id=1, event_id="evt-001", conversation_id="conv-simple-001",
            owner="acme", repo="widgets", branch="feature/add-button",
        ),
        # Create PR
        make_pr_action(
            id=2, event_id="evt-002", conversation_id="conv-simple-001",
            pr_number=42, owner="acme", repo="widgets", head_branch="feature/add-button",
        ),
        # Push update after PR review feedback
        make_push_action(
            id=3, event_id="evt-003", conversation_id="conv-simple-001",
            owner="acme", repo="widgets", branch="feature/add-button",
        ),
        # Another update
        make_push_action(
            id=4, event_id="evt-004", conversation_id="conv-simple-001",
            owner="acme", repo="widgets", branch="feature/add-button",
        ),
    ],
    "expected_links": [
        # All pushes to feature/add-button should link to PR #42
        ("conv-simple-001", "https://github.com/acme/widgets/pull/42"),
    ],
}


# =============================================================================
# SCENARIO 2: Multiple branches, multiple PRs (sequential)
# =============================================================================
# Pattern: Agent creates multiple PRs on different branches in sequence.
# Each branch gets its own PR. Observed in conversations where agent
# iterates on fixes, creating separate PRs for each attempt.

SCENARIO_MULTI_BRANCH_SEQUENTIAL = {
    "description": "Multiple branches with separate PRs created sequentially",
    "conversation_id": "conv-multi-001",
    "actions": [
        # First feature branch
        make_push_action(
            id=1, event_id="evt-001", conversation_id="conv-multi-001",
            owner="acme", repo="gadgets", branch="fix/typo-readme",
        ),
        make_pr_action(
            id=2, event_id="evt-002", conversation_id="conv-multi-001",
            pr_number=10, owner="acme", repo="gadgets", head_branch="fix/typo-readme",
        ),
        # Second feature branch (different fix)
        make_push_action(
            id=3, event_id="evt-003", conversation_id="conv-multi-001",
            owner="acme", repo="gadgets", branch="fix/broken-link",
        ),
        make_pr_action(
            id=4, event_id="evt-004", conversation_id="conv-multi-001",
            pr_number=11, owner="acme", repo="gadgets", head_branch="fix/broken-link",
        ),
        # Third feature branch
        make_push_action(
            id=5, event_id="evt-005", conversation_id="conv-multi-001",
            owner="acme", repo="gadgets", branch="fix/api-docs",
        ),
        make_pr_action(
            id=6, event_id="evt-006", conversation_id="conv-multi-001",
            pr_number=12, owner="acme", repo="gadgets", head_branch="fix/api-docs",
        ),
    ],
    "expected_links": [
        # Each branch's push links to its respective PR
        ("conv-multi-001", "https://github.com/acme/gadgets/pull/10"),  # fix/typo-readme
        ("conv-multi-001", "https://github.com/acme/gadgets/pull/11"),  # fix/broken-link
        ("conv-multi-001", "https://github.com/acme/gadgets/pull/12"),  # fix/api-docs
    ],
}


# =============================================================================
# SCENARIO 3: Multiple repositories
# =============================================================================
# Pattern: Agent works across multiple repos in one conversation.
# Same branch name might exist in different repos.
# This tests that we correctly qualify by owner/repo, not just branch.

SCENARIO_MULTI_REPO = {
    "description": "Same branch name in different repositories",
    "conversation_id": "conv-multirepo-001",
    "actions": [
        # Push to repo A
        make_push_action(
            id=1, event_id="evt-001", conversation_id="conv-multirepo-001",
            owner="acme", repo="frontend", branch="update-deps",
        ),
        make_pr_action(
            id=2, event_id="evt-002", conversation_id="conv-multirepo-001",
            pr_number=100, owner="acme", repo="frontend", head_branch="update-deps",
        ),
        # Push to repo B with SAME branch name
        make_push_action(
            id=3, event_id="evt-003", conversation_id="conv-multirepo-001",
            owner="acme", repo="backend", branch="update-deps",
        ),
        make_pr_action(
            id=4, event_id="evt-004", conversation_id="conv-multirepo-001",
            pr_number=200, owner="acme", repo="backend", head_branch="update-deps",
        ),
    ],
    "expected_links": [
        # Each repo's push links to its own PR, despite same branch name
        ("conv-multirepo-001", "https://github.com/acme/frontend/pull/100"),
        ("conv-multirepo-001", "https://github.com/acme/backend/pull/200"),
    ],
}


# =============================================================================
# SCENARIO 4: Push before PR creation (common flow)
# =============================================================================
# Pattern: Agent pushes branch, then creates PR from it.
# The push happens BEFORE the PR exists.

SCENARIO_PUSH_BEFORE_PR = {
    "description": "Push occurs before PR is created",
    "conversation_id": "conv-pushfirst-001",
    "actions": [
        # Push first (no PR yet)
        make_push_action(
            id=1, event_id="evt-001", conversation_id="conv-pushfirst-001",
            owner="acme", repo="tools", branch="feature/new-cli",
        ),
        # More work, another push
        make_push_action(
            id=2, event_id="evt-002", conversation_id="conv-pushfirst-001",
            owner="acme", repo="tools", branch="feature/new-cli",
        ),
        # Now create PR
        make_pr_action(
            id=3, event_id="evt-003", conversation_id="conv-pushfirst-001",
            pr_number=55, owner="acme", repo="tools", head_branch="feature/new-cli",
        ),
        # Push update after PR created
        make_push_action(
            id=4, event_id="evt-004", conversation_id="conv-pushfirst-001",
            owner="acme", repo="tools", branch="feature/new-cli",
        ),
    ],
    "expected_links": [
        # All pushes (before and after) should link to the PR
        # NOTE: Current implementation may not link pre-PR pushes correctly
        ("conv-pushfirst-001", "https://github.com/acme/tools/pull/55"),
    ],
    "notes": "Pushes before PR creation require temporal-aware linking (not yet implemented)",
}


# =============================================================================
# SCENARIO 5: Missing metadata (conservative behavior)
# =============================================================================
# Pattern: Push or PR is missing owner/repo metadata.
# Should NOT create a link to avoid incorrect associations.

SCENARIO_MISSING_METADATA = {
    "description": "Push missing repo metadata should not link",
    "conversation_id": "conv-missing-001",
    "actions": [
        # PR with full metadata
        make_pr_action(
            id=1, event_id="evt-001", conversation_id="conv-missing-001",
            pr_number=99, owner="acme", repo="app", head_branch="hotfix",
        ),
        # Push with branch but NO owner/repo (e.g., extraction failed)
        ConversationAction(
            id=2,
            conversation_id="conv-missing-001",
            action_type=ActionType.GIT_PUSH,
            target=None,
            metadata={"branch": "hotfix"},  # Missing owner/repo
            event_id="evt-002",
        ),
    ],
    "expected_links": [],  # No link should be created
}


# =============================================================================
# SCENARIO 6: Pushes to main (no PR association)
# =============================================================================
# Pattern: Some pushes go to main/master for initial setup.
# These don't have associated PRs and should not cause errors.

SCENARIO_MAIN_BRANCH_PUSHES = {
    "description": "Pushes to main branch without PR",
    "conversation_id": "conv-main-001",
    "actions": [
        # Initial push to main (repo setup)
        make_push_action(
            id=1, event_id="evt-001", conversation_id="conv-main-001",
            owner="acme", repo="new-project", branch="main",
        ),
        # Another setup push
        make_push_action(
            id=2, event_id="evt-002", conversation_id="conv-main-001",
            owner="acme", repo="new-project", branch="main",
        ),
        # Now feature work with PR
        make_push_action(
            id=3, event_id="evt-003", conversation_id="conv-main-001",
            owner="acme", repo="new-project", branch="feature/init",
        ),
        make_pr_action(
            id=4, event_id="evt-004", conversation_id="conv-main-001",
            pr_number=1, owner="acme", repo="new-project", head_branch="feature/init",
        ),
    ],
    "expected_links": [
        # Only the feature branch push links to PR
        # Main branch pushes have no PR to link to
        ("conv-main-001", "https://github.com/acme/new-project/pull/1"),
    ],
}


# =============================================================================
# SCENARIO 7: Branch reuse (temporal ordering challenge)
# =============================================================================
# Pattern: Same branch is used for multiple PRs over time.
# PR #1 created, merged, then PR #2 created from same branch.
# This requires temporal ordering to link correctly.
# CURRENT LIMITATION: Both pushes would link to last PR.

SCENARIO_BRANCH_REUSE = {
    "description": "Same branch reused for multiple PRs (temporal challenge)",
    "conversation_id": "conv-reuse-001",
    "actions": [
        # First PR
        make_pr_action(
            id=1, event_id="evt-001", conversation_id="conv-reuse-001",
            pr_number=20, owner="acme", repo="lib", head_branch="develop",
        ),
        make_push_action(
            id=2, event_id="evt-002", conversation_id="conv-reuse-001",
            owner="acme", repo="lib", branch="develop",
        ),
        # Second PR on same branch (after first was merged)
        make_pr_action(
            id=3, event_id="evt-003", conversation_id="conv-reuse-001",
            pr_number=25, owner="acme", repo="lib", head_branch="develop",
        ),
        make_push_action(
            id=4, event_id="evt-004", conversation_id="conv-reuse-001",
            owner="acme", repo="lib", branch="develop",
        ),
    ],
    "expected_links_ideal": [
        # Ideally: push #2 -> PR #20, push #4 -> PR #25
        ("conv-reuse-001", "https://github.com/acme/lib/pull/20"),
        ("conv-reuse-001", "https://github.com/acme/lib/pull/25"),
    ],
    "expected_links_current": [
        # Current behavior: both link to PR #25 (last in map)
        ("conv-reuse-001", "https://github.com/acme/lib/pull/25"),
    ],
    "notes": "Requires temporal ordering to link correctly (not yet implemented)",
}


# All scenarios for easy iteration in tests
ALL_SCENARIOS = [
    SCENARIO_SIMPLE_SINGLE_BRANCH,
    SCENARIO_MULTI_BRANCH_SEQUENTIAL,
    SCENARIO_MULTI_REPO,
    SCENARIO_PUSH_BEFORE_PR,
    SCENARIO_MISSING_METADATA,
    SCENARIO_MAIN_BRANCH_PUSHES,
    SCENARIO_BRANCH_REUSE,
]
