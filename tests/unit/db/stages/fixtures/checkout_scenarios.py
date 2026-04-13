"""Test fixtures for git checkout/branch tracking scenarios.

These fixtures represent patterns where we need to infer branch context
from git checkout/switch commands because the git push command or output
doesn't explicitly specify the branch.

## Problem Statement

When we see a `git push` without branch info in the command or output:
- `git push` (no branch specified)
- Output: "Everything up-to-date" (no branch info)

We need to infer the branch from the last `git checkout` or `git switch`
command in the same repository.

## Key Challenges

1. **Repo path extraction**: Commands often use `cd /path && git checkout...`
   Need to extract the working directory from the command.

2. **Path normalization**: Paths may be absolute, relative, or use ~.
   Need to normalize to match checkout paths to push paths.

3. **Multiple repos**: Agent may work in multiple repos concurrently.
   Need to track branch state per repo, not globally.

4. **Checkout variants**: Need to handle:
   - `git checkout <branch>`
   - `git checkout -b <branch>`
   - `git switch <branch>`
   - `git switch -c <branch>`
   - `git checkout <commit>` (detached HEAD)

5. **Push variants where we DO have branch info (no inference needed):
   - Output: `abc123..def456  branch -> branch`
   - Output: `* [new branch]  branch -> branch`
   - Command: `git push origin branch-name`

## Design Approach

During action recognition for GIT_PUSH:
1. Try to extract branch from push output (most reliable)
2. If not found, try to extract from push command
3. If still not found, look backward through events for last checkout
   in the same repo directory

Each scenario includes:
- Description of the pattern
- Sequence of events (terminal commands + outputs)
- Expected branch state at each point
- Expected push metadata after inference
"""

from dataclasses import dataclass, field


@dataclass
class TerminalEvent:
    """Represents a terminal command and its output."""
    id: str
    command: str
    output: str
    exit_code: int = 0


@dataclass 
class ExpectedPushMetadata:
    """Expected metadata for a GIT_PUSH action after checkout inference."""
    event_id: str
    branch: str | None
    owner: str | None = None
    repo: str | None = None
    inferred_from_checkout: bool = False


@dataclass
class CheckoutScenario:
    """A complete test scenario for checkout tracking."""
    description: str
    conversation_id: str
    events: list[TerminalEvent]
    # Expected branch state after each checkout event
    # Map of event_id -> {repo_path: branch}
    expected_branch_state: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # Expected metadata for push actions
    expected_push_metadata: list[ExpectedPushMetadata] = field(default_factory=list)
    notes: str = ""


# =============================================================================
# SCENARIO 1: Simple checkout then push (branch in push output)
# =============================================================================
# Pattern: Agent checks out a branch, makes changes, pushes.
# The push output contains the branch info, so NO inference needed.
# This is the baseline case showing when inference is NOT required.

SCENARIO_CHECKOUT_THEN_PUSH_WITH_OUTPUT = CheckoutScenario(
    description="Checkout branch, push with branch info in output (no inference needed)",
    conversation_id="conv-checkout-001",
    events=[
        # Checkout feature branch
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout -b feature/new-button",
            output="Switched to a new branch 'feature/new-button'",
        ),
        # Push - output contains branch info
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git push -u origin",
            output="To https://github.com/acme/widgets.git\n * [new branch]      feature/new-button -> feature/new-button",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "feature/new-button"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-002",
            branch="feature/new-button",  # From output, not inference
            owner="acme",
            repo="widgets",
            inferred_from_checkout=False,
        ),
    ],
    notes="Push output contains branch, so no checkout inference needed",
)


# =============================================================================
# SCENARIO 2: Push without branch info - NEEDS INFERENCE
# =============================================================================
# This is the KEY scenario - push output is "Everything up-to-date" or similar
# with no branch information. We must infer from prior checkout.

SCENARIO_PUSH_NEEDS_INFERENCE = CheckoutScenario(
    description="Push with no branch info in output - requires checkout inference",
    conversation_id="conv-checkout-002",
    events=[
        # Checkout feature branch
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout feature/my-feature",
            output="Switched to branch 'feature/my-feature'",
        ),
        # Make commits...
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git commit -m 'Add feature'",
            output="[feature/my-feature abc1234] Add feature\n 1 file changed",
        ),
        # Push - output has NO branch info (common when already up to date)
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "feature/my-feature"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-003",
            branch="feature/my-feature",  # INFERRED from checkout
            owner=None,  # Can't determine from "Everything up-to-date"
            repo=None,
            inferred_from_checkout=True,
        ),
    ],
    notes="This is the core case requiring checkout tracking",
)


# =============================================================================
# SCENARIO 3: Multiple checkouts, last one wins
# =============================================================================
# Pattern: Agent switches between branches, push should use the most recent checkout.

SCENARIO_MULTIPLE_CHECKOUTS = CheckoutScenario(
    description="Multiple checkouts, push uses most recent branch",
    conversation_id="conv-checkout-003",
    events=[
        # Start on main
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout main",
            output="Switched to branch 'main'",
        ),
        # Switch to feature-a
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git checkout feature-a",
            output="Switched to branch 'feature-a'",
        ),
        # Switch to feature-b
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/project && git checkout feature-b",
            output="Switched to branch 'feature-b'",
        ),
        # Push - no branch in output
        TerminalEvent(
            id="evt-004",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "main"},
        "evt-002": {"/workspace/project": "feature-a"},
        "evt-003": {"/workspace/project": "feature-b"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-004",
            branch="feature-b",  # Most recent checkout
            inferred_from_checkout=True,
        ),
    ],
    notes="Most recent checkout determines current branch for inference",
)


# =============================================================================
# SCENARIO 4: Multiple repos, independent branch tracking
# =============================================================================
# Pattern: Agent works in multiple repos, each has independent branch state.

SCENARIO_MULTIPLE_REPOS = CheckoutScenario(
    description="Multiple repos have independent branch tracking",
    conversation_id="conv-checkout-004",
    events=[
        # Checkout in repo A
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/frontend && git checkout feature/ui",
            output="Switched to branch 'feature/ui'",
        ),
        # Checkout in repo B (different branch)
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/backend && git checkout feature/api",
            output="Switched to branch 'feature/api'",
        ),
        # Push in repo B - no branch in output
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/backend && git push",
            output="Everything up-to-date",
        ),
        # Push in repo A - no branch in output
        TerminalEvent(
            id="evt-004",
            command="cd /workspace/frontend && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/frontend": "feature/ui"},
        "evt-002": {
            "/workspace/frontend": "feature/ui",
            "/workspace/backend": "feature/api",
        },
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-003",
            branch="feature/api",  # From /workspace/backend checkout
            inferred_from_checkout=True,
        ),
        ExpectedPushMetadata(
            event_id="evt-004",
            branch="feature/ui",  # From /workspace/frontend checkout
            inferred_from_checkout=True,
        ),
    ],
    notes="Each repo path tracks its own current branch independently",
)


# =============================================================================
# SCENARIO 5: git switch command variants
# =============================================================================
# Pattern: Agent uses modern `git switch` command instead of `git checkout`.

SCENARIO_GIT_SWITCH = CheckoutScenario(
    description="git switch commands tracked for branch context",
    conversation_id="conv-checkout-005",
    events=[
        # Create new branch with git switch -c
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git switch -c hotfix/urgent",
            output="Switched to a new branch 'hotfix/urgent'",
        ),
        # Push - no branch in output
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
        # Switch to existing branch
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/project && git switch main",
            output="Switched to branch 'main'",
        ),
        # Push - no branch in output
        TerminalEvent(
            id="evt-004",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "hotfix/urgent"},
        "evt-003": {"/workspace/project": "main"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-002",
            branch="hotfix/urgent",
            inferred_from_checkout=True,
        ),
        ExpectedPushMetadata(
            event_id="evt-004",
            branch="main",
            inferred_from_checkout=True,
        ),
    ],
    notes="git switch -c and git switch should both update branch tracking",
)


# =============================================================================
# SCENARIO 6: Detached HEAD clears branch tracking
# =============================================================================
# Pattern: Checkout a specific commit (detached HEAD) - no current branch.

SCENARIO_DETACHED_HEAD = CheckoutScenario(
    description="Checkout specific commit results in no current branch",
    conversation_id="conv-checkout-006",
    events=[
        # Start on a branch
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout feature/test",
            output="Switched to branch 'feature/test'",
        ),
        # Checkout specific commit (detached HEAD)
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git checkout abc123def",
            output="Note: switching to 'abc123def'.\n\nYou are in 'detached HEAD' state.",
        ),
        # Push - no branch info, and no current branch
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/project && git push",
            output="fatal: You are not currently on a branch.",
            exit_code=1,
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "feature/test"},
        "evt-002": {"/workspace/project": None},  # Detached HEAD = no branch
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-003",
            branch=None,  # Can't infer - detached HEAD
            inferred_from_checkout=False,  # No inference possible
        ),
    ],
    notes="Detached HEAD state clears current branch tracking",
)


# =============================================================================
# SCENARIO 7: Checkout -b with start point
# =============================================================================
# Pattern: git checkout -b <new-branch> <start-point>

SCENARIO_CHECKOUT_WITH_START_POINT = CheckoutScenario(
    description="Checkout -b with start point still tracks new branch",
    conversation_id="conv-checkout-007",
    events=[
        # Create branch from specific commit
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout -b feature/new origin/main",
            output="Branch 'feature/new' set up to track 'origin/main'.\nSwitched to a new branch 'feature/new'",
        ),
        # Push - no branch in output
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "feature/new"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-002",
            branch="feature/new",  # New local branch, not origin/main
            inferred_from_checkout=True,
        ),
    ],
    notes="Track the new local branch name, not the start point",
)


# =============================================================================
# SCENARIO 8: Working directory variations
# =============================================================================
# Pattern: Different ways of specifying working directory

SCENARIO_WORKING_DIR_VARIATIONS = CheckoutScenario(
    description="Various working directory specification patterns",
    conversation_id="conv-checkout-008",
    events=[
        # Absolute path
        TerminalEvent(
            id="evt-001",
            command="cd /workspace/project && git checkout feature-a",
            output="Switched to branch 'feature-a'",
        ),
        # Using && with different spacing
        TerminalEvent(
            id="evt-002",
            command="cd /workspace/project&&git checkout feature-b",
            output="Switched to branch 'feature-b'",
        ),
        # Using ; instead of &&
        TerminalEvent(
            id="evt-003",
            command="cd /workspace/project ; git checkout feature-c",
            output="Switched to branch 'feature-c'",
        ),
        # Push from same directory
        TerminalEvent(
            id="evt-004",
            command="cd /workspace/project && git push",
            output="Everything up-to-date",
        ),
    ],
    expected_branch_state={
        "evt-001": {"/workspace/project": "feature-a"},
        "evt-002": {"/workspace/project": "feature-b"},
        "evt-003": {"/workspace/project": "feature-c"},
    },
    expected_push_metadata=[
        ExpectedPushMetadata(
            event_id="evt-004",
            branch="feature-c",  # Most recent
            inferred_from_checkout=True,
        ),
    ],
    notes="Handle various command separator patterns",
)


# =============================================================================
# All scenarios for easy iteration in tests
# =============================================================================

ALL_CHECKOUT_SCENARIOS = [
    SCENARIO_CHECKOUT_THEN_PUSH_WITH_OUTPUT,
    SCENARIO_PUSH_NEEDS_INFERENCE,
    SCENARIO_MULTIPLE_CHECKOUTS,
    SCENARIO_MULTIPLE_REPOS,
    SCENARIO_GIT_SWITCH,
    SCENARIO_DETACHED_HEAD,
    SCENARIO_CHECKOUT_WITH_START_POINT,
    SCENARIO_WORKING_DIR_VARIATIONS,
]

# Scenarios where inference IS needed (for targeted testing)
SCENARIOS_NEEDING_INFERENCE = [
    SCENARIO_PUSH_NEEDS_INFERENCE,
    SCENARIO_MULTIPLE_CHECKOUTS,
    SCENARIO_MULTIPLE_REPOS,
    SCENARIO_GIT_SWITCH,
    SCENARIO_CHECKOUT_WITH_START_POINT,
    SCENARIO_WORKING_DIR_VARIATIONS,
]
