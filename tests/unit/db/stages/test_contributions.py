"""Tests for the contributions detection stage."""

from __future__ import annotations

import sqlite3

import pytest

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, LinkType, Repository
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.contributions import (
    STAGE_NAME,
    _branch_key,
    _identify_pr,
    _pr_number_from_target,
    _PrIdent,
    process_contributions,
)
from ohtv.db.stores import (
    ActionStore,
    ContributionsStore,
    ConversationStore,
    LinkStore,
    RepoStore,
    StageStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn():
    """In-memory DB with the full migration chain applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()


def _register_conversation(
    db_conn: sqlite3.Connection,
    conv_id: str = "conv-1",
    event_count: int = 5,
) -> Conversation:
    conv = Conversation(
        id=conv_id,
        location=f"/tmp/{conv_id}",
        event_count=event_count,
    )
    ConversationStore(db_conn).upsert(conv)
    return conv


def _insert_action(
    db_conn: sqlite3.Connection,
    conversation_id: str,
    action_type: ActionType,
    target: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Insert a single action and return its DB id."""
    return ActionStore(db_conn).insert(
        ConversationAction(
            id=None,
            conversation_id=conversation_id,
            action_type=action_type,
            target=target,
            metadata=metadata,
        )
    )


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestIdentifyPr:
    def test_from_github_pr_url(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
        )
        ident = _identify_pr(action)
        assert ident == _PrIdent(
            owner="acme", repo="widgets", pr_number=42, host="github.com"
        )

    def test_from_gitlab_mr_url(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.OPEN_PR,
            target="https://gitlab.com/acme/widgets/-/merge_requests/17",
        )
        ident = _identify_pr(action)
        assert ident == _PrIdent(
            owner="acme", repo="widgets", pr_number=17, host="gitlab.com"
        )

    def test_from_bitbucket_pr_url(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.OPEN_PR,
            target="https://bitbucket.org/acme/widgets/pull-requests/9",
        )
        ident = _identify_pr(action)
        assert ident == _PrIdent(
            owner="acme", repo="widgets", pr_number=9, host="bitbucket.org"
        )

    def test_falls_back_to_metadata_when_target_is_bare_number(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.MERGE_PR,
            target="42",
            metadata={"owner": "acme", "repo": "widgets"},
        )
        ident = _identify_pr(action)
        # Metadata fallback path has no URL to inspect, so it defaults to
        # github.com - this matches the recognizer's current behavior.
        assert ident == _PrIdent(
            owner="acme", repo="widgets", pr_number=42, host="github.com"
        )

    def test_returns_none_when_target_is_bare_number_without_metadata(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.MERGE_PR,
            target="42",
            metadata={"source": "github"},
        )
        assert _identify_pr(action) is None

    def test_returns_none_when_nothing_parseable(self):
        action = ConversationAction(
            id=1,
            conversation_id="c",
            action_type=ActionType.OPEN_PR,
            target=None,
            metadata=None,
        )
        assert _identify_pr(action) is None


class TestPrNumberFromTarget:
    def test_none(self):
        assert _pr_number_from_target(None) is None

    def test_url(self):
        assert _pr_number_from_target(
            "https://github.com/o/r/pull/55"
        ) == 55

    def test_bare_digits(self):
        assert _pr_number_from_target("123") == 123

    def test_garbage(self):
        assert _pr_number_from_target("nope") is None


class TestBranchKey:
    def test_full(self):
        assert _branch_key("o", "r", "feature/x") == "o/r:feature/x"

    def test_missing_owner(self):
        assert _branch_key(None, "r", "b") is None

    def test_missing_branch(self):
        assert _branch_key("o", "r", None) is None


# ---------------------------------------------------------------------------
# process_contributions - end-to-end
# ---------------------------------------------------------------------------


class TestProcessContributions:
    def test_open_pr_creates_change_ref_and_created_contribution(self, db_conn):
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)

        store = ContributionsStore(db_conn)
        contributions = store.get_contributions_for_conversation(conv.id)
        assert len(contributions) == 1
        assert contributions[0].contribution_type == "created"

        change_ref = store.get_change_ref(contributions[0].change_ref_id)
        assert change_ref is not None
        assert change_ref.pr_number == 42
        assert change_ref.change_type == "pr"
        assert change_ref.status == "pending"
        assert change_ref.branch == "feature/x"

        # Repository row was upserted.
        repo = RepoStore(db_conn).get_by_id(change_ref.repo_id)
        assert repo is not None
        assert repo.fqn == "acme/widgets"
        assert repo.canonical_url == "https://github.com/acme/widgets"

    def test_open_pr_on_gitlab_preserves_canonical_url(self, db_conn):
        """OPEN_PR for a GitLab MR must upsert a gitlab.com repo, not github.com."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://gitlab.com/acme/widgets/-/merge_requests/17",
            metadata={"head_branch": "feature/x"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1
        change_ref = ContributionsStore(db_conn).get_change_ref(
            contributions[0].change_ref_id
        )
        assert change_ref is not None
        repo = RepoStore(db_conn).get_by_id(change_ref.repo_id)
        assert repo is not None
        assert repo.fqn == "acme/widgets"
        assert repo.canonical_url == "https://gitlab.com/acme/widgets"

    def test_open_pr_on_bitbucket_preserves_canonical_url(self, db_conn):
        """OPEN_PR for a Bitbucket PR must upsert a bitbucket.org repo, not github.com."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://bitbucket.org/acme/widgets/pull-requests/9",
            metadata={"head_branch": "feature/x"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1
        change_ref = ContributionsStore(db_conn).get_change_ref(
            contributions[0].change_ref_id
        )
        assert change_ref is not None
        repo = RepoStore(db_conn).get_by_id(change_ref.repo_id)
        assert repo is not None
        assert repo.fqn == "acme/widgets"
        assert repo.canonical_url == "https://bitbucket.org/acme/widgets"

    def test_merge_pr_on_gitlab_preserves_canonical_url(self, db_conn):
        """MERGE_PR for a GitLab MR (by URL) must upsert a gitlab.com repo."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="https://gitlab.com/acme/widgets/-/merge_requests/17",
            metadata={"source": "gitlab"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1
        change_ref = ContributionsStore(db_conn).get_change_ref(
            contributions[0].change_ref_id
        )
        assert change_ref is not None
        repo = RepoStore(db_conn).get_by_id(change_ref.repo_id)
        assert repo is not None
        assert repo.canonical_url == "https://gitlab.com/acme/widgets"

    def test_merge_pr_creates_change_ref_and_merged_contribution(self, db_conn):
        conv = _register_conversation(db_conn)
        # Merge by URL is the most reliable shape - covers the common case
        # where the recognizer was able to attach the canonical URL.
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1
        assert contributions[0].contribution_type == "merged"

    def test_merge_pr_with_only_pr_number_uses_earlier_open_pr_repo(self, db_conn):
        """MERGE_PR after OPEN_PR in same conversation should reuse the repo."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="42",  # bare number from `gh pr merge 42`
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        types = sorted(c.contribution_type for c in contributions)
        assert types == ["created", "merged"]
        # Both contributions point at the same change_ref.
        assert len({c.change_ref_id for c in contributions}) == 1

    def test_merge_pr_with_unparseable_target_is_skipped(self, db_conn):
        """If the target is neither a URL nor a bare number, skip cleanly."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="not-a-number-or-url",
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )

    def test_merge_pr_with_unresolvable_repo_is_skipped(self, db_conn):
        """No OPEN_PR, no repo link, no URL → log-and-skip, not crash."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="42",
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert contributions == []
        # No change_ref was created either.
        cursor = db_conn.execute("SELECT COUNT(*) FROM change_refs")
        assert cursor.fetchone()[0] == 0

    def test_merge_pr_uses_single_linked_repo_as_fallback(self, db_conn):
        """If the conv is linked to exactly one repo, use it for unresolved MERGE_PR."""
        conv = _register_conversation(db_conn)
        repo_id = RepoStore(db_conn).upsert(
            Repository(
                id=None,
                canonical_url="https://github.com/acme/widgets",
                fqn="acme/widgets",
                short_name="widgets",
            )
        )
        LinkStore(db_conn).link_repo(conv.id, repo_id, LinkType.READ)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="7",
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1
        cr = ContributionsStore(db_conn).get_change_ref(
            contributions[0].change_ref_id
        )
        assert cr is not None
        assert cr.repo_id == repo_id
        assert cr.pr_number == 7

    def test_merge_pr_with_multiple_linked_repos_is_skipped(self, db_conn):
        """We refuse to guess across repos."""
        conv = _register_conversation(db_conn)
        repo_store = RepoStore(db_conn)
        a = repo_store.upsert(
            Repository(
                id=None,
                canonical_url="https://github.com/acme/widgets",
                fqn="acme/widgets",
                short_name="widgets",
            )
        )
        b = repo_store.upsert(
            Repository(
                id=None,
                canonical_url="https://github.com/acme/gadgets",
                fqn="acme/gadgets",
                short_name="gadgets",
            )
        )
        link_store = LinkStore(db_conn)
        link_store.link_repo(conv.id, a, LinkType.READ)
        link_store.link_repo(conv.id, b, LinkType.READ)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.MERGE_PR,
            target="9",
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )

    def test_git_push_after_open_pr_links_to_pr(self, db_conn):
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        types = sorted(c.contribution_type for c in contributions)
        assert types == ["created", "pushed"]
        # Both link to the same change_ref (the PR).
        assert len({c.change_ref_id for c in contributions}) == 1

    def test_git_push_before_open_pr_links_via_backward_pass(self, db_conn):
        """An orphan push gets attributed to the first PR opened on its branch."""
        conv = _register_conversation(db_conn)
        # Push first.
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )
        # PR opened later.
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        types = sorted(c.contribution_type for c in contributions)
        assert types == ["created", "pushed"]

    def test_git_push_without_pr_creates_no_contribution(self, db_conn):
        """A push to a branch that never gets a PR (in this conversation) is ignored."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )

    def test_git_push_missing_metadata_is_ignored(self, db_conn):
        conv = _register_conversation(db_conn)
        # Push action with no metadata at all.
        _insert_action(db_conn, conv.id, ActionType.GIT_PUSH, target=None)
        # Push action with branch but no owner/repo (conservative skip).
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_PUSH,
            target="origin",
            metadata={"branch": "feature/x"},
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )

    def test_git_push_to_different_branch_does_not_link(self, db_conn):
        """Push to branch B must not be linked to PR on branch A."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/a",
                "owner": "acme",
                "repo": "widgets",
            },
        )
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/b",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        # Only the PR creation; the push on a different branch is ignored.
        types = [c.contribution_type for c in contributions]
        assert types == ["created"]

    def test_multiple_conversations_share_one_change_ref(self, db_conn):
        """Two conversations contributing to PR #42 produce a single change_ref."""
        conv_a = _register_conversation(db_conn, conv_id="conv-a")
        conv_b = _register_conversation(db_conn, conv_id="conv-b")
        for conv in (conv_a, conv_b):
            _insert_action(
                db_conn,
                conv.id,
                ActionType.OPEN_PR,
                target="https://github.com/acme/widgets/pull/42",
                metadata={
                    "head_branch": "feature/x",
                    "owner": "acme",
                    "repo": "widgets",
                },
            )
            process_contributions(db_conn, conv)

        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM change_refs WHERE pr_number = 42"
        )
        assert cursor.fetchone()[0] == 1

        cursor = db_conn.execute(
            "SELECT conversation_id FROM conversation_contributions "
            "WHERE contribution_type = 'created'"
        )
        contributors = {row[0] for row in cursor.fetchall()}
        assert contributors == {"conv-a", "conv-b"}

    def test_reprocessing_is_idempotent(self, db_conn):
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )

        process_contributions(db_conn, conv)
        process_contributions(db_conn, conv)  # replay

        contributions = ContributionsStore(db_conn).get_contributions_for_conversation(
            conv.id
        )
        assert len(contributions) == 1

    def test_reprocessing_after_action_removed_clears_old_contribution(
        self, db_conn
    ):
        """If actions change between runs, stale contributions are removed."""
        conv = _register_conversation(db_conn)
        action_id = _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target="https://github.com/acme/widgets/pull/42",
            metadata={
                "head_branch": "feature/x",
                "owner": "acme",
                "repo": "widgets",
            },
        )
        process_contributions(db_conn, conv)
        assert (
            len(
                ContributionsStore(db_conn).get_contributions_for_conversation(
                    conv.id
                )
            )
            == 1
        )

        # Simulate a recognizer update that no longer produces the action.
        db_conn.execute("DELETE FROM actions WHERE id = ?", (action_id,))

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )
        # change_ref persists in case other conversations contributed.
        cursor = db_conn.execute("SELECT COUNT(*) FROM change_refs")
        assert cursor.fetchone()[0] == 1

    def test_marks_stage_complete(self, db_conn):
        conv = _register_conversation(db_conn, event_count=12)
        process_contributions(db_conn, conv)

        stage = StageStore(db_conn).get(conv.id, STAGE_NAME)
        assert stage is not None
        assert stage.event_count == 12
        # Future runs with the same event count don't need reprocessing.
        assert (
            StageStore(db_conn).needs_processing(
                conv.id, STAGE_NAME, conv.event_count
            )
            is False
        )

    def test_no_actions_marks_stage_complete_with_no_contributions(self, db_conn):
        conv = _register_conversation(db_conn)
        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )
        stage = StageStore(db_conn).get(conv.id, STAGE_NAME)
        assert stage is not None

    def test_open_pr_with_no_parseable_identity_skipped(self, db_conn):
        """OPEN_PR with no URL and no owner/repo metadata is logged and skipped."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.OPEN_PR,
            target=None,
            metadata={"source": "github"},
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )

    def test_ignores_non_contribution_action_types(self, db_conn):
        """Other actions (commits, comments, edits) don't produce contributions."""
        conv = _register_conversation(db_conn)
        _insert_action(
            db_conn,
            conv.id,
            ActionType.GIT_COMMIT,
            target="abc1234",
            metadata={"commit_message": "wip"},
        )
        _insert_action(
            db_conn,
            conv.id,
            ActionType.PR_COMMENT,
            target="42",
            metadata={"source": "github"},
        )
        _insert_action(
            db_conn,
            conv.id,
            ActionType.EDIT_CODE,
            target="src/foo.py",
        )

        process_contributions(db_conn, conv)

        assert (
            ContributionsStore(db_conn).get_contributions_for_conversation(conv.id)
            == []
        )


# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------


def test_stage_registered_in_registry():
    from ohtv.db.stages import STAGES

    assert "contributions" in STAGES
    assert STAGES["contributions"] is process_contributions
